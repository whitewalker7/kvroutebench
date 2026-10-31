#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
policy="${1:-round_robin}"
if [[ "$#" -gt 1 || ! "$policy" =~ ^(round_robin|cache_aware)$ ]]; then
  echo "Usage: bash scripts/start-smg.sh [round_robin|cache_aware]" >&2
  exit 2
fi
# Start with HTTP pass-through; no gateway tokenizer or hidden request retries.
exec "$project_dir/.venv-smg/bin/smg" launch \
  --host 127.0.0.1 \
  --port 8010 \
  --worker-urls http://127.0.0.1:8001 http://127.0.0.1:8002 \
  --policy "$policy" \
  --disable-retries \
  --disable-tokenizer-autoload \
  --health-check-endpoint /health \
  --prometheus-host 127.0.0.1 \
  --prometheus-port 29010 \
  --request-timeout-secs 120 \
  --log-level info
