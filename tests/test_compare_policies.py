import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("compare", Path(__file__).resolve().parents[1] / "scripts/compare-policies.py")
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


class TraceTests(unittest.TestCase):
    def template(self):
        return {"messages": [{"role": "user", "content": "warehouse notes"}],
                "stream": True, "stream_options": {"include_usage": True}}

    def test_trace_is_reproducible_without_mutating_template(self):
        template = self.template()
        first = compare.make_trace(template, 7)
        self.assertEqual(first, compare.make_trace(template, 7))
        self.assertNotEqual(first, compare.make_trace(template, 8))
        self.assertEqual(template, self.template())

    def test_repeats_identical_families_and_round_robin_visits_both_workers(self):
        trace = compare.make_trace(self.template(), 7)
        self.assertEqual(len(trace), 12)
        self.assertEqual(len({r['body']['messages'][0]['content'] for r in trace}), 3)
        for family in range(3):
            requests = [r for r in trace if r['family'] == family]
            self.assertTrue(all(r['body'] == requests[0]['body'] for r in requests))
            self.assertEqual({i % 2 for i, r in enumerate(trace) if r['family'] == family}, {0, 1})

    def test_missing_cache_accounting_is_rejected(self):
        record = {'http_status': 200, 'done': True, 'worker': compare.WORKERS[0], 'ttft_ms': 1}
        with self.assertRaises(ValueError):
            compare.checked_row(record, {'body': {}}, 0)

    def test_weighted_reuse_not_mean_of_request_ratios(self):
        rows = [{'round': turn, 'worker': compare.WORKERS[0], 'ttft_ms': 1,
                 'prompt_tokens': prompt, 'cached_tokens': cached,
                 'prompt_ms': 1, 'generation_ms': 1}
                for turn, prompt, cached in [(0, 10, 0), (1, 90, 90)]]
        self.assertEqual(compare.summarize(rows)['token_weighted_reuse'], 0.9)
