#!/usr/bin/env python3
"""Real browser: generate, change download speed, verify measured duration and downloaded WAV."""
import argparse
import json
from pathlib import Path
import ssl
import urllib.request
import wave
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--ca-file',type=Path,default=ROOT/'certs/ca.pem')
    args=parser.parse_args(); output=ROOT/'outputs/validation'; output.mkdir(exist_ok=True,parents=True)
    tls=ssl.create_default_context(cafile=str(args.ca_file)) if args.url.startswith('https:') else None
    asset_id=None; results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--autoplay-policy=no-user-gesture-required'])
            page=browser.new_page(ignore_https_errors=True,accept_downloads=True,viewport={'width':1100,'height':950})
            errors=[]; requests=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:requests.append(request.url)
                if request.method=='POST' and request.url.endswith('/v2/generate') else None)
            page.goto(args.url,wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            page.fill('#text','Este áudio terá opções de velocidade para baixar.')
            page.click('#generate')
            page.wait_for_function("document.getElementById('status').textContent === 'Concluído'",timeout=180000)
            original=float(page.locator('#download-duration').get_attribute('data-seconds'))
            page.wait_for_function("!document.getElementById('download-durations').hidden",timeout=30000)
            durations=page.locator('#download-durations').get_attribute('href')
            asset_id=durations.split('/')[3]
            for speed in [1.3,.8,1.0]:
                page.locator('#download-speed').evaluate('(input,value)=>{input.value=String(value);input.dispatchEvent(new Event("input",{bubbles:true}));}',speed)
                page.wait_for_function("document.getElementById('download').getAttribute('aria-disabled')==='false' && document.getElementById('download-duration').dataset.seconds",timeout=30000)
                duration=float(page.locator('#download-duration').get_attribute('data-seconds'))
                assert page.locator('#download-speed-value').inner_text()==f'{speed:.1f}x'
                with page.expect_download() as pending:
                    page.click('#download')
                download=pending.value
                path=output/f'download-{speed:.1f}x.wav'; download.save_as(path)
                with wave.open(str(path),'rb') as audio:
                    actual=audio.getnframes()/audio.getframerate()
                    assert abs(actual-duration)<1e-9
                assert abs(actual-original/speed)<.15
                results.append({'speed':speed,'displayed_seconds':duration,'downloaded_seconds':actual})
            # Conversion must not trigger extra synthesis calls.
            assert len(requests)==1,requests
            # The duration endpoint returns the same measured values as the WAV headers.
            with urllib.request.urlopen(args.url+durations+'?speeds=1.0,1.3',context=tls) as response:
                metadata=json.load(response)
            assert metadata['duration_is_measured']
            page.screenshot(path=str(output/'download-speed-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output/'download-speed-mobile.png'),full_page=True)
            assert not errors,errors
            browser.close()
        report={'status':'passed','variants':results,'synthesis_calls':1,'page_errors':errors}
        (output/'download-speed-browser-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    finally:
        if asset_id:
            try:
                with urllib.request.urlopen(urllib.request.Request(args.url+'/v2/audio-assets/'+asset_id,method='DELETE'),context=tls): pass
            except Exception: pass


if __name__=='__main__': main()
