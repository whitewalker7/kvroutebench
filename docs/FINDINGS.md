# Initial findings: prefix reuse, waiting, and completion time

These are exploratory measurements from two CPU-only llama.cpp workers behind SMG 1.13.0. Each policy receives the same 12-request trace and starts with restarted workers and a fresh router. Three prompt families repeat four times. The burst workloads send A/B/C together and wait for all three before sending the next burst.

## Measured means

| Workload | Metric | Round-robin | Cache-aware | Reduction |
|---|---|---:|---:|---:|
| Sequential, 16 output tokens | TTFT | 846.7 ms | 437.1 ms | 48.4% |
| Three-request bursts, 16 output tokens | TTFT | 2035.7 ms | 976.1 ms | 52.1% |
| Three-request bursts, 16 output tokens | Full response | 2316.3 ms | 1247.5 ms | 46.1% |
| Three-request bursts, 128 output tokens | TTFT | 2800.4 ms | 1789.8 ms | 36.1% |
| Three-request bursts, 128 output tokens | Full response | 5278.1 ms | 4102.7 ms | 22.3% |

Output lengths in this table are observed completion-token counts, not merely configured limits. All requests in each selected burst run generated exactly the indicated token count. Full response includes terminal stream handling and response closure; it is not precisely time to the last visible content chunk.

## What the records show

In the sequential example, round-robin incurs six large prefills, while cache-aware incurs three. Once histories are available on both workers, round-robin also produces fast responses. This demonstrates avoided duplicate warmup computation, not a permanent latency gap at steady state.

In the long-answer burst run, cache-aware requests C (#6) and A (#4) share worker 1. Both reuse 620 of 621 prompt tokens. C has TTFT 26.6 ms and server generation time 2567.7 ms; A has TTFT 2611.2 ms. This is consistent with A waiting behind C's generation. No direct server queue-time measurement was collected, so those durations do not prove an exact queue decomposition.

In that same run, mean TTFT improves 36.1%, while mean full-response latency improves 22.3%. Reporting the former as an overall response speedup would overstate the observed completion-time benefit. Both metrics are necessary.

Cache-aware still has lower average latency in these selected runs. No reversal or universal winner has been established. Worker assignments in the burst runs are 8/4 for cache-aware and 6/6 for round-robin; equal request counts alone do not mean equal work.

## Evidence and rerun reports

- [Sequential raw evidence](../demo/evidence/)
- [Short-answer burst evidence](../results/burst-short/)
- [Long-answer burst evidence](../results/burst-long/)

Each burst directory preserves the original trace, manifest, client/runner snapshots, per-request JSON, CSV, and original summary. `analysis.json` is a separate recalculation that includes full-response means. The original records are not rewritten.

From the repository root, inspect either saved run without model servers:

```bash
python3 scripts/compare-policies.py --report results/burst-short
python3 scripts/compare-policies.py --report results/burst-long
```

## What remains unproven

These are single selected runs, not repeated estimates. The long-answer instruction also changes the prompt, so the answer-length comparison is not a controlled one-variable intervention. Within-burst arrival order, router tie-breaking, host contention, and worker assignment can vary. Both workers share one CPU host. There is no GPU, sustained-load, cache-capacity, or tail-latency conclusion.

The low-reuse control is implemented but has no recorded results yet. Independent repetitions and policy-order variation must follow before stronger claims. See [methods](METHODS.md) for configurations and measurement definitions.
