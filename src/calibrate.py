from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from engines import JEV_MODEL, ROUTES


def calibrate(rows: list[dict], min_joint_accuracy: float = 1.0, min_accepted: int = 2) -> dict:
    if not math.isfinite(min_joint_accuracy) or not 0 < min_joint_accuracy <= 1 or min_accepted < 1:
        raise ValueError('Invalid calibration objective')
    if not rows or any(row.get('split') != 'validation' or 'prediction' not in row for row in rows):
        raise ValueError('Calibration requires completed validation cases only')
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Duplicate validation case IDs')
    for row in rows:
        prediction = row['prediction']
        if prediction.get('model') != JEV_MODEL or set(prediction.get('route_probs', {})) != set(ROUTES):
            raise ValueError('Calibration requires real pinned Jev probabilities')
        probabilities = prediction['route_probs']
        review_probability = prediction.get('review_probability')
        if prediction.get('route') not in ROUTES or type(prediction.get('review')) is not bool:
            raise ValueError('Invalid Jev decisions')
        if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities.values()) or abs(sum(probabilities.values()) - 1) > 0.02:
            raise ValueError('Invalid Jev route probabilities')
        if type(review_probability) not in (int, float) or not math.isfinite(review_probability) or not 0 <= review_probability <= 1:
            raise ValueError('Invalid Jev review probability')

    candidates = []
    for route_min in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        for margin in (0.1, 0.2, 0.3, 0.4):
            accepted = [
                row for row in rows
                if row['prediction']['route_probs'][row['prediction']['route']] >= route_min
                and (row['prediction']['review_probability'] <= margin or row['prediction']['review_probability'] >= 1 - margin)
            ]
            if len(accepted) < min_accepted:
                continue
            correct = sum(
                row['prediction']['route'] == row['expected']['route']
                and row['prediction']['review'] == row['expected']['review']
                for row in accepted
            )
            joint_accuracy = correct / len(accepted)
            if joint_accuracy >= min_joint_accuracy:
                candidates.append((len(accepted), route_min, -margin, joint_accuracy))

    if not candidates:
        return {
            'auto_enabled': False, 'route_min_probability': 0.8, 'review_endpoint_margin': 0.2,
            'validation_cases': len(rows), 'accepted_validation_cases': 0,
            'accepted_joint_accuracy': None, 'min_joint_accuracy': min_joint_accuracy,
        }
    count, route_min, negative_margin, joint_accuracy = max(candidates)
    return {
        'auto_enabled': True, 'route_min_probability': route_min,
        'review_endpoint_margin': -negative_margin, 'validation_cases': len(rows),
        'accepted_validation_cases': count, 'accepted_joint_accuracy': round(joint_accuracy, 4),
        'min_joint_accuracy': min_joint_accuracy,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('validation_run', type=Path)
    parser.add_argument('--out', type=Path, default=Path('results/gate-thresholds.json'))
    parser.add_argument('--min-joint-accuracy', type=float, default=1.0)
    args = parser.parse_args()
    raw = args.validation_run.read_bytes()
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if len(rows) != 8:
        parser.error(f'Expected eight validation cases, found {len(rows)}')
    result = calibrate(rows, args.min_joint_accuracy)
    result['validation_run_sha256'] = hashlib.sha256(raw).hexdigest()
    result['model'] = JEV_MODEL
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
