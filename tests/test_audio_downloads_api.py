"""Real audio-asset conversion tests; no model synthesis or external Python DSP dependency needed."""
import array
import base64
import io
import json
import math
import os
import sys
import unittest
import urllib.error
import urllib.request
import wave


@unittest.skipUnless(os.environ.get('ZONOS_LIVE_URL'),'Set ZONOS_LIVE_URL for real conversion tests')
class AudioDownloadsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=os.environ['ZONOS_LIVE_URL'].rstrip('/')
        data=io.BytesIO()
        samples=array.array('h',(round(16000*math.sin(2*math.pi*440*i/44100)) for i in range(88200)))
        if sys.byteorder!='little': samples.byteswap()
        with wave.open(data,'wb') as wav:
            wav.setparams((1,2,44100,0,'NONE','not compressed')); wav.writeframes(samples.tobytes())
        cls.wav=data.getvalue()

    def setUp(self):
        self.created=[]
        status,self.asset=self.call('POST','/v2/audio-assets',{'audio_name':'tone.wav','audio_base64':base64.b64encode(self.wav).decode()})
        self.assertEqual(status,201,self.asset); self.created.append(self.asset['id'])

    def tearDown(self):
        for asset in self.created: self.call('DELETE','/v2/audio-assets/'+asset)

    def call(self,method,path,body=None):
        request=urllib.request.Request(self.base+path,None if body is None else json.dumps(body).encode(),
                                       method=method,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=180) as response: return response.status,json.load(response)
        except urllib.error.HTTPError as response: return response.code,json.load(response)

    def test_exact_duration_and_pitch_for_selected_speeds(self):
        aid=self.asset['id']; self.assertAlmostEqual(self.asset['duration_seconds'],2.0,places=10)
        _,info=self.call('GET',f'/v2/audio-assets/{aid}/durations?speeds=0.5,1.0,1.3,2.0')
        self.assertTrue(info['duration_is_measured']); self.assertTrue(info['preserves_pitch'])
        for variant in info['variants']:
            with urllib.request.urlopen(self.base+variant['download_url']) as response:
                data=response.read()
                self.assertIn('attachment',response.headers['Content-Disposition'])
                self.assertAlmostEqual(float(response.headers['X-Audio-Duration-Seconds']),variant['duration_seconds'],places=5)
                self.assertAlmostEqual(float(response.headers['X-Audio-Speed']),variant['speed'])
            with wave.open(io.BytesIO(data),'rb') as wav:
                self.assertEqual((wav.getnchannels(),wav.getsampwidth(),wav.getframerate()),(1,2,44100))
                duration=wav.getnframes()/wav.getframerate()
                self.assertAlmostEqual(duration,variant['duration_seconds'],places=10)
                self.assertAlmostEqual(duration,2/variant['speed'],delta=.12)
                samples=array.array('h',wav.readframes(wav.getnframes()))
            if variant['speed']==1:
                self.assertEqual(data,self.wav)  # 1.0x preserves canonical source bytes.
            if sys.byteorder!='little': samples.byteswap()
            middle=samples[4410:-4410]
            crossings=sum(a<=0<b for a,b in zip(middle,middle[1:]))
            frequency=crossings/(len(middle)/44100)
            self.assertAlmostEqual(frequency,440,delta=3) # A naive resample would shift pitch.

    def test_all_supported_speed_durations_and_cached_results(self):
        path=f"/v2/audio-assets/{self.asset['id']}/durations"
        status,first=self.call('GET',path); self.assertEqual(status,200)
        self.assertEqual([round(v['speed']*10) for v in first['variants']],list(range(5,21)))
        status,second=self.call('GET',path); self.assertEqual(status,200)
        self.assertEqual(first,second)
        self.assertGreater(first['variants'][0]['duration_seconds'],first['variants'][-1]['duration_seconds'])

    def test_invalid_speeds_audio_and_deleted_asset(self):
        base=f"/v2/audio-assets/{self.asset['id']}"
        for query in ['speed=0','speed=2.1','speed=1.25','speed=NaN','speed=abc','speed=1&speed=1.3','format=mp3']:
            request=urllib.request.Request(self.base+base+'/download?'+query)
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,422)
        for query in ['speeds=','speeds=1,1.0','speeds=1,,1.3']:
            self.assertEqual(self.call('GET',base+'/durations?'+query)[0],422)
        self.assertEqual(self.call('POST','/v2/audio-assets',{'audio_base64':'bm90IGF1ZGlv'})[0],400)
        self.assertEqual(self.call('DELETE',base)[0],200)
        self.created=[]
        self.assertEqual(self.call('GET',base)[0],404)


if __name__=='__main__': unittest.main()
