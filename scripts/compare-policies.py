"""Small sequential SMG comparison. Restarts only the two benchmark workers.

Three synthetic prefix families, four identical requests per family, interleaved.
This isolates initial placement/reuse; it is not a concurrency or tail benchmark.
"""

import argparse
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


def make_trace(template, seed):
    families = []
    for family in range(3):
        body = copy.deepcopy(template)
        label = hashlib.sha256(f"kvroutebench:{seed}:{family}".encode()).hexdigest()[:24]
        body["messages"][0]["content"] = (
            f"Dataset {label}. Ignore this label when answering.\n\n"
            + body["messages"][0]["content"])
        body["max_tokens"] = 16
        families.append(body)
    # Three families and two RR workers means each family visits both workers.
    return [{"family": family, "round": turn, "body": copy.deepcopy(body)}
            for turn in range(4) for family, body in enumerate(families)]


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
            "worker": record["worker"], "ttft_ms": record["ttft_ms"],
            "end_to_end_ms": record["end_to_end_ms"], "prompt_tokens": prompt,
            "cached_tokens": cached, "completion_tokens": usage.get("completion_tokens"),
            "prompt_ms": timings.get("prompt_ms"), "generation_ms": timings.get("predicted_ms"),
            "request_id": record.get("request_id"), "router_request_id": record.get("router_request_id")}


def summarize(rows):
    return {
        "requests": len(rows),
        "median_ttft_ms": statistics.median(r["ttft_ms"] for r in rows),
        "mean_ttft_ms": statistics.mean(r["ttft_ms"] for r in rows),
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


def run_policy(policy, trace, run_dir):
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
    for item in trace[:3]:
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
            print("request family worker cached/prompt TTFT(ms)", flush=True)
            for index, item in enumerate(trace):
                fixture = directory / f"request-{index:02d}.json"
                save(fixture, item["body"])
                result = subprocess.run([sys.executable, str(run_dir / "stream_once.py"), str(fixture),
                    "--url", "http://127.0.0.1:8010/v1/chat/completions"], capture_output=True, text=True, timeout=180)
                (directory / f"result-{index:02d}.json").write_text(result.stdout)
                (directory / f"result-{index:02d}.stderr").write_text(result.stderr)
                if result.returncode:
                    raise RuntimeError(f"Request {index} failed; see raw result")
                row = checked_row(json.loads(result.stdout), item, index)
                rows.append(row)
                with (directory / "requests.csv").open("w", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=list(row))
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"{index:7} {row['family']:6} {row['worker'][-4:]} "
                      f"{row['cached_tokens']:4}/{row['prompt_tokens']} {row['ttft_ms']:8.1f}", flush=True)
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
    args = parser.parse_args()
    # Never kill an existing user-run gateway or reset workers before this check.
    for port in (8010, 29010):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is occupied. Stop the manually launched SMG first.")
    template = json.loads((ROOT / "configs/long-prefix.json").read_text())
    trace = make_trace(template, args.seed)
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
         "warmup_requests": 0, "concurrency": 1, "retries": 0,
         "limitations": "Single exploratory run; synthetic labels distinguish shared warehouse text. No cache-capacity pressure, no concurrent queuing, CPU results only. Outputs are capped at 16 tokens and never fed back. SMG tie-breaking randomness is not seeded by this harness."})
    print(f"Saving comparison to {directory}", flush=True)
    summaries = {}
    try:
        for policy in policies:
            summaries[policy] = run_policy(policy, trace, directory)
        save(directory / "comparison.json", summaries)
        print("\npolicy       median TTFT   mean TTFT   reused prompt tokens")
        for policy, summary in summaries.items():
            print(f"{policy:12} {summary['median_ttft_ms']:10.1f}ms {summary['mean_ttft_ms']:9.1f}ms {summary['token_weighted_reuse']:19.1%}")
    except Exception as error:
        save(directory / "failure.json", {"error": str(error)})
        raise


if __name__ == "__main__":
    main()
