"""Export a completed comparison into the static demo; never runs inference."""
import argparse
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('comparison', ROOT / 'scripts/compare-policies.py')
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def export(source, destination):
    manifest = json.loads((source / 'manifest.json').read_text())
    trace = json.loads((source / 'trace.json').read_text())
    policies = {}
    for policy in ('round_robin', 'cache_aware'):
        rows = []
        for index, item in enumerate(trace):
            raw = json.loads((source / policy / f'result-{index:02d}.json').read_text())
            row = comparison.checked_row(raw, item, index)
            row['raw_url'] = f'evidence/{policy}/result-{index:02d}.json'
            rows.append(row)
        policies[policy] = {'rows': rows, 'summary': comparison.summarize(rows)}
    # Copy only this experiment's evidence, never the whole workspace or .runs.
    evidence = destination / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ('manifest.json', 'trace.json', 'comparison.json', 'stream_once.py',
                 'compare-policies.py', 'start-smg.sh'):
        shutil.copyfile(source / name, evidence / name)
    for policy in policies:
        folder = evidence / policy
        folder.mkdir(exist_ok=True)
        for pattern in ('result-*.json', 'request-*.json', 'requests.csv', 'workers.json',
                        'registration.json', 'token_counts.json', 'summary.json'):
            for path in (source / policy).glob(pattern):
                shutil.copyfile(path, folder / path.name)
    bundle = {'run_id': source.name, 'manifest': manifest, 'policies': policies,
              'note': 'Saved experiment replay. Animation is illustrative; measured times are shown numerically.'}
    (destination / 'data.json').write_text(json.dumps(bundle, indent=2) + '\n')
    return bundle


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    bundle = export(args.run, ROOT / 'demo')
    print(f"Exported {bundle['run_id']}: {sum(len(p['rows']) for p in bundle['policies'].values())} validated requests")
