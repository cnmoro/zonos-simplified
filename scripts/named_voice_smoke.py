#!/usr/bin/env python3
"""Create a named voice in the actual browser, reload and generate without an upload."""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request
import uuid
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1919')
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    output = ROOT / 'outputs/validation'
    output.mkdir(parents=True, exist_ok=True)
    name = 'Browser test ' + uuid.uuid4().hex[:8]
    voice_id = None
    report = {'status': 'running', 'name': name, 'cases': []}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
            page = browser.new_page(viewport={'width': 1100, 'height': 1000})
            errors, requests = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append((request.url, request.post_data_json))
                    if request.method == 'POST' and request.url.endswith(('/v2/voices', '/v2/generate', '/v2/speakers')) else None)
            page.goto(args.url, wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            page.set_input_files('#reference', args.reference)
            page.fill('#voice-name', name)
            page.click('#save-voice')
            page.wait_for_function("document.getElementById('status').textContent === 'Voz salva e pronta para usar'", timeout=180000)
            voice_id = page.locator('#voice').input_value()
            assert voice_id.startswith('voice_')
            assert not page.locator('#reference').input_value()
            with urllib.request.urlopen(args.url + '/v2/voices/' + voice_id) as response:
                voice = json.load(response)
                assert voice['name'] == name and voice['ready'] and voice['persistent']
                report['preprocessing_ms'] = voice['preprocessing_ms']
            # A fresh page/session must discover the same persistent library entry.
            page.reload(wait_until='networkidle')
            page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
            page.select_option('#voice', voice_id)
            for language, text in [('pt_br', 'Uma voz salva e pronta.'), ('en_us', 'A saved voice, ready to speak.')]:
                page.select_option('#language', language)
                assert page.locator('#voice').input_value() == voice_id
                page.fill('#text', text)
                page.click('#generate')
                page.wait_for_function("document.getElementById('status').textContent === 'Concluído'", timeout=180000)
                page.wait_for_function("document.getElementById('audio').duration > 0")
                report['cases'].append({'language': language, 'metrics': page.locator('#metrics').inner_text()})
            assert len([r for r in requests if r[0].endswith('/v2/voices')]) == 1
            assert not [r for r in requests if r[0].endswith('/v2/speakers')]
            for url, body in requests:
                if url.endswith('/v2/generate'):
                    assert body['speaker_embedding_id'] == voice_id
                    assert 'speaker_audio_base64' not in body
            assert not errors, errors
            page.screenshot(path=str(output / 'named-voice-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output / 'named-voice-mobile.png'), full_page=True)
            browser.close()
        report.update(status='passed', page_errors=errors, audio_uploads=1, reuploads_during_generation=0)
    finally:
        if voice_id:
            request = urllib.request.Request(args.url + '/v2/voices/' + voice_id, method='DELETE')
            with urllib.request.urlopen(request) as response:
                assert response.status == 200
        (output / 'named-voice-browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
