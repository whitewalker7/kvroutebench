# Terminal demo: 10 minutes

Run commands from the repository root. Increase terminal font size before sharing. No UI is needed. Commands 1–4 read local code and saved evidence only; no model servers are required.

## 1. Question and setup — 0:00–2:00

```bash
python3 scripts/terminal-demo.py intro
```

Say: “I am testing whether smarter placement avoids repeating prompt processing. Two workers have separate KV caches. Everything stays the same except routing policy.” Explain prefill, decode, and TTFT in one sentence each. Three labels A/B/C identify different prefixes.

## 2. Show the requests — 2:00–5:00

```bash
python3 scripts/terminal-demo.py replay
```

Explicitly say this is a replay of saved measurements. Rows appear with illustrative pacing. W1/W2 identify workers, reused/prompt counts show actual reported cache reuse, Fresh shows remaining work, and TTFT is the observed client wait. Bars encode fresh-token fraction, not elapsed time. Yellow LARGE means over half of prompt tokens were processed afresh; green REUSE means at most half.

Explain: round-robin sends each family to both workers; cache-aware retains family placement in this trace. Once both workers are warm, round-robin is fast too. No need to narrate every row.

## 3. Compare results — 5:00–7:00

```bash
python3 scripts/terminal-demo.py results
```

Say: “Six large prefills became three. Mean TTFT fell from 846.7 to 437.1 ms, a 48.4% reduction in this run.” Show token reuse and the 6/6 versus 4/8 request split. Equal request counts do not mean equal work.

## 4. Show actual code — 7:00–9:00

```bash
python3 scripts/terminal-demo.py code
```

This prints source with line numbers. Point to the streaming client's first nonempty content delta and the trace builder's fixed request bodies. Explain that the runner resets both workers and starts a fresh gateway before each policy. Do not read every line aloud.

## 5. Close — 9:00–10:00

One seed, sequential traffic, small CPU model, no cache pressure: this does not rank production routers. Ask: “When could an idle worker without the prefix beat a busy worker with it?” Next experiment: concurrent requests and queueing.

Repository: https://github.com/whitewalker7/kvroutebench

## Optional live replacement for step 2

Only use this after a rehearsal with both benchmark containers available, the SMG environment installed, and ports 8010/29010 free:

```bash
python3 scripts/terminal-demo.py live --seed 7
```

This restarts both benchmark workers and runs actual inference. It prints a new results table and saves a new `.runs/comparison-…` directory. Do not present the default saved results as belonging to this live run. To inspect the new results use:

```bash
python3 scripts/terminal-demo.py results --run .runs/comparison-YOUR-RUN-ID
```

If live setup fails, use the saved replay and state that it is recorded. Reproduction and methodology are documented in the README and METHODS.md.
