#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$project_dir/models"
model_file="$project_dir/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
expected="74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
if [[ -f "$model_file" ]]; then
  printf '%s  %s\n' "$expected" "$model_file" | sha256sum --check
  exit 0
fi
curl --fail --location --retry 3 'https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf' --output "$model_file.partial"
printf '%s  %s\n' "$expected" "$model_file.partial" | sha256sum --check
mv -- "$model_file.partial" "$model_file"
