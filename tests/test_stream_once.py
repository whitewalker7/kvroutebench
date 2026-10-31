"""Offline checks: these never contact or warm the model worker."""

import json
import unittest

from routerbench.stream_once import read_stream


def event(payload):
    return [f"data: {json.dumps(payload)}\n".encode(), b"\n"]


class StreamTests(unittest.TestCase):
    def test_ttft_ignores_role_empty_and_heartbeat(self):
        lines = [b": heartbeat\n", b"\n"]
        lines += event({"choices": [{"delta": {"role": "assistant", "content": None}}]})
        lines += event({"choices": [{"delta": {"content": ""}}]})
        lines += event({"choices": [{"delta": {"content": "A"}}]})
        lines += event({"choices": [], "usage": {"prompt_tokens": 40,
                       "prompt_tokens_details": {"cached_tokens": 31}}})
        lines += [b"data: [DONE]\n", b"\n"]
        times = iter([10.01, 10.02, 10.25, 10.30, 10.31])
        result = read_stream(lines, 10.0, clock=lambda: next(times))
        self.assertAlmostEqual(result["ttft_ms"], 250)
        self.assertEqual(result["content_chunk_times_ms"], [250])
        self.assertEqual(result["cached_tokens"], 31)
        self.assertEqual(result["text"], "A")
        self.assertTrue(result["done"])

    def test_missing_cache_metric_is_not_zero(self):
        lines = event({"usage": {"prompt_tokens": 40}, "choices": []})
        lines += [b"data: [DONE]\n", b"\n"]
        result = read_stream(lines, 0, clock=lambda: 1)
        self.assertIsNone(result["cached_tokens"])
        self.assertIsNone(result["ttft_ms"])

    def test_truncated_stream_preserves_observed_content(self):
        lines = event({"choices": [{"delta": {"content": "A"}}]})
        result = read_stream(lines, 0, clock=lambda: 1)
        self.assertFalse(result["done"])
        self.assertIn("error", result)
        self.assertEqual(result["text"], "A")

    def test_server_error_is_failure(self):
        result = read_stream(event({"error": "failed"}), 0, clock=lambda: 1)
        self.assertEqual(result["error"], "failed")
        self.assertFalse(result["done"])


if __name__ == "__main__":
    unittest.main()
