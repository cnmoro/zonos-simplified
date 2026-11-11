#!/usr/bin/env python3
"""Download the minimal release and build the native CUDA API."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/Zyphra/ZONOS3-Mini.git'
MODEL = 'Zyphra/ZONOS3-Mini'
FILES = ['gguf/zonos3-ptq.gguf', 'gguf/zac-keep2.gguf', 'gguf/spk-encoder.gguf']


def run(*args):
    subprocess.run(args, check=True, cwd=ROOT)


def main():
    lock_path = ROOT / 'install-lock.json'
    locked = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-revision', default=locked.get('runtime_commit', 'main'))
    parser.add_argument('--model-revision', default=locked.get('model_revision', 'main'))
    parser.add_argument('--cuda-host-compiler', default=shutil.which('g++-12') or shutil.which('g++'),
                        help='CUDA host compiler; GCC 12 is compatible with the CUDA 12.0 toolkit')
    parser.add_argument('--jobs', type=int, default=4, help='Build jobs; 4 limits compilation RAM')
    args = parser.parse_args()
    for command in ('git', 'cmake', 'cargo', 'nvcc', 'ffmpeg'):
        if not shutil.which(command):
            raise RuntimeError(f'Missing prerequisite: {command}')
    from huggingface_hub import HfApi, hf_hub_download
    # Resolve mutable references once and record exact revisions for reproducibility.
    info = HfApi().model_info(MODEL, revision=args.model_revision)
    revision = info.sha
    local = ROOT / 'models'
    files = FILES + [f.rfilename for f in info.siblings
                     if f.rfilename.startswith(('gguf/voices/English/', 'gguf/voices/Portuguese/'))]
    # Language folder names are checked against the actual release, never silently omitted.
    for language in ('English', 'Portuguese'):
        if not any(f.startswith(f'gguf/voices/{language}/') for f in files):
            raise RuntimeError(f'Release has no gguf/voices/{language}/; inspect model file listing')
    for name in files:
        hf_hub_download(MODEL, name, revision=revision, local_dir=local)
    source = ROOT / 'vendor' / 'ZONOS3-Mini'
    if not source.exists():
        run('git', 'clone', REPO, str(source))
    run('git', '-C', str(source), 'checkout', args.runtime_revision)
    run('git', '-C', str(source), 'submodule', 'update', '--init', '--recursive',
        'servers/ggml/ggml', 'third_party/zyphra-textnorm')
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    from patch_runtime import patch
    patch()
    build = ROOT / 'build' / 'cuda'
    run('cmake', '-S', str(source / 'servers/ggml'), '-B', str(build),
        '-DCMAKE_BUILD_TYPE=Release', '-DGGML_CUDA=ON', '-DCMAKE_CUDA_ARCHITECTURES=native',
        f'-DCMAKE_CUDA_HOST_COMPILER={args.cuda_host_compiler}')
    run('cmake', '--build', str(build), '--config', 'Release', '-j', str(args.jobs), '--target', 'zonos3-server')
    (ROOT / 'install-lock.json').write_text(json.dumps({
        'runtime_commit': commit, 'model_revision': revision, 'files': files,
    }, indent=2) + '\n')
    print('Installed. Start with: bash scripts/serve.sh')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
