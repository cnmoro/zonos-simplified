"""Opt-in real native API integration tests: ZONOS_LIVE_URL=http://localhost:1919."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import unittest
import urllib.error
import urllib.request
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infer import synthesize


@unittest.skipUnless(os.environ.get('ZONOS_LIVE_URL'), 'Set ZONOS_LIVE_URL for real API tests')
class SavedVoicesAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.environ['ZONOS_LIVE_URL'].rstrip('/')
        cls.reference = ROOT / 'models/gguf/voices/English/Jett_en-energetic_M_1.wav'
        cls.audio = base64.b64encode(cls.reference.read_bytes()).decode()
        cls.output = ROOT / 'outputs/validation'
        cls.output.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.created = []
        self.prefix = 'API test ' + uuid.uuid4().hex[:10]

    def tearDown(self):
        for voice_id in self.created:
            self.call('DELETE', '/v2/voices/' + voice_id)

    def call(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
            headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def create(self, **extra):
        status, body = self.call('POST', '/v2/voices', {
            'name': self.prefix, 'language': 'pt_br', 'speaker_audio_base64': self.audio, **extra})
        self.assertEqual(status, 201, body)
        self.created.append(body['id'])
        return body

    def test_preprocess_generate_rename_delete_without_session(self):
        voice = self.create()
        self.assertTrue(voice['ready'])
        self.assertTrue(voice['persistent'])
        self.assertGreater(voice['preprocessing_ms'], 0)
        self.assertNotIn('embedding', voice)
        self.assertEqual(voice['embedding_dim'], 192)
        voice_id = voice['id']
        status, listed = self.call('GET', '/v2/voices')
        self.assertEqual(status, 200)
        self.assertIn(voice_id, [v['id'] for v in listed['voices']])
        _, speakers = self.call('GET', '/v2/speakers')
        self.assertTrue(next(v for v in speakers['speakers'] if v['id'] == voice_id)['ready'])
        _, vector = self.call('GET', f'/v2/speakers/{voice_id}/embedding')
        self.assertEqual(len(vector['embedding']), 192)
        for language, text in [('en', 'A ready voice.'), ('pt', 'Uma voz já pronta.')]:
            result = synthesize(self.base, text, language, self.output / f'saved-voice-{language}.wav', voice=voice_id)
            self.assertGreater(result['audio_seconds'], .1)
            # JSON transport must never re-upload audio for a saved id.
        status, changed = self.call('PATCH', '/v2/voices/' + voice_id, {'name': self.prefix + ' renamed'})
        self.assertEqual(status, 200)
        self.assertEqual(changed['id'], voice_id)
        self.assertEqual(changed['name'], self.prefix + ' renamed')
        status, _ = self.call('DELETE', '/v2/voices/' + voice_id)
        self.assertEqual(status, 200)
        self.assertEqual(self.call('GET', '/v2/voices/' + voice_id)[0], 404)
        self.created.remove(voice_id)

    def test_duplicate_does_not_overwrite_and_validation_is_actionable(self):
        voice = self.create()
        status, error = self.call('POST', '/v2/voices', {'name': self.prefix.upper(), 'speaker_audio_base64': self.audio})
        self.assertEqual(status, 409)
        self.assertEqual(error['voice_id'], voice['id'])
        for payload in [{'name': ' ', 'speaker_audio_base64': self.audio},
                        {'name': 'x', 'language': 'xx', 'speaker_audio_base64': self.audio},
                        {'name': 17, 'speaker_audio_base64': self.audio},
                        {'name': 'x', 'audio_path': '/etc/passwd'},
                        {'name': 'x', 'speaker_audio_base64': self.audio, 'speaker_embedding_id': voice['id']}]:
            self.assertEqual(self.call('POST', '/v2/voices', payload)[0], 422)
        self.assertEqual(self.call('POST', '/v2/voices', {'name': 'invalid', 'speaker_audio_base64': 'bm90IGF1ZGlv'})[0], 400)
        self.assertEqual(self.call('PATCH', '/v2/voices/' + voice['id'], {})[0], 422)

    def test_promote_temporary_voice_preprocesses_without_generation(self):
        session = {'X-TTS-Session-ID': uuid.uuid4().hex}
        status, temporary = self.call('POST', '/v2/speakers', {
            'label': 'temporary', 'speaker_audio_base64': self.audio, 'speaker_audio_name': self.reference.name}, session)
        self.assertEqual(status, 200)
        status, voice = self.call('POST', '/v2/voices', {
            'name': self.prefix, 'language': 'en_us', 'speaker_embedding_id': temporary['id']}, session)
        self.assertEqual(status, 201, voice)
        self.created.append(voice['id'])
        self.assertTrue(voice['ready'])
        # Read the resulting global voice without that session.
        self.assertEqual(self.call('GET', '/v2/voices/' + voice['id'])[0], 200)
        self.assertEqual(self.call('GET', '/v2/speakers/' + voice['id'] + '/embedding')[0], 200)

    def test_saved_voice_blending_without_session(self):
        _, listed = self.call('GET', '/v2/speakers')
        defaults = [voice for voice in listed['speakers'] if voice['is_default'] and not voice.get('persistent')]
        ids = []
        for i, source in enumerate(defaults[:2]):
            status, saved = self.call('POST', '/v2/voices', {
                'name': self.prefix + str(i), 'speaker_embedding_id': source['id']})
            self.assertEqual(status, 201, saved)
            ids.append(saved['id'])
            self.created.append(saved['id'])
        payload = {'text': 'Two voices blended.', 'language': 'en_us', 'speaker_mode': 'embedding',
                   'speaker_blend_embedding_id_a': ids[0], 'speaker_blend_embedding_id_b': ids[1],
                   'speaker_blend_t': 0.5, 'decoder': 'keep2_plain', 'stream': False, 'format': 'wav', 'max_tokens': 200}
        req = urllib.request.Request(self.base + '/v2/generate', json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=180) as response:
            with wave.open(io.BytesIO(response.read())) as audio:
                self.assertGreater(audio.getnframes(), 4410)

    def test_markdown_is_available_and_contains_complete_flows(self):
        with urllib.request.urlopen(self.base + '/agents.md') as response:
            self.assertIn('text/markdown', response.headers['Content-Type'])
            text = response.read().decode()
        for endpoint in ['/v2/voices', '/v2/generate', '/v2/speakers', '/v1/audio/speech']:
            self.assertIn(endpoint, text)
        for term in ['float32', 'speaker_mode', '409', 'X-TTS-Session-ID', 'ready']:
            self.assertIn(term, text)


if __name__ == '__main__':
    unittest.main()
