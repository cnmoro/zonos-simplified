#!/usr/bin/env python3
"""Real browser: ten references, pairwise scores, checkbox selection and reusable profile."""
import argparse
import io
import json
from pathlib import Path
import urllib.request
import uuid
import wave
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def clip_bytes(reference, seconds=2):
    with wave.open(str(reference),'rb') as source:
        params=source.getparams(); frames=source.readframes(int(seconds*source.getframerate()))
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as target:
        target.setparams(params); target.writeframes(frames)
    return buffer.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:1919')
    parser.add_argument('--reference',type=Path,default=ROOT/'models/gguf/voices/English/Jett_en-energetic_M_1.wav')
    args=parser.parse_args(); output=ROOT/'outputs/validation'; output.mkdir(parents=True,exist_ok=True)
    name='Multi browser '+uuid.uuid4().hex[:8]; voice_id=None; analysis_id=None
    report={'status':'running','samples':10}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
            page=browser.new_page(viewport={'width':1200,'height':950})
            errors=[]; saved_payloads=[]; analysis_calls=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:saved_payloads.append(request.post_data_json)
                    if request.method=='POST' and request.url.endswith('/v2/voices') else None)
            page.on('response',lambda response:analysis_calls.append(response.url)
                    if response.request.method=='POST' and response.url.endswith('/v2/voice-analyses') else None)
            page.goto(args.url,wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            data=clip_bytes(args.reference)
            alternate=clip_bytes(ROOT/'models/gguf/voices/Portuguese/Thiago_pt_M_1.wav')
            files=[{'name':f'take-{i+1}.wav','mimeType':'audio/wav','buffer':data if i<5 else alternate} for i in range(10)]
            page.set_input_files('#reference',files)
            assert page.locator('#generate').is_disabled()
            assert page.locator('#save-voice').is_disabled()
            page.click('#analyze-references')
            page.wait_for_function("!document.getElementById('reference-analysis').hidden && !document.getElementById('analyze-references').disabled",timeout=240000)
            assert page.locator('#reference-rows input[type=checkbox]').count()==10
            assert page.locator('#similarity-matrix tbody td').count()==100
            original_score=page.locator('#selected-mean-0').inner_text()
            # Two known speakers are deliberately mixed here to make a changed selection observable.
            # No profile exists before the explicit confirmation.
            assert not saved_payloads
            # Deselect all: committing an empty selection must be disabled.
            for box in page.locator('#reference-rows input[type=checkbox]').all(): box.uncheck()
            assert page.locator('#save-voice').is_disabled()
            for index in [0,2,4,6,8]: page.locator('#reference-rows input[type=checkbox]').nth(index).check()
            assert '5 de 10' in page.locator('#selection-count').inner_text()
            assert page.locator('#selected-mean-0').inner_text()!=original_score
            page.fill('#voice-name',name)
            page.screenshot(path=str(output/'multi-reference-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/'multi-reference-mobile.png'),full_page=True)
            page.click('#save-voice')
            page.wait_for_function("document.getElementById('status').textContent === 'Voz salva e pronta para usar'",timeout=180000)
            voice_id=page.locator('#voice').input_value()
            assert len(saved_payloads)==1 and len(analysis_calls)==1
            payload=saved_payloads[0]; analysis_id=payload['analysis_id']
            assert payload['confirmed'] is True
            assert payload['selected_sample_ids']==['sample_1','sample_3','sample_5','sample_7','sample_9']
            assert 'speaker_audio_base64' not in payload
            with urllib.request.urlopen(args.url+'/v2/voices/'+voice_id) as response: saved=json.load(response)
            assert saved['sample_count']==5 and saved['ready']
            assert len(saved['reference_analysis']['samples'])==5
            assert [s['name'] for s in saved['reference_analysis']['samples']]==[f'take-{i}.wav' for i in [1,3,5,7,9]]
            for language,text in [('pt_br','Um perfil com referências escolhidas.'),('en_us','A profile with selected references.')]:
                page.select_option('#language',language); page.fill('#text',text); page.click('#generate')
                page.wait_for_function("document.getElementById('status').textContent === 'Concluído'",timeout=180000)
                assert page.locator('#result').is_visible()
            assert not errors,errors
            browser.close()
        report.update(status='passed',selected_count=5,analysis_uploads=1,profile_uploads=0,page_errors=errors)
    finally:
        if voice_id:
            with urllib.request.urlopen(urllib.request.Request(args.url+'/v2/voices/'+voice_id,method='DELETE')): pass
        (output/'multi-reference-browser-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()
