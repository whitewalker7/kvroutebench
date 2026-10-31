"""Four short terminal presentation steps. Saved evidence by default; live is explicit."""
import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('comparison', ROOT / 'scripts/compare-policies.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def evidence(folder):
    trace = json.loads((folder / 'trace.json').read_text())
    return {policy: [comparison.checked_row(
        json.loads((folder / policy / f'result-{index:02d}.json').read_text()), item, index)
        for index, item in enumerate(trace)] for policy in ('round_robin', 'cache_aware')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['intro', 'replay', 'results', 'code', 'live'])
    parser.add_argument('--run', type=Path, default=ROOT / 'demo/evidence', help='Completed evidence directory')
    parser.add_argument('--delay', type=float, default=0.35, help='Illustrative replay delay, not measured time')
    parser.add_argument('--seed', type=int, default=7, help='Live trace seed')
    args = parser.parse_args()
    if args.delay < 0:
        parser.error('--delay must be nonnegative')
    if args.step == 'intro':
        print('''
======================================================================
 KVRouteBench | Does request placement avoid repeated prefill work?
======================================================================

                  +--> Worker 1 :8001 [local KV cache]
 Client --> SMG ---+
                  +--> Worker 2 :8002 [local KV cache]

 SAME: model, CPU limits, prompts, client, cache reset before each policy
 CHANGE: round-robin versus cache-aware placement

 A B C | A B C | A B C | A B C
 Three prompt families, each repeated four times. One request at a time.
 Synthetic leading labels distinguish otherwise shared warehouse text.

 PREFILL : process prompt tokens; reuse a matching prefix when available
 DECODE  : generate the answer
 TTFT    : client time until the first nonempty streamed answer content

 Question: how many times will each worker process each family afresh?
''')
    elif args.step == 'live':
        print('LIVE INFERENCE | restarts both benchmark workers; fresh gateway per policy.', flush=True)
        raise SystemExit(subprocess.call([sys.executable, str(ROOT / 'scripts/compare-policies.py'), '--seed', str(args.seed)]))
    elif args.step == 'code':
        print('CODE TOUR | actual source, with line numbers\n')
        snippets = [
            ('routerbench/stream_once.py', 'def read_stream', '\ndef main'),
            ('scripts/compare-policies.py', 'def make_trace', '\ndef checked_row'),
        ]
        for filename, start, end in snippets:
            lines = (ROOT / filename).read_text().splitlines()
            # Locate names rather than fixed line numbers, so edits do not stale the tour.
            begin = next(i for i, line in enumerate(lines) if line.startswith(start))
            finish = next((i for i in range(begin + 1, len(lines)) if lines[i].startswith(end.lstrip())), len(lines))
            print(f'--- {filename} ---')
            for i in range(begin, finish):
                print(f'{i+1:4} | {lines[i]}')
        print('\nRunner: run_policy resets workers, records identities and validates usage.')
        print('Tests: python3 -m unittest discover -s tests -v')
    else:
        rows = evidence(args.run)
        print(f'SAVED MEASUREMENTS | {args.run}\nNo inference is running. Replay pacing is illustrative.')
        if args.step == 'replay':
            print('W1 = port 8001; W2 = port 8002. Fresh = prompt tokens - reused tokens.')
            print('Bars show fresh-token fraction, NOT latency. LARGE = more than half fresh.')
            for policy, records in rows.items():
                comparison.print_heading(policy)
                for row in records:
                    comparison.print_row(row)
                    time.sleep(args.delay)
        else:
            comparison.print_comparison({policy: comparison.summarize(records) for policy, records in rows.items()})
            print('\nLARGE PREFILLS (> half the prompt processed afresh)')
            for policy, records in rows.items():
                count = sum(r['prompt_tokens'] - r['cached_tokens'] > r['prompt_tokens'] / 2 for r in records)
                print(f'  {policy:12}: {count} / {len(records)} requests')
            print('\nInspect evidence: result-XX.json and requests.csv in each policy directory.')


if __name__ == '__main__':
    main()
