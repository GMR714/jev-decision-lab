from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from engines import ROUTES


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return round(values[low] + (values[high] - values[low]) * (position - low), 2)


def macro_f1(rows: list[dict]) -> float | None:
    if not rows:
        return None
    scores = []
    for label in ROUTES:
        true_positive = sum(r['expected']['route'] == label and r['prediction']['route'] == label for r in rows)
        false_positive = sum(r['expected']['route'] != label and r['prediction']['route'] == label for r in rows)
        false_negative = sum(r['expected']['route'] == label and r['prediction']['route'] != label for r in rows)
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(2 * true_positive / denominator if denominator else 0)
    return round(statistics.mean(scores), 4)


def accuracy(rows: list[dict], field: str) -> float | None:
    return round(sum(r['expected'][field] == r['prediction'][field] for r in rows) / len(rows), 4) if rows else None


def summarize(rows: list[dict]) -> dict:
    valid = [row for row in rows if 'prediction' in row]
    review_probabilities = [r for r in valid if r['prediction'].get('review_probability') is not None]
    route_probabilities = [r for r in valid if r['prediction'].get('route_probs') is not None]
    paths = sorted({row['prediction']['path'] for row in valid if 'path' in row['prediction']})
    languages = sorted({row['language'] for row in rows if 'language' in row})
    return {
        'cases': len(rows), 'completed': len(valid), 'errors': len(rows) - len(valid),
        'completion_rate': round(len(valid) / len(rows), 4) if rows else None,
        'route_accuracy': accuracy(valid, 'route'),
        'review_accuracy': accuracy(valid, 'review'),
        'joint_accuracy': round(sum(r['expected']['route'] == r['prediction']['route'] and r['expected']['review'] == r['prediction']['review'] for r in valid) / len(valid), 4) if valid else None,
        'joint_accuracy_all_cases': round(sum(r['expected']['route'] == r['prediction']['route'] and r['expected']['review'] == r['prediction']['review'] for r in valid) / len(rows), 4) if rows else None,
        'route_accuracy_all_cases': round(sum(r['expected']['route'] == r['prediction']['route'] for r in valid) / len(rows), 4) if rows else None,
        'review_accuracy_all_cases': round(sum(r['expected']['review'] == r['prediction']['review'] for r in valid) / len(rows), 4) if rows else None,
        'route_macro_f1': macro_f1(valid),
        'review_brier': round(statistics.mean((r['prediction']['review_probability'] - int(r['expected']['review'])) ** 2 for r in review_probabilities), 4) if review_probabilities else None,
        'review_brier_cases': len(review_probabilities),
        'route_brier_cases': len(route_probabilities),
        'route_brier': round(statistics.mean(sum((r['prediction']['route_probs'][label] - int(r['expected']['route'] == label)) ** 2 for label in ROUTES) for r in route_probabilities), 4) if route_probabilities else None,
        'latency_p50_ms': percentile([r['prediction']['elapsed_ms'] for r in valid], 0.5),
        'latency_p95_ms': percentile([r['prediction']['elapsed_ms'] for r in valid], 0.95),
        'input_tokens': sum(r['prediction'].get('input_tokens', 0) for r in valid),
        'output_tokens': sum(r['prediction'].get('output_tokens', 0) for r in valid),
        'jev_input_tokens': sum(r['prediction'].get('jev_input_tokens', 0) for r in valid),
        'jev_output_tokens': sum(r['prediction'].get('jev_output_tokens', 0) for r in valid),
        'by_language': {
            language: {
                'cases': len(group), 'completed': len(done),
                'route_accuracy': accuracy(done, 'route'),
                'review_accuracy': accuracy(done, 'review'),
            }
            for language in languages
            if (group := [r for r in rows if r.get('language') == language])
            if (done := [r for r in group if 'prediction' in r]) or group
        },
        'by_path': {
            path: {
                'cases': len(group), 'route_accuracy': accuracy(group, 'route'),
                'review_accuracy': accuracy(group, 'review'),
                'joint_accuracy': round(sum(r['expected']['route'] == r['prediction']['route'] and r['expected']['review'] == r['prediction']['review'] for r in group) / len(group), 4),
                'latency_p50_ms': percentile([r['prediction']['elapsed_ms'] for r in group], 0.5),
            }
            for path in paths
            if (group := [r for r in valid if r['prediction'].get('path') == path])
        },
        'confusion': dict(Counter(f'{r["expected"]["route"]}->{r["prediction"]["route"]}' for r in valid)),
        'error_types': dict(Counter(r['error'].split(':', 1)[0] for r in rows if 'error' in r)),
    }


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def validate_comparable(runs: dict[str, list[dict]]) -> None:
    if len(runs) < 2:
        return
    first = next(iter(runs.values()))
    reference = {row['id']: (row['sha256'], row['expected']) for row in first}
    if len(reference) != len(first):
        raise ValueError('Duplicate case IDs in reference run')
    for name, rows in runs.items():
        indexed = {row['id']: (row['sha256'], row['expected']) for row in rows}
        if len(indexed) != len(rows) or indexed != reference:
            raise ValueError(f'Case hash or expected label mismatch: {name}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--jev-input-usd-per-million', type=float)
    args = parser.parse_args()
    runs = {path.stem: read_rows(path) for path in args.files}
    validate_comparable(runs)
    report = {name: summarize(rows) for name, rows in runs.items()}
    if args.jev_input_usd_per_million is not None:
        if not math.isfinite(args.jev_input_usd_per_million) or args.jev_input_usd_per_million < 0:
            parser.error('Jev input price must be a nonnegative finite number')
        for metrics in report.values():
            metrics['jev_input_usd_per_million'] = args.jev_input_usd_per_million
            metrics['jev_input_cost_usd_estimate'] = round(metrics['jev_input_tokens'] * args.jev_input_usd_per_million / 1_000_000, 8)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
