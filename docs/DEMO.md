# A 15-minute meetup demo

## 0–2 minutes: the question and artifact

Open the dashboard. “I built a small benchmark to test whether prefix-aware placement avoids repeated prefill work.” Show the repo and the recorded-run label. State the setup: two CPU workers, one small model, two policies in the same gateway.

## 2–4 minutes: the minimum mechanism

Draw client → gateway → two workers. Explain prefill versus decode and that worker-local KV reuse can reduce prompt processing. The router estimates which worker has a useful prefix; it does not hold the model's KV tensors itself.

## 4–7 minutes: replay the evidence

Reset the dashboard, then replay. Pause after three requests: each new family needs substantial prefill. Move to six: round-robin has sent families to both workers, while cache-aware has reused placement. Reveal all twelve: both policies now have fast requests.

Click one slow and one fast request, inspect raw JSON, and connect cached tokens to prompt time and client TTFT. Show six large prefills versus three and mean TTFT 846.7 versus 437.1 ms. State “in this run.”

## 7–10 minutes: code walkthrough

Open `scripts/compare-policies.py`: `make_trace`, cache resets, identical request bodies, and validation. Open `routerbench/stream_once.py`: monotonic timing and the first nonempty content chunk. Show tests and raw CSVs. Explain why timing the full non-streamed response would answer a different question.

## 10–12 minutes: optional live run

Keep the recorded demo open as fallback. If workers and dependencies are ready and no standalone gateway occupies the ports, run:

```bash
python3 scripts/compare-policies.py --seed 8
```

This restarts the benchmark workers. Read its table live; the dashboard does not update automatically. Do not run an installation during the talk.

## 12–15 minutes: boundaries and discussion

Cache-aware placement avoided repeated work in this sequential trace. It also concentrated assignments 4/8 instead of 6/6. Under concurrency, waiting on a warm worker may cost more than prefill on an idle one. That is the next experiment.

Ask the audience: “When would you deliberately send a request away from the worker with its cached prefix?”

## Before presenting

Start `python3 scripts/serve-demo.py` and open http://127.0.0.1:8765. Check replay, a raw JSON link, and repository access. Have the runner and client open in an editor. Rehearse once with a timer. Use recorded results if live inference is unavailable.

Claims to avoid: universal 48% speedup, production-ready load balance, exact per-token streaming timings, or a broad router ranking. One slot is not necessarily one retained history; RAM prompt-history storage matters. A router's remembered prefix can become stale after worker eviction.
