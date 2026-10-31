# KVRouteBench

A reproducible experiment in prefix-aware LLM inference routing: **can placing requests near cached prefixes avoid repeated prefill work?**

Compare round-robin and cache-aware policies in SMG 1.13.0, with two CPU-only llama.cpp workers running Qwen2.5-0.5B-Instruct Q4_K_M. This is an early, inspectable experiment, not a production router ranking.

## Open the recorded browser demo

No model download or extra Python packages needed:

```bash
git clone https://github.com/whitewalker7/kvroutebench.git
cd kvroutebench
python3 scripts/serve-demo.py
```

Open http://127.0.0.1:8765. Replay request placement, compare TTFT bars, and click requests to inspect raw evidence. Playback illustrates a saved run; it does not perform live inference.

## First result

One sequential trace, three prefix families, four repetitions per family, seed 7:

| Metric | Round-robin | Cache-aware |
|---|---:|---:|
| Mean client TTFT | 846.7 ms | 437.1 ms |
| Prompt-token reuse | 51.4% | 75.2% |
| Large prefills | 6 | 3 |
| Requests per worker | 6 / 6 | 4 / 8 |

A large prefill means more than half the prompt tokens were processed afresh. Mean TTFT was **48.4% lower in this run**. Both policies became fast after warming the relevant workers. These 12 requests per policy do not establish throughput, tail latency, or performance under concurrent load. The round-robin median falls between six slow and six fast requests; its ratio is not a general speedup.

[Methods and limitations](docs/METHODS.md) · [Run manifest](demo/evidence/manifest.json) · [Round-robin CSV](demo/evidence/round_robin/requests.csv) · [Cache-aware CSV](demo/evidence/cache_aware/requests.csv)

## Reproduce inference locally

Requires Linux, Docker, Python 3.12 with venv support, curl, and sha256sum. Each worker has a four-CPU quota; the recorded run uses a small quantized model. The model download is about 491 MB, plus the container image and router environment.

```bash
bash scripts/download-model.sh
docker pull ghcr.io/ggml-org/llama.cpp@sha256:5741ab30aae42af23ca57d9b98a6d4544cb09c21f372f92c5ee55312fa8b8b0c
bash scripts/start-worker.sh 1
bash scripts/start-worker.sh 2
python3 -m venv .venv-smg
.venv-smg/bin/python -m pip install -r configs/smg-requirements.txt
python3 scripts/compare-policies.py --seed 7
```

Stop any manually running gateway on ports 8010/29010 first. The comparison **restarts both benchmark workers** to clear their RAM cache before each policy, starts a fresh gateway, sends the same trace, and saves raw records under `.runs/comparison-…`. It leaves the workers running. A seeded trace does not seed the router's tie-breaking choices.

To replace the demo with your own completed comparison:

```bash
python3 scripts/export-demo.py .runs/comparison-YOUR-RUN-ID
python3 scripts/serve-demo.py
```

Review the exported evidence before publishing. The exporter validates completed requests and copies only selected evidence files.

## Code tour

| File | Responsibility |
|---|---|
| `scripts/compare-policies.py` | Build trace, reset state, run both policies, validate and summarize |
| `routerbench/stream_once.py` | Parse SSE and time first nonempty answer content |
| `scripts/start-worker.sh` | Pinned worker image and explicit resource settings |
| `scripts/start-smg.sh` | Gateway policy, health checks, and retries disabled |
| `scripts/export-demo.py` | Turn saved evidence into dashboard data |
| `demo/` | Dependency-free browser UI and selected evidence |
| `routerbench/round_robin.py` | Educational baseline proxy; not used in the published comparison |

Run tests without models:

```bash
python3 -m unittest discover -s tests -v
```

Next experiments: independent repetitions, low-reuse controls, then concurrency to expose the cache-locality versus queueing trade-off. Additional routers come after those controls.

Code is MIT licensed. Models and upstream dependencies retain their own licenses. This project is not affiliated with the model or serving-engine authors.
