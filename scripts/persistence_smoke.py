#!/usr/bin/env python3
"""Test a multi-reference profile across an isolated native-server restart; never touches the production library."""
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
import wave

ROOT=Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    model=ROOT/'models/gguf'
    samples=[]
    with wave.open(str(model/'voices/English/Jett_en-energetic_M_1.wav'),'rb') as source:
        params=source.getparams()
        for i in range(2):
            data=io.BytesIO()
            with wave.open(data,'wb') as out:
                out.setparams(params); out.writeframes(source.readframes(source.getframerate()*3))
            samples.append({'name':f'take-{i+1}.wav','speaker_audio_base64':base64.b64encode(data.getvalue()).decode()})
    def call(path, body=None):
        request=urllib.request.Request(base+path, None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=180) as response: return json.load(response)
    with tempfile.TemporaryDirectory(prefix='zonos-persistence-') as directory:
        env=dict(os.environ,ZONOS3_VOICES_DIR=str(Path(directory)/'voices'))
        for name in ['ZONOS3_TLS_CERT','ZONOS3_TLS_KEY','ZONOS3_TLS_PORT','ZONOS3_HTTP_DISABLED','ZONOS3_ACCESS_TOKEN']: env.pop(name,None)
        command=[str(ROOT/'build/cuda/zonos3-server'),str(model/'zonos3-ptq.gguf'),'--gpu','--zac-gpu',
                 '--zac',str(model/'zac-keep2.gguf'),'--spk-encoder',str(model/'spk-encoder.gguf'),
                 '--batch','1','--zac-threads','1','--max','200','--host','127.0.0.1','--port',str(port),
                 '--studio-dir',str(ROOT/'frontend'),'--tts-default-voices-dir',str(model/'voices')]
        processes=[]
        def start(log_name):
            with (Path(directory)/log_name).open('wb') as log:
                process=subprocess.Popen(command,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
            processes.append(process)
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError((Path(directory)/log_name).read_text())
                try: call('/v2/health'); return process
                except OSError: time.sleep(.1)
            raise RuntimeError('Temporary server did not start')
        try:
            first=start('before.log')
            analysis=call('/v2/voice-analyses',{'samples':samples})
            voice=call('/v2/voices',{'name':'Restart test','analysis_id':analysis['id'],
                'selected_sample_ids':[s['id'] for s in analysis['samples']],'confirmed':True})
            before=call('/v2/speakers/'+voice['id']+'/embedding')
            first.terminate(); first.wait(timeout=15)
            second=start('after.log')
            restored=call('/v2/voices/'+voice['id'])
            assert restored['sample_count']==2 and restored['reference_analysis']==voice['reference_analysis']
            after=call('/v2/speakers/'+voice['id']+'/embedding')
            assert before==after
            body={'text':'Uma voz restaurada do disco.','language':'pt_br','speaker_embedding_id':voice['id'],
                  'speaker_mode':'embedding','decoder':'keep2_plain','stream':False,'format':'wav','max_tokens':200}
            request=urllib.request.Request(base+'/v2/generate',json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=180) as response:
                with wave.open(io.BytesIO(response.read())) as audio: assert audio.getnframes()>4410
            assert 'spk: loaded' not in (Path(directory)/'after.log').read_text()
            report={'status':'passed','sample_count':2,'embedding_unchanged':True,'metadata_preserved':True,
                    'generated_after_restart':True,'encoder_reloaded_after_restart':False,'production_library_untouched':True}
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=15)
    output=ROOT/'outputs/validation'; output.mkdir(exist_ok=True,parents=True)
    (output/'multi-reference-persistence-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
