"""Measure one streamed request, using only Python's standard library.

This is a learning client, not yet a concurrent benchmark harness.
TTFT means first nonempty content chunk observed by this client.
"""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def read_stream(lines, started, clock=time.perf_counter):
    record = {
        "request_id": None,
        "ttft_ms": None,
        "content_chunk_times_ms": [],
        "text": "",
        "usage": None,
        "cached_tokens": None,
        "server_timings": None,
        "done": False,
    }
    # SSE events end at a blank line; an event may contain multiple data lines.
    data_lines = []
    for raw_line in lines:
        line = raw_line.decode("utf-8").rstrip("\r\n")
        if line:
            if line.startswith("data:"):
                data_lines.append(line[5:].removeprefix(" "))
            continue
        if not data_lines:
            continue
        data = "\n".join(data_lines)
        data_lines = []
        elapsed_ms = (clock() - started) * 1000
        if data == "[DONE]":
            record["done"] = True
            break
        event = json.loads(data)
        if "error" in event:
            record["error"] = event["error"]
            break
        record["request_id"] = event.get("id", record["request_id"])
        for choice in event.get("choices", []):
            content = choice.get("delta", {}).get("content")
            if isinstance(content, str) and content:
                if record["ttft_ms"] is None:
                    record["ttft_ms"] = elapsed_ms
                record["content_chunk_times_ms"].append(elapsed_ms)
                record["text"] += content
        if event.get("usage") is not None:
            record["usage"] = event["usage"]
            details = event["usage"].get("prompt_tokens_details") or {}
            record["cached_tokens"] = details.get("cached_tokens")
        if "timings" in event:
            record["server_timings"] = event["timings"]
    if not record["done"]:
        record.setdefault("error", "Stream ended before [DONE]")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8001/v1/chat/completions")
    args = parser.parse_args()
    payload = json.loads(args.request.read_text())
    payload["stream"] = True
    payload.setdefault("stream_options", {})["include_usage"] = True
    request = urllib.request.Request(
        args.url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    record = {"url": args.url, "request": payload, "http_status": None}
    # Prepare transport before starting the request timer.
    opener = urllib.request.build_opener(NoRedirect)
    # A monotonic clock measures durations without wall-clock adjustments.
    started = time.perf_counter()
    try:
        # No redirects or automatic retries: one measurement = one attempt.
        with opener.open(request, timeout=120) as response:
            record["http_status"] = response.status
            record["response_headers"] = dict(response.headers.items())
            record["worker"] = (
                response.headers.get("X-Router-Worker")
                or response.headers.get("X-Smg-Routed-Worker-Id")
            )
            record["router_request_id"] = (
                response.headers.get("X-Router-Request-Id")
                or response.headers.get("X-Request-Id")
            )
            record.update(read_stream(response, started))
    except urllib.error.HTTPError as error:
        record.update(http_status=error.code, error=str(error))
    except (OSError, ValueError) as error:
        record["error"] = str(error)
    record["end_to_end_ms"] = (time.perf_counter() - started) * 1000
    print(json.dumps(record, indent=2))
    raise SystemExit(1 if "error" in record else 0)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


if __name__ == "__main__":
    main()
