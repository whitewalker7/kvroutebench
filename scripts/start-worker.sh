#!/usr/bin/env bash
set -euo pipefail

# Default remains worker 1; pass 2 to start an independent second worker.
worker_id="${1:-1}"
if [[ "$#" -gt 1 || ! "$worker_id" =~ ^[12]$ ]]; then
  echo "Usage: bash scripts/start-worker.sh [1|2]" >&2
  exit 2
fi
worker_port="$((8000 + worker_id))"

# Locate this checkout so the command works from any current directory.
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
worker_image="ghcr.io/ggml-org/llama.cpp@sha256:5741ab30aae42af23ca57d9b98a6d4544cb09c21f372f92c5ee55312fa8b8b0c"

# Leave the worker running; inspect startup with docker logs.
# --rm removes only this container when it stops, not the mounted model file.
exec docker run --detach --rm --pull=never \
  --name "kvroutebench-worker-${worker_id}" \
  --cpus 4 \
  --publish "127.0.0.1:${worker_port}:8001" \
  --mount "type=bind,source=${project_dir}/models,target=/models,readonly" \
  "$worker_image" \
  --model /models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
  --alias routerbench-tiny \
  --host 0.0.0.0 \
  --port 8001 \
  --ctx-size 4096 \
  --parallel 1 \
  --threads 4 \
  --threads-batch 4 \
  --n-gpu-layers 0 \
  --cache-prompt \
  --cache-reuse 0 \
  --metrics \
  --no-webui
