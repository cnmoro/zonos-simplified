#!/usr/bin/env python3
"""Real browser flow against the running native server, including HTTP Tailscale IP."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1919')
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    results = []
    output = ROOT / 'outputs' / 'validation'
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
        page = browser.new_page(viewport={'width': 1100, 'height': 850})
        errors = []
        uploads = []
        page.on('request', lambda request: uploads.append(request.url) if request.method == 'POST' and request.url.endswith('/v2/speakers') else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until='networkidle')
        page.wait_for_function("document.getElementById('health').textContent === 'Modelo conectado'")
        reference_uploaded = False
        for language, text, clone in [('pt_br', 'Olá! Tudo bem?', False),
                                       ('en_us', 'Hello! How are you?', False),
                                       ('pt_br', 'Esta é a voz de referência.', True),
                                       ('en_us', 'Reusing the same voice.', True)]:
            page.select_option('#language', language)
            page.fill('#text', text)
            if clone and not reference_uploaded:
                page.set_input_files('#reference', args.reference)
                reference_uploaded = True
            page.click('#generate')
            page.wait_for_function("document.getElementById('status').textContent === 'Concluído'", timeout=240000)
            assert page.locator('#result').is_visible()
            assert page.locator('#download').get_attribute('href').startswith('blob:')
            page.wait_for_function("document.getElementById('audio').duration > 0")
            results.append({'language': language, 'clone': clone,
                            'metrics': page.locator('#metrics').inner_text(),
                            'duration': page.locator('#audio').evaluate('(audio) => audio.duration')})
        assert len(uploads) == 1, uploads
        assert not errors, errors
        page.screenshot(path=str(output / 'frontend-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(output / 'frontend-mobile.png'), full_page=True)
        browser.close()
    report = {'status': 'passed', 'url': args.url, 'cases': results, 'page_errors': errors, 'reference_uploads': len(uploads)}
    (output / 'browser-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
