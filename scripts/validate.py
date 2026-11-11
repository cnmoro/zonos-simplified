#!/usr/bin/env python3
"""Real model smoke test: EN/PT, reference WAV/MP3/OGG, cached voice, streaming."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import threading
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from infer import cache_voice, request, synthesize


def inspect_audio(path):
    import array
    with wave.open(str(path), 'rb') as wav:
        assert wav.getframerate() == 44100 and wav.getnchannels() == 1
        assert wav.getsampwidth() == 2 and wav.getnframes() > 2205
        samples = array.array('h', wav.readframes(wav.getnframes()))
    assert max(abs(x) for x in samples) > 100, f'Silent audio: {path}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:1919')
    parser.add_argument('--server-pid', type=int, help='Sample server RSS from /proc/<pid>/status')
    parser.add_argument('--reference', type=Path, help='Optional real human speech; otherwise use generated EN audio')
    args = parser.parse_args()
    output = ROOT / 'outputs' / 'validation'
    output.mkdir(parents=True, exist_ok=True)
    report = {'status': 'running', 'cases': [], 'note': 'Signal/transport checks; intelligibility and identity require listening.'}
    report_path = output / 'report.json'
    stop = threading.Event()
    memory = []
    def sample_memory():
        while not stop.is_set():
            try:
                value = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used',
                    '--format=csv,noheader,nounits'], text=True, timeout=5)
                sample = {'gpu_used_mib': [int(x) for x in value.split()]}
                if args.server_pid:
                    status = Path(f'/proc/{args.server_pid}/status').read_text()
                    sample['server_rss_mib'] = next(int(line.split()[1]) / 1024 for line in status.splitlines() if line.startswith('VmRSS:'))
                memory.append(sample)
            except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
                pass
            stop.wait(0.25)
    monitor = None
    try:
        # Fail rather than claiming GPU validation on a CPU fallback.
        subprocess.run(['nvidia-smi'], check=True, capture_output=True)
        monitor = threading.Thread(target=sample_memory, daemon=True)
        monitor.start()
        with request(args.url, '/v2/health') as response:
            assert json.load(response)['status'] == 'ok'
        with request(args.url, '/v2/capabilities') as response:
            report['capabilities'] = json.load(response)
        with request(args.url, '/') as response:
            assert b'Seu texto' in response.read()
        with request(args.url, '/v2/speakers') as response:
            speakers = json.load(response)['speakers']
        defaults = {language: next(s['id'] for s in speakers if (s.get('original_name') or '').startswith(name) and s['source_type'] == 'audio')
                    for language, name in [('pt', 'Thiago_'), ('en', 'Jett_')]}
        report['default_voices'] = defaults
        for language, text in [('en', 'Hello! This is a short English voice generation test.'),
                               ('pt', 'Olá! Este é um teste curto de geração de voz em português.')]:
            # Two runs distinguish cold/warm execution; timings exclude reference upload.
            for iteration in range(2):
                result = synthesize(args.url, text, language, output / f'{language}-{iteration}.wav', voice=defaults[language])
                inspect_audio(result['output'])
                result.update(language=language, iteration=iteration, kind='default')
                report['cases'].append(result)
        buffered = synthesize(args.url, 'Buffered speech test.', 'en', output / 'buffered.wav', voice=defaults['en'], stream=False)
        inspect_audio(buffered['output'])
        buffered['kind'] = 'buffered'
        report['cases'].append(buffered)
        reference = args.reference or output / 'en-1.wav'
        for extension in ('wav', 'mp3', 'ogg'):
            converted = output / f'reference.{extension}'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(reference), '-t', '15',
                            '-ac', '1', str(converted)], check=True)
            session = f'validation-{extension}-{time.time_ns()}'
            voice = cache_voice(args.url, converted, session)
            for language, text in [('en', 'The same voice can speak English.'),
                                   ('pt', 'A mesma voz também pode falar português.')]:
                result = synthesize(args.url, text, language, output / f'clone-{extension}-{language}.wav',
                                    voice=voice, session=session)
                inspect_audio(result['output'])
                result.update(language=language, kind=f'clone-{extension}')
                report['cases'].append(result)
        report['gpu_after'] = subprocess.check_output([
            'nvidia-smi', '--query-gpu=name,memory.used,memory.total,utilization.gpu', '--format=csv'], text=True)
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = str(exc)
        raise
    finally:
        stop.set()
        if monitor:
            monitor.join(timeout=6)
        report['memory_samples'] = len(memory)
        if memory:
            report['peak_device_memory_mib'] = [max(s['gpu_used_mib'][i] for s in memory) for i in range(len(memory[0]['gpu_used_mib']))]
            report['memory_note'] = 'Device-wide sampled usage, includes other processes; transient peaks may be missed.'
            rss = [s['server_rss_mib'] for s in memory if 'server_rss_mib' in s]
            if rss:
                report['peak_server_rss_mib'] = max(rss)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(f'Report: {report_path}')


if __name__ == '__main__':
    main()
