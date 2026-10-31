"""Run five sequential first-use/repeat pairs; save every client result.

No worker reset: these are prefix-reuse probes, not fully cold-cache trials.
Each pair gets a unique leading label to avoid reusing an earlier pair's body.
The two requests within a pair are byte-identical. No concurrency or retries.
"""

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import uuid
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8001"


def post(path, payload):
    request = urllib.request.Request(
        BASE_URL + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def validate(record):
    """Fail closed instead of reporting incomplete requests as fast successes."""
    if record.get("http_status") != 200 or not record.get("done") or "error" in record:
        raise ValueError("Request failed or stream incomplete; inspect saved result")
    if record.get("ttft_ms") is None or record.get("cached_tokens") is None:
        raise ValueError("Missing TTFT or cache accounting; inspect saved result")
    usage = record.get("usage") or {}
    prompt = usage.get("prompt_tokens")
    cached = record["cached_tokens"]
    if not isinstance(prompt, int) or not 0 <= cached <= prompt:
        raise ValueError("Invalid prompt/cache accounting")
    timings = record.get("server_timings") or {}
    if timings.get("cache_n") != cached or timings.get("prompt_n") != prompt - cached:
        raise ValueError("Native worker accounting disagrees with usage")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--namespace", default=None,
                        help="Reuse a saved namespace to reconstruct exact prompts; cache may remain warm")
    args = parser.parse_args()
    if not 1 <= args.pairs <= 20:
        parser.error("--pairs must be between 1 and 20")
    namespace = args.namespace or uuid.uuid4().hex
    run_dir = ROOT / ".runs" / ("cache-pairs-" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True)
    print(f"Saving results to {run_dir}", flush=True)
    template = json.loads((ROOT / "configs/long-prefix.json").read_text())
    manifest = {
        "namespace": namespace, "pairs": args.pairs, "base_url": BASE_URL,
        "method": "unique leading label per pair; first-use then identical repeat; sequential",
        "cache_reset": False, "retries": 0,
        "limitations": "Exploratory fixed-order pairs; no causal isolation of CPU warmup or background load. Not cold-cache or router benchmarking.",
        "worker_image": json.loads((ROOT / "configs/worker-image.json").read_text()),
        "model": json.loads((ROOT / "configs/model.json").read_text()),
        "worker_launch_script": (ROOT / "scripts/start-worker.sh").read_text(),
        "configuration_note": "Recorded repository configuration, not live process attestation",
        "tokenized_prompt_counts": [],
    }
    # Snapshot the actual client used, alongside each exact request fixture.
    (run_dir / "stream_once.py").write_text((ROOT / "routerbench/stream_once.py").read_text())
    (run_dir / "repeat-cache.py").write_text(Path(__file__).read_text())
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    pairs = []
    print("pair  first cached  repeat cached  first TTFT  repeat TTFT  saved ms", flush=True)
    for index in range(1, args.pairs + 1):
        payload = json.loads(json.dumps(template))
        label = hashlib.sha256(f"{namespace}:{index}".encode()).hexdigest()[:16]
        payload["messages"][0]["content"] = (
            f"Experiment label {label}. Ignore this label when answering.\n\n"
            + template["messages"][0]["content"]
        )
        fixture = run_dir / f"pair-{index:02d}-request.json"
        fixture.write_text(json.dumps(payload, indent=2) + "\n")
        formatted = post("/apply-template", {"messages": payload["messages"], "add_generation_prompt": True})["prompt"]
        count = len(post("/tokenize", {"content": formatted, "add_special": True, "parse_special": True})["tokens"])
        manifest["tokenized_prompt_counts"].append(count)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        if count + payload["max_tokens"] > 4096:
            raise ValueError("Prompt plus output allowance exceeds configured context")
        records = []
        for phase in ("first", "repeat"):
            completed = subprocess.run(
                [sys.executable, str(run_dir / "stream_once.py"), str(fixture)],
                capture_output=True, text=True,
            )
            output = run_dir / f"pair-{index:02d}-{phase}.json"
            output.write_text(completed.stdout)
            (run_dir / f"pair-{index:02d}-{phase}.stderr.txt").write_text(completed.stderr)
            if completed.returncode:
                raise RuntimeError(f"Client failed; saved output at {output}")
            record = json.loads(completed.stdout)
            validate(record)
            records.append(record)
        first, repeat = records
        if first["request"] != repeat["request"]:
            raise ValueError("Pair inputs differ")
        saved = first["ttft_ms"] - repeat["ttft_ms"]
        pairs.append({"pair": index, "first_ttft_ms": first["ttft_ms"],
                      "repeat_ttft_ms": repeat["ttft_ms"], "saved_ms": saved,
                      "first_cached": first["cached_tokens"], "repeat_cached": repeat["cached_tokens"]})
        print(f"{index:4}  {first['cached_tokens']:12}  {repeat['cached_tokens']:13}  "
              f"{first['ttft_ms']:10.1f}  {repeat['ttft_ms']:11.1f}  {saved:8.1f}", flush=True)
        (run_dir / "pairs.json").write_text(json.dumps(pairs, indent=2) + "\n")
    summary = {
        "completed_pairs": len(pairs),
        "median_first_ttft_ms": statistics.median(p["first_ttft_ms"] for p in pairs),
        "median_repeat_ttft_ms": statistics.median(p["repeat_ttft_ms"] for p in pairs),
        "median_paired_saving_ms": statistics.median(p["saved_ms"] for p in pairs),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
