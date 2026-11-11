#!/usr/bin/env python3
"""English/Portuguese inference client. No Python inference dependencies."""
import argparse
import array
import base64
import json
import math
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

LANGUAGES = {'en': 'en_us', 'pt': 'pt_br', 'en_us': 'en_us', 'pt_br': 'pt_br'}
MAX_UPLOAD = 20 * 1024 * 1024


def request(base_url, path, payload=None, session='local', timeout=180):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base_url.rstrip('/') + path, body, headers={
        'Content-Type': 'application/json', 'X-TTS-Session-ID': session})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'API {exc.code}: {exc.read(8192).decode(errors="replace")}') from exc


def cache_voice(base_url, reference, session):
    reference = Path(reference)
    if reference.stat().st_size > MAX_UPLOAD:
        raise ValueError('Reference exceeds 20 MiB; use a short 5–15 second clip')
    with request(base_url, '/v2/speakers', {
        'label': reference.stem, 'speaker_audio_name': reference.name,
        'speaker_audio_base64': base64.b64encode(reference.read_bytes()).decode(),
    }, session) as response:
        return json.load(response)['id']


def synthesize(base_url, text, language, output, *, voice=None, reference=None,
               session=None, max_tokens=1000, seed=42, stream=True):
    if language not in LANGUAGES:
        raise ValueError('Supported languages: en, pt, en_us, pt_br')
    if not text.strip() or len(text) > 3000:
        raise ValueError('Text must contain 1–3000 characters')
    if reference and voice:
        raise ValueError('Choose reference or voice, not both')
    session = session or uuid.uuid4().hex
    if reference:
        voice = cache_voice(base_url, reference, session)
    payload = {
        'text': text, 'language': LANGUAGES[language], 'speaker_mode': 'embedding',
        'speaker_cfg_scale': 1.0, 'decoder': 'keep2_plain', 'seed': seed,
        'max_tokens': max_tokens, 'stream': stream, 'format': 'pcm' if stream else 'wav',
    }
    if voice:
        payload['speaker_embedding_id'] = voice
    start = time.perf_counter()
    first = None
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.part')
    try:
        with request(base_url, '/v2/generate', payload, session) as response:
            if stream:
                pending = b''
                with wave.open(str(temporary), 'wb') as wav:
                    wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                    while chunk := response.read1(16384):
                        if first is None:
                            first = time.perf_counter() - start
                        chunk = pending + chunk
                        boundary = len(chunk) // 4 * 4
                        values = array.array('f')
                        values.frombytes(chunk[:boundary])
                        if sys.byteorder != 'little':
                            values.byteswap()
                        pcm = array.array('h', (round(max(-1, min(1, x if math.isfinite(x) else 0)) * 32767) for x in values))
                        if sys.byteorder != 'little':
                            pcm.byteswap()
                        wav.writeframesraw(pcm.tobytes())
                        pending = chunk[boundary:]
                    if pending:
                        raise RuntimeError('Truncated float32 PCM stream')
            else:
                with temporary.open('wb') as file:
                    while chunk := response.read1(16384):
                        if first is None:
                            first = time.perf_counter() - start
                        file.write(chunk)
        with wave.open(str(temporary), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
            if duration <= 0:
                raise RuntimeError('Empty audio response')
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    elapsed = time.perf_counter() - start
    return {'output': str(output), 'audio_seconds': duration, 'generation_seconds': elapsed,
            'first_audio_seconds': first, 'rtf': elapsed / duration, 'voice_id': voice,
            'session': session, 'stream': stream}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', required=True)
    parser.add_argument('--language', choices=LANGUAGES, default='pt')
    parser.add_argument('--reference', type=Path, help='WAV, MP3, OGG, FLAC, M4A etc. (ffmpeg)')
    parser.add_argument('--voice', help='Previously cached or default speaker id')
    parser.add_argument('--session', help='Reuse with --voice for a cached uploaded voice')
    parser.add_argument('--output', type=Path, default=Path('outputs/speech.wav'))
    parser.add_argument('--url', default='http://127.0.0.1:1919')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--max-tokens', type=int, default=1000)
    parser.add_argument('--buffered', action='store_true')
    args = parser.parse_args()
    result = synthesize(args.url, args.text, args.language, args.output, voice=args.voice,
                        reference=args.reference, session=args.session, seed=args.seed,
                        max_tokens=args.max_tokens, stream=not args.buffered)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        sys.exit(str(exc))
