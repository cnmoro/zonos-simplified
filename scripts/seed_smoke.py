#!/usr/bin/env python3
"""Verify seed selection, reuse, and deterministic WAV output in a real browser."""
import argparse
import hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / 'outputs/validation'
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
        page = browser.new_page(ignore_https_errors=True, accept_downloads=True)
        calls, errors = [], []
        page.on('request', lambda r: calls.append(r.post_data_json)
                if r.method == 'POST' and r.url.endswith('/v2/generate') else None)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.url, wait_until='networkidle')
        page.wait_for_function("document.getElementById('health').textContent==='Modelo conectado'")
        page.select_option('#language', 'en_us')
        page.fill('#text', 'A quiet morning brings a fresh opportunity to learn.')
        hashes = []
        for index in range(2):
            page.click('#generate')
            page.wait_for_function("document.getElementById('status').textContent==='Concluído'", timeout=180000)
            with page.expect_download() as pending:
                page.click('#download')
            target = output / f'seed-reuse-{index}.wav'
            pending.value.save_as(str(target))
            hashes.append(hashlib.sha256(target.read_bytes()).hexdigest())
            page.click('#reuse-seed')
            assert page.locator('#seed').input_value().isdigit()
        assert 'seed' not in calls[0]
        assert calls[1]['seed'] == int(page.locator('#seed').input_value())
        assert hashes[0] == hashes[1], hashes
        assert not errors, errors
        print('PASS: random seed captured, reused, and identical WAV reproduced')
        browser.close()


if __name__ == '__main__':
    main()
