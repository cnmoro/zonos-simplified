#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/build/cuda/zonos3-server"
MODEL="$ROOT/models/gguf"
nvidia-smi >/dev/null || { echo 'NVIDIA GPU unavailable. Check driver/device access.' >&2; exit 1; }
for file in "$BIN" "$MODEL/zonos3-ptq.gguf" "$MODEL/zac-keep2.gguf" "$MODEL/spk-encoder.gguf"; do
  [[ -f "$file" ]] || { echo "Missing: $file. Run python scripts/setup.py" >&2; exit 1; }
done
export ZONOS3_AUDIO_CACHE_DIR="${ZONOS3_AUDIO_CACHE_DIR:-$ROOT/outputs/audio-cache}"
export ZONOS3_VOICES_DIR="${ZONOS3_VOICES_DIR:-$ROOT/voices}"
# With certificates installed, serve HTTPS only by default.
if [[ -f "$ROOT/certs/server.pem" && -f "$ROOT/certs/server-key.pem" ]]; then
  export ZONOS3_TLS_CERT="${ZONOS3_TLS_CERT:-$ROOT/certs/server.pem}"
  export ZONOS3_TLS_KEY="${ZONOS3_TLS_KEY:-$ROOT/certs/server-key.pem}"
  export ZONOS3_TLS_PORT="${ZONOS3_TLS_PORT:-1920}"
  export ZONOS3_HTTP_DISABLED="${ZONOS3_HTTP_DISABLED:-1}"
  [[ "$ZONOS3_TLS_PORT" =~ ^[0-9]{1,5}$ ]] && ((10#$ZONOS3_TLS_PORT > 0 && 10#$ZONOS3_TLS_PORT < 65536)) || {
    echo 'Invalid ZONOS3_TLS_PORT; use 1..65535.' >&2; exit 1;
  }
  export ZONOS3_TLS_PORT="$((10#$ZONOS3_TLS_PORT))"
  printf '{"https_port":%s,"ca_certificate":"/ca.crt"}\n' "$ZONOS3_TLS_PORT" > "$ROOT/frontend/tls.json"
fi
export ZONOS3_FFMPEG="$(command -v ffmpeg)"
# Explicit decoder prevents automatic loading of a second, larger decoder.
# One generation slot, one decoder lane; CFG disabled in clients.
exec "$BIN" "$MODEL/zonos3-ptq.gguf" --gpu --zac-gpu \
  --zac "$MODEL/zac-keep2.gguf" --spk-encoder "$MODEL/spk-encoder.gguf" \
  --batch 1 --zac-threads 1 --max "${ZONOS3_MAX_TOKENS:-1000}" \
  --tts-default-voices-dir "$MODEL/voices" --studio-dir "$ROOT/frontend" \
  --host "${ZONOS3_HOST:-0.0.0.0}" --port "${ZONOS3_PORT:-1919}" "$@"
