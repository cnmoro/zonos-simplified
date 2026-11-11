#!/usr/bin/env python3
"""Regression: record -> enter name -> generate -> F5; profile must exist on disk and remain selected."""
import argparse
import json
from pathlib import Path
import ssl
import subprocess
import tempfile
import urllib.request
import uuid
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--ca-file',type=Path,default=ROOT/'certs/ca.pem')
    args=parser.parse_args(); voice_id=None
    context=ssl.create_default_context(cafile=str(args.ca_file)) if args.url.startswith('https:') else None
    name='Reload regression '+uuid.uuid4().hex[:8]
    output=ROOT/'outputs/validation'; output.mkdir(exist_ok=True,parents=True)
    report={'status':'running'}
    try:
        with tempfile.TemporaryDirectory(prefix='zonos-reload-') as temporary, sync_playwright() as pw:
            capture=Path(temporary)/'capture.wav'
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(ROOT/'models/gguf/voices/English/Jett_en-energetic_M_1.wav'),
                            '-ar','48000','-ac','1','-c:a','pcm_s16le',str(capture)],check=True)
            browser=pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required',
                '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',f'--use-file-for-fake-audio-capture={capture}'])
            page=browser.new_page(ignore_https_errors=True,permissions=['microphone'])
            errors=[]; posts=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:posts.append(request.url.rsplit('/',1)[-1])
                    if request.method=='POST' and request.url.endswith(('/v2/voices','/v2/generate','/v2/speakers')) else None)
            page.goto(args.url,wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            page.fill('#voice-name',name)
            assert page.locator('#generate').is_disabled()
            page.click('#record-start'); page.wait_for_function("!document.getElementById('record-stop').disabled")
            page.wait_for_timeout(2300); page.click('#record-stop')
            page.wait_for_function("document.getElementById('record-stop').disabled && !document.getElementById('record-start').disabled")
            page.fill('#voice-name',name); page.fill('#text','Esta voz permanece após recarregar.')
            assert page.locator('#generate').inner_text()=='Salvar voz e gerar'
            page.click('#generate')
            page.wait_for_function("document.getElementById('status').textContent === 'Concluído'",timeout=180000)
            voice_id=page.locator('#voice').input_value()
            assert voice_id.startswith('voice_'),voice_id
            assert posts==['voices','generate'],posts
            assert (ROOT/'voices'/f'{voice_id}.json').is_file()
            with urllib.request.urlopen(args.url+'/v2/voices/'+voice_id,context=context) as response:
                voice=json.load(response); assert voice['name']==name and voice['persistent'] and voice['ready']
            page.reload(wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            assert page.locator('#voice').input_value()==voice_id
            assert 'Perfil salvo no servidor' in page.locator('#voice-state').inner_text()
            page.fill('#text','A mesma voz, depois de recarregar.'); page.click('#generate')
            page.wait_for_function("document.getElementById('status').textContent === 'Concluído'",timeout=180000)
            assert posts==['voices','generate','generate'],posts
            # Discovery is from the server, even with all browser storage removed.
            page.evaluate('localStorage.clear(); sessionStorage.clear()')
            page.reload(wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            assert page.locator(f'#voice option[value="{voice_id}"]').count()==1
            # A failed disk-save request must never fall back to ephemeral generation.
            source=(ROOT/'models/gguf/voices/English/Jett_en-energetic_M_1.wav').read_bytes()
            page.set_input_files('#reference',{'name':'failed-save.wav','mimeType':'audio/wav','buffer':source})
            page.fill('#voice-name','Should not generate')
            def fail_save(route):
                if route.request.method=='POST': route.fulfill(status=500,content_type='application/json',body='{"detail":"simulated storage failure"}')
                else: route.continue_()
            page.route('**/v2/voices',fail_save)
            before=posts.count('generate'); page.click('#generate')
            page.wait_for_function("document.getElementById('status').textContent.includes('simulated storage failure')",timeout=30000)
            assert posts.count('generate')==before
            assert page.locator('#reference-file-rows audio').count()==1
            assert not errors,errors
            page.screenshot(path=str(output/'named-generation-reload.png'),full_page=True)
            report={'status':'passed','named_voice_saved_before_generation':True,'restored_selected_voice_after_F5':True,
                    'available_without_browser_storage':True,'save_failure_blocks_generation':True,'page_errors':errors}
            browser.close()
    finally:
        if voice_id:
            with urllib.request.urlopen(urllib.request.Request(args.url+'/v2/voices/'+voice_id,method='DELETE'),context=context): pass
        (output/'named-generation-reload-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
