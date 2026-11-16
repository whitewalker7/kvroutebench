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

    def test_long_answers_change_instruction_and_keep_repeats_identical(self):
        template = self.template()
        template['messages'][0]['content'] = 'After the notes, answer the final question in one short sentence.'
        before = compare.copy.deepcopy(template)
        trace = compare.make_trace(template, 7, 'long')
        self.assertEqual(template, before)
        for item in trace:
            self.assertEqual(item['body']['max_tokens'], 128)
            self.assertNotIn('one short sentence', item['body']['messages'][0]['content'])
            self.assertIn('detailed explanation', item['body']['messages'][0]['content'])
            self.assertEqual(item['body'], trace[item['family']]['body'])
        short = compare.make_trace(template, 7)
        self.assertTrue(all(r['body']['max_tokens'] == 16 for r in short))

    def test_long_answers_reject_unexpected_template(self):
        with self.assertRaisesRegex(ValueError, 'expected short-answer instruction'):
            compare.make_trace(self.template(), 7, 'long')

    def test_unique_control_changes_only_leading_labels_and_is_reproducible(self):
        template = self.template()
        repeated = compare.make_trace(template, 7)
        unique = compare.make_trace(template, 7, reuse='unique')
        self.assertEqual(unique, compare.make_trace(template, 7, reuse='unique'))
        self.assertNotEqual(unique, compare.make_trace(template, 8, reuse='unique'))
        self.assertEqual(len({r['body']['messages'][0]['content'] for r in unique}), 12)
        self.assertEqual([r['prefix_label'] for r in unique][:6], ['A1','B1','C1','A2','B2','C2'])
        for i, (old, new) in enumerate(zip(repeated, unique)):
            old_body, new_body = compare.copy.deepcopy(old['body']), compare.copy.deepcopy(new['body'])
            for body in (old_body, new_body):
                body['messages'][0]['content'] = body['messages'][0]['content'].split('\n\n', 1)[1]
            self.assertEqual(old_body, new_body)
            self.assertEqual((old['family'], old['round']), (new['family'], new['round']))
            if i < 3:
                self.assertEqual(old['body'], new['body'])
        self.assertEqual(template, self.template())

    def test_unique_control_rejects_unknown_reuse(self):
        with self.assertRaisesRegex(ValueError, 'reuse must'):
            compare.make_trace(self.template(), 7, reuse='off')

    def test_missing_cache_accounting_is_rejected(self):
        record = {'http_status': 200, 'done': True, 'worker': compare.WORKERS[0], 'ttft_ms': 1}
        with self.assertRaises(ValueError):
            compare.checked_row(record, {'body': {}}, 0)

    def test_weighted_reuse_not_mean_of_request_ratios(self):
        rows = [{'round': turn, 'worker': compare.WORKERS[0], 'ttft_ms': 1,
                 'prompt_tokens': prompt, 'cached_tokens': cached,
                 'prompt_ms': 1, 'generation_ms': 1, 'end_to_end_ms': 10 + turn * 10}
                for turn, prompt, cached in [(0, 10, 0), (1, 90, 90)]]
        summary = compare.summarize(rows)
        self.assertEqual(summary['token_weighted_reuse'], 0.9)
        self.assertEqual(summary['mean_end_to_end_ms'], 15)
        self.assertEqual(summary['mean_ttft_ms'], 1)


class BurstTests(unittest.TestCase):
    def test_three_requests_overlap_and_bursts_do_not_overlap(self):
        import threading
        lock = threading.Lock()
        barrier = threading.Barrier(3, timeout=3)
        completed = set()
        active = 0
        peak = 0

        def send(index, item):
            nonlocal active, peak
            with lock:
                if index >= 3:
                    self.assertTrue({0, 1, 2}.issubset(completed))
                active += 1
                peak = max(peak, active)
            barrier.wait()
            with lock:
                completed.add(index)
                active -= 1
            return index

        self.assertEqual(sorted(compare.run_batches(list(range(6)), 3, send)), list(range(6)))
        self.assertEqual(peak, 3)

    def test_sequential_mode_preserves_trace_order(self):
        seen = []
        def send(index, item):
            seen.append(index)
            return item
        self.assertEqual(list(compare.run_batches(['A', 'B', 'C'], 1, send)), ['A', 'B', 'C'])
        self.assertEqual(seen, [0, 1, 2])

    def test_failure_stops_future_bursts(self):
        seen = []
        def send(index, item):
            seen.append(index)
            raise ValueError('failed request')
        with self.assertRaisesRegex(ValueError, 'failed request'):
            list(compare.run_batches([0, 1], 1, send))
        self.assertEqual(seen, [0])
