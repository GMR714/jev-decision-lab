from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from engines import ENGINES, JEV_MODEL, classify


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=ENGINES, required=True)
    parser.add_argument('--split', choices=('validation', 'test', 'all'), default='test')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--cases', type=Path, default=Path('data/cases.jsonl'))
    parser.add_argument('--out', type=Path, default=Path('results'))
    parser.add_argument('--gate-thresholds', type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.cases.read_text(encoding='utf-8').splitlines() if line]
    rows = [row for row in rows if args.split == 'all' or row['split'] == args.split]
    if args.limit is not None:
        rows = rows[:args.limit]
    if args.engine in ('jev', 'jev_gate') and not os.environ.get('TYPESAFE_API_KEY'):
        parser.error('Set TYPESAFE_API_KEY locally before requesting a real Jev run')
    gate_thresholds = None
    threshold_sha256 = None
    if args.engine == 'jev_gate':
        if not args.gate_thresholds:
            parser.error('jev_gate requires --gate-thresholds from validation calibration')
        raw_thresholds = args.gate_thresholds.read_bytes()
        gate_thresholds = json.loads(raw_thresholds)
        if gate_thresholds.get('model') != JEV_MODEL or gate_thresholds.get('validation_cases') != 8:
            parser.error('Invalid Jev gate calibration file')
        route_min = gate_thresholds.get('route_min_probability')
        margin = gate_thresholds.get('review_endpoint_margin')
        if type(gate_thresholds.get('auto_enabled')) is not bool or any(
            type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper
            for value, lower, upper in ((route_min, 0, 1), (margin, 0, 0.5))
        ):
            parser.error('Invalid Jev gate thresholds')
        threshold_sha256 = hashlib.sha256(raw_thresholds).hexdigest()
    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / f'{args.engine}-{args.split}.jsonl'
    with output.open('w', encoding='utf-8') as stream:
        for index, row in enumerate(rows, 1):
            try:
                prediction = classify(args.engine, row['message'], gate_thresholds)
                result = {
                    'id': row['id'], 'sha256': row['sha256'], 'split': row['split'],
                    'language': row['language'], 'scenario': row['scenario'],
                    'expected': {'route': row['route'], 'review': row['review']},
                    'gate_thresholds_sha256': threshold_sha256,
                    'prediction': prediction, 'run_at': datetime.now(timezone.utc).isoformat(),
                }
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
                result = {
                    'id': row['id'], 'sha256': row['sha256'], 'split': row['split'],
                    'language': row['language'], 'scenario': row['scenario'],
                    'expected': {'route': row['route'], 'review': row['review']},
                    'gate_thresholds_sha256': threshold_sha256,
                    'error': type(error).__name__ + ': ' + str(error),
                    'run_at': datetime.now(timezone.utc).isoformat(),
                }
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
            stream.flush()
            print(f'{index}/{len(rows)} {row["id"]} {"error" if "error" in result else "ok"}', flush=True)
    print(output)


if __name__ == '__main__':
    main()
