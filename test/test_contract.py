from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from cases import build
from calibrate import calibrate
from engines import jev, jev_gate
from report import summarize


class DecisionContractTest(unittest.TestCase):
    def test_case_families_do_not_cross_splits(self) -> None:
        rows = build()
        families = {split: {r['family_id'] for r in rows if r['split'] == split} for split in ('test', 'validation')}
        self.assertFalse(families['test'] & families['validation'])
        self.assertEqual(len(rows), 32)
        self.assertEqual(sum(row['split'] == 'validation' for row in rows), 8)
        for family_id in families['test'] | families['validation']:
            pair = [row for row in rows if row['family_id'] == family_id]
            self.assertEqual({row['language'] for row in pair}, {'pt', 'en'})

    @patch.dict(os.environ, {'TYPESAFE_API_KEY': 'local-test-key'})
    @patch('engines._post')
    def test_jev_request_and_response(self, post) -> None:
        post.return_value = {
            'model': 'jev-1.13.0',
            'answers': {
                'route': {'type': 'choice', 'choice': 'billing', 'probabilities': {
                    'delivery': 0.02, 'billing': 0.91, 'technical': 0.02, 'manual': 0.05,
                }, 'confidence': 0.85},
                'review': {'type': 'noul', 'noul': 0.7},
            },
            'usage': {'input_tokens': 300, 'output_tokens': 32},
        }
        result = jev('Duplicate invoice')
        self.assertEqual(result['route'], 'billing')
        self.assertTrue(result['review'])
        self.assertEqual(result['review_probability'], 0.7)
        payload = post.call_args.args[1]
        self.assertEqual(payload['model'], 'jev-1.13.0')
        self.assertEqual(set(payload['questions']), {'route', 'review'})

    @patch('engines.ollama')
    @patch('engines.jev')
    def test_gate_falls_back_on_uncertain_route(self, decision, fallback) -> None:
        decision.return_value = {'route': 'manual', 'review': True, 'route_probs': {'manual': 0.55},
                                 'review_probability': 0.6, 'route_confidence': 0.55, 'model': 'jev-1.13.0',
                                 'input_tokens': 100, 'output_tokens': 10}
        fallback.return_value = {'route': 'billing', 'review': True, 'model': 'qwen3:1.7b',
                                 'input_tokens': 80, 'output_tokens': 12}
        result = jev_gate('Something is wrong')
        self.assertEqual(result['path'], 'jev_to_ollama')
        self.assertEqual(result['input_tokens'], 180)

    @patch('engines.ollama')
    @patch('engines.jev')
    def test_gate_keeps_confident_jev_result(self, decision, fallback) -> None:
        decision.return_value = {'route': 'billing', 'review': False, 'route_probs': {'billing': 0.9},
                                 'review_probability': 0.1, 'model': 'jev-1.13.0',
                                 'input_tokens': 100, 'output_tokens': 10}
        result = jev_gate('Invoice copy')
        self.assertEqual(result['path'], 'jev')
        self.assertEqual(result['jev_input_tokens'], 100)
        fallback.assert_not_called()

    @patch.dict(os.environ, {'TYPESAFE_API_KEY': 'local-test-key'})
    @patch('engines._post')
    def test_jev_rejects_unexpected_model_version(self, post) -> None:
        post.return_value = {'model': 'jev-latest'}
        with self.assertRaisesRegex(ValueError, 'model version'):
            jev('Invoice copy')

    def test_calibration_accepts_only_correct_confident_cases(self) -> None:
        rows = []
        for index, (probability, review_probability, expected) in enumerate(((0.94, 0.05, 'billing'), (0.92, 0.95, 'billing'), (0.55, 0.5, 'manual')), 1):
            rows.append({'id': str(index), 'split': 'validation',
                         'expected': {'route': expected, 'review': review_probability > 0.5},
                         'prediction': {'model': 'jev-1.13.0', 'route': 'billing',
                                        'route_probs': {'delivery': 0.02, 'billing': probability, 'technical': 0.02, 'manual': 0.96 - probability},
                                        'review': review_probability > 0.5, 'review_probability': review_probability}})
        result = calibrate(rows)
        self.assertTrue(result['auto_enabled'])
        self.assertEqual(result['accepted_validation_cases'], 2)
        self.assertEqual(result['accepted_joint_accuracy'], 1.0)

    def test_calibration_disables_auto_when_confident_errors_remain(self) -> None:
        rows = [
            {'id': str(index), 'split': 'validation', 'expected': {'route': 'manual', 'review': False},
             'prediction': {'model': 'jev-1.13.0', 'route': 'billing', 'review': False,
                            'route_probs': {'delivery': 0.02, 'billing': 0.94, 'technical': 0.02, 'manual': 0.02},
                            'review_probability': 0.05}}
            for index in range(2)
        ]
        self.assertFalse(calibrate(rows)['auto_enabled'])

    def test_report_does_not_count_errors_as_correct(self) -> None:
        rows = [{'id': '1', 'error': 'Timeout'}, {
            'expected': {'route': 'billing', 'review': True},
            'prediction': {'route': 'billing', 'review': True, 'review_probability': 0.8,
                           'elapsed_ms': 10, 'input_tokens': 100, 'output_tokens': 10},
            'language': 'en',
        }]
        result = summarize(rows)
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['route_accuracy'], 1.0)
        self.assertEqual(result['route_accuracy_all_cases'], 0.5)
        self.assertEqual(result['joint_accuracy_all_cases'], 0.5)
        self.assertEqual(result['review_brier_cases'], 1)
        self.assertEqual(result['completion_rate'], 0.5)
        self.assertAlmostEqual(result['review_brier'], 0.04)


if __name__ == '__main__':
    unittest.main()
