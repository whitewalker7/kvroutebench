import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('export_demo', ROOT / 'scripts/export-demo.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportTests(unittest.TestCase):
    def test_original_evidence_exports_without_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'demo'
            result = exporter.export(ROOT / 'demo/evidence', destination)
            self.assertEqual(len(result['policies']['round_robin']['rows']), 12)
            self.assertAlmostEqual(result['policies']['cache_aware']['summary']['mean_ttft_ms'], 437.11173724902136)
            self.assertTrue((destination / 'evidence/round_robin/result-00.json').exists())

    def test_incompatible_workloads_rejected_before_copy(self):
        baseline = ROOT / 'demo/evidence'
        for change in ({'concurrency': 3}, {'reuse': 'unique'}, {'answer_length': 'long'}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / 'source'
                source.mkdir()
                manifest = json.loads((baseline / 'manifest.json').read_text())
                manifest.update(change)
                (source / 'manifest.json').write_text(json.dumps(manifest))
                (source / 'trace.json').write_bytes((baseline / 'trace.json').read_bytes())
                destination = Path(folder) / 'demo'
                with self.assertRaisesRegex(ValueError, 'Browser demo describes'):
                    exporter.export(source, destination)
                self.assertFalse(destination.exists())
