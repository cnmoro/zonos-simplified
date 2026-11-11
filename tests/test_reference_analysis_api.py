"""Real GPU analysis + confirmation tests; opt in with ZONOS_LIVE_URL."""
import base64
import io
import json
import math
import os
from pathlib import Path
import unittest
import urllib.error
import urllib.request
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('ZONOS_LIVE_URL'), 'Set ZONOS_LIVE_URL for real analysis tests')
class ReferenceAnalysisAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.environ['ZONOS_LIVE_URL'].rstrip('/')
        cls.samples = []
        for name in ['English/Jett_en-energetic_M_1.wav', 'English/Jett_en-energetic_M_1.wav', 'Portuguese/Thiago_pt_M_1.wav']:
            with wave.open(str(ROOT/'models/gguf/voices'/name), 'rb') as source:
                params = source.getparams()
                audio = source.readframes(3 * source.getframerate())
            stream = io.BytesIO()
            with wave.open(stream, 'wb') as target:
                target.setparams(params)
                target.writeframes(audio)
            cls.samples.append({'name': f'take-{len(cls.samples)+1}.wav',
                                'speaker_audio_base64': base64.b64encode(stream.getvalue()).decode()})

    def setUp(self):
        self.voices, self.analyses = [], []
        self.prefix = 'Analysis test ' + uuid.uuid4().hex[:8]

    def tearDown(self):
        for voice in self.voices: self.call('DELETE','/v2/voices/'+voice)
        for analysis in self.analyses: self.call('DELETE','/v2/voice-analyses/'+analysis)

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base+path, None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type':'application/json'}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=180) as response: return response.status,json.load(response)
        except urllib.error.HTTPError as response: return response.code,json.load(response)

    def analyze(self, samples=None):
        status, analysis = self.call('POST','/v2/voice-analyses',{'samples':samples or self.samples})
        self.assertEqual(status,201,analysis)
        self.analyses.append(analysis['id'])
        return analysis

    def confirm(self, analysis, ids, suffix):
        status, voice = self.call('POST','/v2/voices',{'name':self.prefix+suffix,'language':'pt_br',
            'analysis_id':analysis['id'],'selected_sample_ids':ids,'confirmed':True})
        self.assertEqual(status,201,voice)
        self.voices.append(voice['id'])
        return voice

    def test_cross_similarity_selection_and_exact_saved_mean(self):
        analysis = self.analyze()
        self.assertEqual(analysis['sample_count'],3)
        self.assertFalse(analysis['persistent'])
        matrix=analysis['pairwise_similarity']
        for i in range(3):
            self.assertAlmostEqual(matrix[i][i],1,places=10)
            for j in range(3):
                self.assertTrue(-1 <= matrix[i][j] <= 1)
                self.assertAlmostEqual(matrix[i][j],matrix[j][i],places=10)
        self.assertAlmostEqual(matrix[0][1],1,places=9)  # Identical bytes give identical embeddings.
        self.assertLess(matrix[0][2],.99)  # A genuinely different speaker.
        ids=[s['id'] for s in analysis['samples']]
        # Analysis alone has not created a profile.
        _, listed=self.call('GET','/v2/voices')
        self.assertFalse(any(v['name'].startswith(self.prefix) for v in listed['voices']))
        status, selection=self.call('POST',f"/v2/voice-analyses/{analysis['id']}/selection",{'selected_sample_ids':[ids[0]]})
        self.assertEqual(status,200)
        for i in range(3): self.assertAlmostEqual(selection['samples'][i]['similarity_to_mean'],matrix[i][0],places=9)
        vectors=[]
        for i in [0,2]:
            single=self.confirm(analysis,[ids[i]],str(i))
            _, vector=self.call('GET',f"/v2/speakers/{single['id']}/embedding")
            vectors.append(vector['embedding'])
        combined=self.confirm(analysis,[ids[2],ids[0]],' combined')
        self.assertEqual(combined['sample_count'],2)
        self.assertEqual(combined['reference_analysis']['selected_sample_ids'],[ids[0],ids[2]])
        self.assertEqual([s['name'] for s in combined['reference_analysis']['samples']],['take-1.wav','take-3.wav'])
        _, actual=self.call('GET',f"/v2/speakers/{combined['id']}/embedding")
        for i,x in enumerate(actual['embedding']): self.assertAlmostEqual(x,(vectors[0][i]+vectors[1][i])/2,delta=2e-6)
        # The independent UI Gram-matrix formula must match native mean scores.
        _, subset=self.call('POST',f"/v2/voice-analyses/{analysis['id']}/selection",{'selected_sample_ids':[ids[0],ids[2]]})
        norms=[s['embedding_norm'] for s in analysis['samples']]
        divisor=math.sqrt(sum(matrix[i][j]*norms[i]*norms[j] for i in [0,2] for j in [0,2]))
        for i in range(3):
            expected=sum(matrix[i][j]*norms[j] for j in [0,2])/divisor
            self.assertAlmostEqual(subset['samples'][i]['similarity_to_mean'],expected,places=6)
        self.call('DELETE','/v2/voice-analyses/'+analysis['id'])
        self.analyses.remove(analysis['id'])
        body={'text':'Uma voz com referências escolhidas.','language':'pt_br','speaker_mode':'embedding',
              'speaker_embedding_id':combined['id'],'decoder':'keep2_plain','stream':False,'format':'wav','max_tokens':200}
        request=urllib.request.Request(self.base+'/v2/generate',json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=180) as response:
            with wave.open(io.BytesIO(response.read())) as wav: self.assertGreater(wav.getnframes(),4410)

    def test_confirmation_and_selection_validation(self):
        analysis=self.analyze(self.samples[:1]); sid=analysis['samples'][0]['id']
        base={'name':self.prefix,'analysis_id':analysis['id'],'selected_sample_ids':[sid]}
        for extra in [{},{'confirmed':False},{'confirmed':'true'}, {'confirmed':True,'selected_sample_ids':[]},
                      {'confirmed':True,'selected_sample_ids':[sid,sid]}, {'confirmed':True,'selected_sample_ids':['wrong']}]:
            self.assertEqual(self.call('POST','/v2/voices',{**base,**extra})[0],422)
        self.assertEqual(self.call('POST',f"/v2/voice-analyses/{analysis['id']}/selection",{'selected_sample_ids':[]})[0],422)
        self.assertEqual(self.call('GET','/v2/voice-analyses/analysis_'+'0'*24)[0],404)
        self.assertEqual(self.call('POST','/v2/voice-analyses',{'samples':[]})[0],422)
        self.assertEqual(self.call('POST','/v2/voice-analyses',{'samples':self.samples[:1]*21})[0],422)
        self.assertEqual(self.call('POST','/v2/voice-analyses',{'samples':[{'name':'bad.wav','speaker_audio_base64':'bm90IGF1ZGlv'}]})[0],400)


if __name__=='__main__': unittest.main()
