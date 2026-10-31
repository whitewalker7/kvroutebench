# Experiment 001: repeated prefixes on two CPU workers

## Workload and isolation

The published evidence is `comparison-1b1b92e7aba341c6b61baa2b994dbc90`, seed 7. Three synthetic leading labels distinguish prompt families sharing warehouse background text. The sequence is ABC repeated four times: 12 sequential requests per policy, concurrency one. Family lengths are 599, 595, and 599 prompt tokens. Outputs are capped at 16 tokens, temperature zero, and never fed into subsequent prompts. This is repeated fixed input, not evolving conversation history.

Each policy uses identical bodies, model, worker image, resource limits, and client. Both worker containers are restarted and a fresh gateway launched before each policy. There are no warmup requests and retries are disabled. This resets worker RAM and router state; it does not clear the OS page cache. Seeded policy order for this run is round-robin then cache-aware. The harness does not seed SMG tie-breaking.

## Runtime

- Qwen2.5-0.5B-Instruct Q4_K_M; revision and SHA256 in `configs/model.json`.
- llama.cpp build 11889, commit d854d98ba; image digest in `configs/worker-image.json`.
- Two localhost workers, ports 8001/8002; four CPU quota and four threads each, one slot, 4096 context, CPU only.
- Prefix caching enabled; `--cache-reuse 0` disables chunk-shifting reuse, not ordinary prefix reuse. Prompt-history RAM cache uses the engine default of 8192 MiB. One slot does not mean only one prompt history can be retained.
- SMG 1.13.0; exact dependency freeze in the manifest. HTTP pass-through, tokenizer autoload disabled, generic OpenAI-compatible workers.
- Cache-aware defaults observed at startup: cache threshold 0.3, absolute balance threshold 64, relative threshold 1.5, tree size 67108864, block size 16, TTL 180 seconds, eviction interval 60 seconds. Router prefix estimates are not direct worker cache events.

Inspect `demo/evidence/*/workers.json` for actual container arguments, image IDs, and resource limits. Historical runner, client and gateway-launch scripts are included alongside the evidence. The manifest records OS and Python, but does not capture the CPU model or competing host activity; this limits hardware reproducibility.

## Measurement

Client TTFT uses a monotonic clock from before sending the request until the first nonempty streamed content delta. Role-only events, usage chunks and DONE do not count. Transport and queueing are included. A content chunk can contain multiple tokens.

Cached tokens come from final `usage.prompt_tokens_details.cached_tokens`, cross-checked against native timing counters. Token-weighted reuse is total cached prompt tokens divided by total prompt tokens. Missing metrics are not converted to zero. Worker assignment comes from `x-smg-routed-worker-id`. Gateway request IDs differ from model-completion IDs.

Server prompt processing time and end-to-end time are separate metrics. Per-worker request counts do not establish equal work. A large prefill in the UI means more than half of prompt tokens were processed afresh.

## Interpretation and limits

Round-robin performs six large prefills; cache-aware performs three. Mean TTFT is 846.7 versus 437.1 ms. Once the relevant histories are warm, both policies are fast. Cache-aware assigns four requests to one worker and eight to the other.

This is one small exploratory run without concurrent queues, cache-capacity pressure, low-reuse controls, or independent repetitions. Do not infer GPU results, production throughput, tail latency, or a universal router winner. The different generated answers do not change later inputs. Answer quality is not evaluated here.

The dashboard replays saved records, not live inference. Its animation timing is illustrative. Headline statistics describe the full run even while only some request rows are revealed.
