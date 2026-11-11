#!/usr/bin/env python3
"""Record repeated microphone samples using real browser MediaRecorder and a deterministic test audio device."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import ssl
import tempfile
import urllib.request
import uuid
from playwright.sync_api import sync_playwright
from multi_reference_smoke import clip_bytes

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:1919')
    parser.add_argument('--reference',type=Path,default=ROOT/'models/gguf/voices/English/Jett_en-energetic_M_1.wav')
    parser.add_argument('--ca-file',type=Path,default=ROOT/'certs/ca.pem')
    args=parser.parse_args(); output=ROOT/'outputs/validation'; output.mkdir(parents=True,exist_ok=True)
    report={'status':'running','capture_device':'Chromium fake microphone fed by real speech','url':args.url}
    voice_id=None
    tls_context=ssl.create_default_context(cafile=str(args.ca_file)) if args.url.startswith('https:') else None
    try:
        with tempfile.TemporaryDirectory(prefix='zonos-microphone-') as temporary:
            capture=Path(temporary)/'capture.wav'
            subprocess.run(['ffmpeg','-v','error','-y','-i',str(args.reference),'-ar','48000','-ac','1','-c:a','pcm_s16le',str(capture)],check=True)
            with sync_playwright() as pw:
                flags=['--autoplay-policy=no-user-gesture-required','--use-fake-ui-for-media-stream',
                       '--use-fake-device-for-media-stream',f'--use-file-for-fake-audio-capture={capture}']
                browser=pw.chromium.launch(headless=True,args=flags)
                context=browser.new_context(ignore_https_errors=True,permissions=['microphone'],viewport={'width':1100,'height':950})
                page=context.new_page(); errors=[]; analyses=[]; confirmations=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('response',lambda response:analyses.append(response.json())
                        if response.request.method=='POST' and response.url.endswith('/v2/voice-analyses') and response.ok else None)
                page.on('request',lambda request:confirmations.append(request.post_data_json)
                        if request.method=='POST' and request.url.endswith('/v2/voices') else None)
                page.goto(args.url,wait_until='networkidle')
                page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
                assert page.evaluate('isSecureContext && !!navigator.mediaDevices?.getUserMedia')
                page.wait_for_function("document.getElementById('reading-prompt').options.length === 20")
                page.select_option('#reading-prompt','6')
                initial_reading=page.locator('#reading-text').inner_text()
                for i in range(2):
                    page.click('#record-start')
                    page.wait_for_function("!document.getElementById('record-stop').disabled")
                    assert page.locator('#reading-next').is_disabled()
                    assert page.locator('#reading-prompt').is_disabled()
                    assert page.locator('#language').is_disabled()
                    reading=page.locator('#reading-text').inner_text()
                    page.wait_for_timeout(2300)
                    assert page.locator('#reading-text').inner_text()==reading
                    page.click('#record-stop')
                    page.wait_for_function("document.getElementById('record-stop').disabled && !document.getElementById('record-start').disabled")
                    assert page.locator('#reference-file-rows audio').count()==i+1
                    if i==0:
                        page.click('#reading-next')
                        assert page.locator('#reading-text').inner_text()!=initial_reading
                page.select_option('#language','en_us')
                assert page.locator('#reading-prompt option').count()==20
                assert page.locator('#reading-text').get_attribute('lang')=='en-US'
                page.select_option('#language','pt_br')
                # Uploads and recordings share the same review list.
                page.set_input_files('#reference',{'name':'uploaded.wav','mimeType':'audio/wav','buffer':clip_bytes(args.reference)})
                assert page.locator('#reference-file-rows audio').count()==3
                page.set_input_files('#reference',{'name':'discard.wav','mimeType':'audio/wav','buffer':clip_bytes(args.reference)})
                assert page.locator('#reference-file-rows audio').count()==4
                page.get_by_role('button',name='Remover discard.wav',exact=True).click()
                assert page.locator('#reference-file-rows audio').count()==3
                page.click('#analyze-references')
                page.wait_for_function("!document.getElementById('reference-analysis').hidden && !document.getElementById('analyze-references').disabled",timeout=180000)
                assert analyses and analyses[0]['sample_count']==3
                assert any(s['name'].startswith('microfone-') for s in analyses[0]['samples'])
                page.locator('#reference-rows input[type=checkbox]').nth(1).uncheck()
                page.fill('#voice-name','Microphone test '+uuid.uuid4().hex[:8])
                page.click('#save-voice')
                page.wait_for_function("document.getElementById('status').textContent === 'Voz salva e pronta para usar'",timeout=180000)
                voice_id=page.locator('#voice').input_value()
                assert confirmations[0]['selected_sample_ids']==['sample_1','sample_3']
                with urllib.request.urlopen(args.url+'/v2/voices/'+voice_id,context=tls_context) as response: voice=json.load(response)
                assert voice['sample_count']==2
                assert voice['reference_analysis']['samples'][0]['name'].startswith('microfone-')
                page.fill('#text','Uma voz com amostras do microfone.'); page.click('#generate')
                page.wait_for_function("document.getElementById('status').textContent === 'Concluído'",timeout=180000)
                assert page.locator('#result').is_visible()
                page.screenshot(path=str(output/'microphone-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/'microphone-mobile.png'),full_page=True)
                assert not errors,errors
                report.update(status='passed',microphone_samples=2,uploaded_samples=1,selected_samples=2,
                              generated=True,reading_prompts_per_language=20,reading_locked_during_capture=True,page_errors=errors)
                browser.close()
    finally:
        if voice_id:
            with urllib.request.urlopen(urllib.request.Request(args.url+'/v2/voices/'+voice_id,method='DELETE'),context=tls_context): pass
        (output/'microphone-browser-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
