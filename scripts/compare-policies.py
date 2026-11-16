"""Small sequential or burst SMG comparison. Restarts only the two benchmark workers.

Three request lanes, four rounds: repeated prefixes by default, or unique-prefix control.
Concurrency 3 submits A/B/C together, waiting for each burst before the next.
This is an exploratory placement experiment, not a throughput or tail benchmark.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import csv
import hashlib
import json
import platform
import random
import socket
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ["http://127.0.0.1:8001", "http://127.0.0.1:8002"]
CONTAINERS = ["kvroutebench-worker-1", "kvroutebench-worker-2"]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def api(url, payload=None):
    request = Request(url) if payload is None else Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def make_trace(template, seed, answer_length="short", reuse="repeated"):
    if reuse not in ("repeated", "unique"):
        raise ValueError("reuse must be repeated or unique")
    if answer_length not in ("short", "long"):
        raise ValueError("answer_length must be short or long")
    families = []
    for family in range(3):
        body = copy.deepcopy(template)
        label = hashlib.sha256(f"kvroutebench:{seed}:{family}".encode()).hexdigest()[:24]
        body["messages"][0]["content"] = (
            f"Dataset {label}. Ignore this label when answering.\n\n"
            + body["messages"][0]["content"])
        if answer_length == "long":
            content = body["messages"][0]["content"]
            instruction = "answer the final question in one short sentence."
            if instruction not in content:
                raise ValueError("Long-answer workload requires the expected short-answer instruction")
            body["messages"][0]["content"] = content.replace(instruction,
                "answer the final question in a detailed explanation of about 200 words. "
                "Explain how the queue handles bursts, waiting, and priorities, with examples.", 1)
        body["max_tokens"] = 128 if answer_length == "long" else 16
        families.append(body)
    # Sequential round-robin visits both workers for each repeated family.
    trace = []
    for turn in range(4):
        for family, body in enumerate(families):
            item = {"family": family, "round": turn, "body": copy.deepcopy(body)}
            if reuse == "unique":
                # Keep the original first round; later rounds get new early labels.
                # The text after the label, answer cap, and arrival pattern stay fixed.
                if turn:
                    label = hashlib.sha256(f"kvroutebench:{seed}:{family}:round:{turn}".encode()).hexdigest()[:24]
                    content = item["body"]["messages"][0]["content"]
                    suffix = content.split("\n\n", 1)[1]
                    item["body"]["messages"][0]["content"] = (
                        f"Dataset {label}. Ignore this label when answering.\n\n" + suffix)
                item["prefix_label"] = f"{'ABC'[family]}{turn + 1}"
            trace.append(item)
    return trace


def checked_row(record, item, index):
    if record.get("http_status") != 200 or not record.get("done") or "error" in record:
        raise ValueError("Failed/incomplete request; inspect raw output")
    if record.get("worker") not in WORKERS or record.get("ttft_ms") is None:
        raise ValueError("Missing worker identity or TTFT")
    usage = record.get("usage") or {}
    timings = record.get("server_timings") or {}
    prompt, cached = usage.get("prompt_tokens"), record.get("cached_tokens")
    if not isinstance(prompt, int) or not isinstance(cached, int) or not 0 <= cached <= prompt:
        raise ValueError("Missing or invalid cache accounting")
    if timings.get("cache_n") != cached or timings.get("prompt_n") != prompt - cached:
        raise ValueError("Usage and native cache accounting disagree")
    if record["request"] != item["body"]:
        raise ValueError("Client changed the trace request")
    return {"index": index, "family": item["family"], "round": item["round"],
            "prefix_label": item.get("prefix_label", "ABC"[item["family"]]),
            "worker": record["worker"], "ttft_ms": record["ttft_ms"],
            "end_to_end_ms": record["end_to_end_ms"], "prompt_tokens": prompt,
            "cached_tokens": cached, "completion_tokens": usage.get("completion_tokens"),
            "prompt_ms": timings.get("prompt_ms"), "generation_ms": timings.get("predicted_ms"),
            "request_id": record.get("request_id"), "router_request_id": record.get("router_request_id")}


def summarize(rows):
    return {
        "requests": len(rows),
        "mean_completion_tokens": (statistics.mean(r["completion_tokens"] for r in rows)
            if all(isinstance(r.get("completion_tokens"), int) for r in rows) else None),
        "mean_generation_ms": statistics.mean(r["generation_ms"] for r in rows),
        "median_ttft_ms": statistics.median(r["ttft_ms"] for r in rows),
        "mean_ttft_ms": statistics.mean(r["ttft_ms"] for r in rows),
        "mean_end_to_end_ms": statistics.mean(r["end_to_end_ms"] for r in rows),
        "first_round_median_ttft_ms": statistics.median(r["ttft_ms"] for r in rows if r["round"] == 0),
        "later_rounds_median_ttft_ms": statistics.median(r["ttft_ms"] for r in rows if r["round"] > 0),
        "token_weighted_reuse": sum(r["cached_tokens"] for r in rows) / sum(r["prompt_tokens"] for r in rows),
        "workers": {worker: {
            "requests": sum(r["worker"] == worker for r in rows),
            "prompt_tokens_processed": sum(r["prompt_tokens"] - r["cached_tokens"] for r in rows if r["worker"] == worker),
            "server_prompt_ms": sum(r["prompt_ms"] for r in rows if r["worker"] == worker),
            "server_generation_ms": sum(r["generation_ms"] for r in rows if r["worker"] == worker),
        } for worker in WORKERS},
    }



def print_heading(policy):
    name = {"round_robin": "ROUND-ROBIN | alternate workers",
            "cache_aware": "CACHE-AWARE | prefer matching prefixes"}[policy]
    print("\n" + "=" * 78)
    print(name)
    print("=" * 78)
    print("W1=:8001 W2=:8002 | bars=fresh-token fraction | LARGE=more than half fresh")
    print(" #  Prefix  Worker   Reused / prompt   Fresh     TTFT       Out   Decode(ms)  Prefill work")
    print("-" * 78, flush=True)


def print_row(row):
    fresh = row["prompt_tokens"] - row["cached_tokens"]
    large = fresh > row["prompt_tokens"] / 2
    bar = "#" * max(1, round(12 * fresh / row["prompt_tokens"]))
    line = (f"{row['index'] + 1:2}  {row.get('prefix_label', 'ABC'[row['family']]):>4}     "
            f"W{WORKERS.index(row['worker']) + 1}      "
            f"{row['cached_tokens']:4} / {row['prompt_tokens']:<4}   {fresh:5}  "
            f"{row['ttft_ms']:8.1f} ms  {str(row.get('completion_tokens', 'NA')):>3}  "
            f"{row['generation_ms']:10.1f}  {bar:<12} {'LARGE' if large else 'REUSE'}")
    # Color only on interactive terminals; saved output stays plain text.
    import os
    if sys.stdout.isatty() and 'NO_COLOR' not in os.environ:
        line = ("\033[33m" if large else "\033[32m") + line + "\033[0m"
    print(line, flush=True)


def print_comparison(summaries, concurrency=1):
    rr, ca = summaries['round_robin'], summaries['cache_aware']
    print("\n" + "=" * 70)
    print("RESULTS | this run only")
    print("=" * 70)
    print(f"{'Metric':32} {'Round-robin':>16} {'Cache-aware':>16}")
    print("-" * 70)
    for label, key, fmt in [('Mean TTFT (ms)', 'mean_ttft_ms', '.1f'),
                            ('Mean full response (ms)', 'mean_end_to_end_ms', '.1f'),
                            ('Prompt-token reuse', 'token_weighted_reuse', '.1%')]:
        print(f"{label:32} {format(rr[key], fmt):>16} {format(ca[key], fmt):>16}")
    for label, key in [('Mean output tokens', 'mean_completion_tokens'),
                       ('Mean server decode (ms)', 'mean_generation_ms')]:
        if rr.get(key) is not None and ca.get(key) is not None:
            print(f"{label:32} {rr[key]:16.1f} {ca[key]:16.1f}")
    counts = lambda summary: ' / '.join(str(summary['workers'][w]['requests']) for w in WORKERS)
    print(f"{'Requests on W1 / W2':32} {counts(rr):>16} {counts(ca):>16}")
    for label, key in [('TTFT', 'mean_ttft_ms'), ('Full response', 'mean_end_to_end_ms')]:
        saving = 100 * (1 - ca[key] / rr[key])
        direction = "lower" if saving >= 0 else "higher"
        print(f"{label}: {abs(saving):.1f}% {direction} mean latency with cache-aware routing.")
    print("Full response includes stream completion; it is not just first-token latency.")
    print(f"CPU traffic; burst width {concurrency}; one trace. No throughput or tail-latency claim.")
    print("Next question: can waiting for a warm worker cost more than new prefill?")

def wait_workers():
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if all(api(w + "/health").get("status") == "ok" for w in WORKERS):
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Workers did not become healthy")


def wait_gateway(process):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("SMG exited; inspect smg.log")
        try:
            workers = api("http://127.0.0.1:8010/workers")["workers"]
            ready = {w["url"] for w in workers if w.get("is_healthy") and w.get("status") == "ready"}
            if ready == set(WORKERS):
                return workers
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.5)
    raise RuntimeError("SMG registration timed out; inspect smg.log")



def run_batches(trace, concurrency, send):
    """Yield completions; never start the next burst until this one finishes."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(trace), concurrency):
            pending = [pool.submit(send, i, trace[i])
                       for i in range(start, min(start + concurrency, len(trace)))]
            for future in as_completed(pending):
                yield future.result()


