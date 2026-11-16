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

## Next experiment: three-request bursts

The runner now accepts `--concurrency 3`. Each burst contains one request from each family; all responses must complete before the next burst begins. This preserves sequential repeats within each family while allowing different families to overlap. Default concurrency one preserves the original experiment. No burst inference results have been collected by the assistant.

Read TTFT together with cached tokens and per-worker prompt/decode work. A high cache-hit count does not guarantee low TTFT. TTFT minus server prompt time must not be labeled exact queue time: transport, scheduling, and other work contribute. Both workers share the same host CPU; changes can reflect CPU contention as well as request placement. Router defaults remain unchanged and may not rebalance at this small load. A negative or unchanged result is valid.

This workload does not isolate warm-state queueing from warmup. Next controls are low-reuse input, independent repeated seeds, and separate warm-state experiments before attempting production conclusions.

## Longer-answer workload

Use `--answer-length long` with `--concurrency 3` to ask for a detailed explanation and raise the output cap from 16 to 128 tokens. The requested explanation is intentionally longer than the cap; completion can be truncated or end early. No forced minimum or suppressed end-of-sequence token is used. `Out` records actual completion tokens and `Decode(ms)` records native server generation time. The same generated trace is used for both policies; outputs never become later inputs.

This changes the prompt instruction as well as the output cap. Compare policies within this workload, then inspect changes relative to the short-answer run as exploratory evidence, not an isolated causal effect of answer length. Actual completion lengths can differ across policies. High cache reuse with increased TTFT is consistent with waiting, but direct queue timings are not measured.

## Reporting full-response latency

The summary now reports mean TTFT and mean end-to-end latency, with separate percentage changes. End-to-end timing uses the client's saved `end_to_end_ms`, through stream completion and response-context exit, including terminal usage/DONE handling; it is not exactly time to the last content chunk. Output lengths accompany both metrics.

Use `python3 scripts/compare-policies.py --report .runs/comparison-ID` to recalculate summaries from validated raw records without running inference or modifying historical evidence. A failed or incomplete comparison cannot be reported as successful.

## Low-reuse control

`--reuse unique` assigns every request a different early synthetic label. Round one matches the repeated workload; later rounds replace only that label. All warehouse text after the label, output settings, and burst structure are preserved. Each routing policy receives the same complete trace. A1/B1/C1 followed by A2/B2/C2 in terminal output denotes distinct prefixes, not repeated A/B/C histories. All twelve prompts are tokenized and context-checked before inference. Equal character-length labels can still tokenize to different lengths.

This is a low-reuse control, not cache disabled. Chat-template tokens and the short text before the label can still be reused. Verify actual cached-token counters rather than assuming zero hits. The unchanged suffix cannot generally reuse its original contextual KV state after an early prefix change. This control is specific to the tested engine configuration.

Compare round-robin and cache-aware within this workload first. A reduction in the cache-aware advantage relative to repeated-prefix runs would support the locality explanation. A single run cannot establish equivalence or statistical significance. Seed repeats and policy-order variation are still required. No low-reuse inference measurements have been collected yet.
