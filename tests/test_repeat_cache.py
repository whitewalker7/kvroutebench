import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "repeat_cache", Path(__file__).resolve().parents[1] / "scripts/repeat-cache.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class AccountingTests(unittest.TestCase):
    def record(self):
        return {"http_status": 200, "done": True, "ttft_ms": 0.5,
                "cached_tokens": 24, "usage": {"prompt_tokens": 567},
                "server_timings": {"cache_n": 24, "prompt_n": 543}}

    def test_consistent_accounting(self):
        runner.validate(self.record())

    def test_missing_cache_is_not_zero(self):
        record = self.record()
        record["cached_tokens"] = None
        with self.assertRaises(ValueError):
            runner.validate(record)

    def test_inconsistent_native_accounting_is_rejected(self):
        record = self.record()
        record["server_timings"]["prompt_n"] = 567
        with self.assertRaises(ValueError):
            runner.validate(record)

    def test_failed_request_cannot_count_as_fast_success(self):
        record = self.record()
        record["done"] = False
        with self.assertRaises(ValueError):
            runner.validate(record)