def send_request(index, item, directory, run_dir, started):
    fixture = directory / f"request-{index:02d}.json"
    save(fixture, item["body"])
    launched_ms = (time.monotonic() - started) * 1000
    result = subprocess.run([sys.executable, str(run_dir / "stream_once.py"), str(fixture),
        "--url", "http://127.0.0.1:8010/v1/chat/completions"],
        capture_output=True, text=True, timeout=180)
    finished_ms = (time.monotonic() - started) * 1000
    (directory / f"result-{index:02d}.json").write_text(result.stdout)
    (directory / f"result-{index:02d}.stderr").write_text(result.stderr)
    save(directory / f"dispatch-{index:02d}.json",
         {"index": index, "client_process_start_ms": launched_ms,
          "client_process_end_ms": finished_ms})
    if result.returncode:
        raise RuntimeError(f"Request {index} failed; see raw result")
    return checked_row(json.loads(result.stdout), item, index)

def run_policy(policy, trace, run_dir, concurrency=1):
    directory = run_dir / policy
    directory.mkdir()
    print(f"\n{policy}: restarting benchmark workers to clear RAM cache", flush=True)
    subprocess.run(["docker", "restart", *CONTAINERS], check=True, capture_output=True, timeout=90)
    wait_workers()
    inspection = json.loads(subprocess.check_output(["docker", "inspect", *CONTAINERS]))
    save(directory / "workers.json", [{"name": c["Name"], "image_id": c["Image"],
          "command": c["Config"]["Cmd"], "nano_cpus": c["HostConfig"]["NanoCpus"],
          "started_at": c["State"]["StartedAt"]} for c in inspection])
    counts = []
    for item in trace:
        prompt = api(WORKERS[0] + "/apply-template", {"messages": item["body"]["messages"], "add_generation_prompt": True})["prompt"]
        count = len(api(WORKERS[0] + "/tokenize", {"content": prompt, "add_special": True, "parse_special": True})["tokens"])
        if count + item["body"]["max_tokens"] > 4096:
            raise ValueError("Trace exceeds worker context")
        counts.append(count)
    save(directory / "token_counts.json", counts)
    with (directory / "smg.log").open("w") as log:
        process = subprocess.Popen(["bash", str(ROOT / "scripts/start-smg.sh"), policy], stdout=log, stderr=subprocess.STDOUT)
        try:
            save(directory / "registration.json", wait_gateway(process))
            rows = []
            print_heading(policy)
            print(f"Burst width: {concurrency}; rows appear in completion order.", flush=True)
            started = time.monotonic()
            def send(index, item):
                return send_request(index, item, directory, run_dir, started)
            for row in run_batches(trace, concurrency, send):
                rows.append(row)
                with (directory / "requests.csv").open("w", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerows(sorted(rows, key=lambda r: r["index"]))
                print_row(row)
            save(directory / "dispatch-summary.json", {
                "burst_width": concurrency, "completed_requests": len(rows),
                "elapsed_ms": (time.monotonic() - started) * 1000,
                "note": "Process dispatch times include subprocess overhead; not server queue timings."})
            summary = summarize(rows)
            save(directory / "summary.json", summary)
            return summary
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--concurrency", type=int, choices=(1, 3), default=1,
                        help="1: sequential; 3: A/B/C bursts, waiting between bursts")
    parser.add_argument("--answer-length", choices=("short", "long"), default="short",
                        help="short: original prompt, cap 16; long: detailed answer, cap 128")
    parser.add_argument("--reuse", choices=("repeated", "unique"), default="repeated",
                        help="repeated: A/B/C repeat; unique: new leading label on every request")
    parser.add_argument("--report", type=Path, help="Read a completed run; no inference or worker changes")
    args = parser.parse_args()
    if args.report:
        directory = args.report
        if not (directory / "comparison.json").exists() or (directory / "failure.json").exists():
            parser.error("Report requires a successfully completed comparison directory")
        manifest = json.loads((directory / "manifest.json").read_text())
        trace = json.loads((directory / "trace.json").read_text())
        summaries = {}
        for policy in ("round_robin", "cache_aware"):
            rows = [checked_row(json.loads((directory / policy / f"result-{i:02d}.json").read_text()), item, i)
                    for i, item in enumerate(trace)]
            summaries[policy] = summarize(rows)
        print(f"SAVED RESULTS | {directory} | no inference run")
        print(f"Prefix reuse workload: {manifest.get('reuse', 'repeated')}")
        print_comparison(summaries, manifest["concurrency"])
        return
    # Never kill an existing user-run gateway or reset workers before this check.
    for port in (8010, 29010):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is occupied. Stop the manually launched SMG first.")
    template = json.loads((ROOT / "configs/long-prefix.json").read_text())
    trace = make_trace(template, args.seed, args.answer_length, args.reuse)
    policies = ["round_robin", "cache_aware"]
    random.Random(args.seed).shuffle(policies)
    directory = ROOT / ".runs" / ("comparison-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    save(directory / "trace.json", trace)
    for name, path in {"stream_once.py": ROOT / "routerbench/stream_once.py",
                       "compare-policies.py": Path(__file__),
                       "start-smg.sh": ROOT / "scripts/start-smg.sh"}.items():
        (directory / name).write_text(path.read_text())
    save(directory / "manifest.json", {"seed": args.seed, "policy_order": policies,
         "system": platform.platform(), "python": sys.version,
         "model": json.loads((ROOT / "configs/model.json").read_text()),
         "smg_dependencies": subprocess.check_output([str(ROOT / ".venv-smg/bin/python"), "-m", "pip", "freeze"], text=True).splitlines(),
         "cache_reset": "restart both benchmark containers and launch fresh SMG per policy",
         "warmup_requests": 0, "concurrency": args.concurrency, "retries": 0,
         "reuse": args.reuse, "answer_length": args.answer_length, "max_tokens": trace[0]["body"]["max_tokens"],
         "arrival_model": "barrier-separated bursts; wait for all completions before next burst",
         "limitations": "Single exploratory run; synthetic labels distinguish shared warehouse text. No cache-capacity pressure. CPU results only; no direct server queue-time measurement. Arrival order within bursts is not deterministic. Output limit is recorded in max_tokens; actual lengths may differ between policies. Outputs are never fed back. Long-answer mode changes the prompt too; not a pure output-length intervention. SMG tie-breaking randomness is not seeded by this harness."})
    print(f"Saving comparison to {directory}", flush=True)
    print(f"Prefix reuse workload: {args.reuse}. Unique labels may still share chat-template tokens.", flush=True)
    print(f"Answer workload: {args.answer_length}; output cap: {trace[0]['body']['max_tokens']} tokens. Out = actual output tokens; Decode = server generation time.", flush=True)
    summaries = {}
    try:
        for policy in policies:
            summaries[policy] = run_policy(policy, trace, directory, args.concurrency)
        save(directory / "comparison.json", summaries)
        print_comparison(summaries, args.concurrency)
    except Exception as error:
        save(directory / "failure.json", {"error": str(error)})
        raise


if __name__ == "__main__":
    main()
