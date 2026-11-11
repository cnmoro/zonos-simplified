import array
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import infer


class Chunks(io.BytesIO):
    # Deliberately split floats across network chunks.
    def read1(self, size=-1):
        return self.read(min(7, size))


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'voice.wav'

    def test_languages_and_validation(self):
        for language in ['es', 'xx']:
            with self.assertRaises(ValueError):
                infer.synthesize('', 'text', language, self.out)
        with self.assertRaises(ValueError):
            infer.synthesize('', ' ', 'pt', self.out)
        with self.assertRaises(ValueError):
            infer.synthesize('', 'text', 'en', self.out, reference='a', voice='b')

    def test_streaming_reference_and_cached_voice_payload(self):
        reference = Path(self.temp.name) / 'speaker.ogg'
        reference.write_bytes(b'OggS fixture')
        calls = []
        values = array.array('f', [0.2, -0.5, 2, float('nan')] * 100)
        if sys.byteorder != 'little': values.byteswap()
        def transport(req, timeout):
            payload = json.loads(req.data)
            calls.append((req.full_url, payload, dict(req.header_items())))
            if req.full_url.endswith('/speakers'):
                self.assertEqual(base64.b64decode(payload['speaker_audio_base64']), reference.read_bytes())
                self.assertEqual(payload['speaker_audio_name'], 'speaker.ogg')
                return io.BytesIO(b'{"id":"cached-test"}')
            self.assertEqual(payload['language'], 'pt_br')
            self.assertEqual(payload['speaker_embedding_id'], 'cached-test')
            self.assertEqual(payload['speaker_mode'], 'embedding')
            self.assertEqual(payload['speaker_cfg_scale'], 1)
            self.assertTrue(payload['stream'])
            return Chunks(values.tobytes())
        with patch('urllib.request.urlopen', side_effect=transport):
            result = infer.synthesize('http://local', 'Olá.', 'pt', self.out, reference=reference, session='test')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2]['X-tts-session-id'], 'test')
        with wave.open(str(self.out)) as wav:
            self.assertEqual(wav.getnframes(), 400)
            self.assertEqual(wav.getframerate(), 44100)
            samples = array.array('h', wav.readframes(4))
            if sys.byteorder != 'little': samples.byteswap()
            self.assertEqual(list(samples), [6553, -16384, 32767, 0])
        self.assertGreater(result['first_audio_seconds'], 0)

    def test_truncated_stream_does_not_publish_file(self):
        with patch('urllib.request.urlopen', return_value=Chunks(b'abc')):
            with self.assertRaisesRegex(RuntimeError, 'Truncated'):
                infer.synthesize('http://local', 'Hello', 'en', self.out)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.out.with_suffix('.wav.part').exists())

    def test_buffered_wav(self):
        data = io.BytesIO()
        with wave.open(data, 'wb') as wav:
            wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x00\x20' * 100)
        with patch('urllib.request.urlopen', return_value=Chunks(data.getvalue())):
            result = infer.synthesize('http://local', 'Hello', 'en', self.out, stream=False)
        self.assertFalse(result['stream'])
        self.assertEqual(self.out.read_bytes(), data.getvalue())

    def test_http_error_is_actionable(self):
        error = urllib.error.HTTPError('http://local', 400, 'Bad request', {}, io.BytesIO(b'unknown voice'))
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, '400: unknown voice'):
                infer.synthesize('http://local', 'Hello', 'en', self.out)

    def test_large_reference_rejected_before_read(self):
        reference = Path(self.temp.name) / 'large.wav'
        with reference.open('wb') as file:
            file.truncate(infer.MAX_UPLOAD + 1)
        with self.assertRaises(ValueError):
            infer.cache_voice('', reference, 'test')


if __name__ == '__main__':
    unittest.main()
