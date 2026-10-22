"""Counterexamples for the portable validation policy, not relaxed green checks."""
import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import validation_portability as policy
from entrysignallab import ModelParams, DecisionBounds, optimize, compare


class PortabilityContract(unittest.TestCase):
    def setUp(self):
        self.p = ModelParams(announcement_cost=.0002, deployment_cost=.012, learning_rate=12)
        self.b = DecisionBounds(delay_lower=.1, delay_upper=.1)
        self.result = optimize(self.p, 'RL', self.b, .15)

    def test_roundoff_is_allowed_but_sign_and_zero_are_not(self):
        self.assertTrue(policy.finite_close(1., math.nextafter(1., 2.)))
        for a, b in [(0., 5e-324), (-5e-324, 5e-324), (1., 1.01), (math.inf, math.inf)]:
            self.assertFalse(policy.finite_close(a, b))

    def test_discrete_states_are_exact(self):
        with patch.object(policy, 'STRICT_REPLAY', False):
            for a, b in [(True, 1), ('RL', 'RF'), (None, 0.), (1, 1.)]:
                self.assertFalse(policy.frozen_matches(a, b))

    def test_strict_replay_retains_last_bit_assertion(self):
        with patch.object(policy, 'STRICT_REPLAY', True):
            self.assertFalse(policy.frozen_matches({'payoff': math.nextafter(1., 2.)}, {'payoff': 1.}))
            self.assertFalse(policy.frozen_matches({'evaluations': 4}, {'evaluations': 5}))

    def test_independent_objective_rejects_corrupted_payoff_even_in_both_snapshots(self):
        actual = copy.deepcopy(self.result)
        actual['payoff'] *= 1.01
        self.assertFalse(policy.result_matches(self.p, self.b, .15, actual, actual))

    def test_configured_domain_cannot_be_waived_by_matching_snapshots(self):
        actual = copy.deepcopy(self.result)
        actual['delay'] = .2
        self.assertFalse(policy.result_matches(self.p, self.b, .15, actual, actual))

    def test_actual_current_controls_have_an_independent_payoff(self):
        self.assertTrue(policy.result_matches(self.p, self.b, .15, self.result, self.result))

    def test_wrong_winner_is_rejected(self):
        report = compare(self.p, self.b, .15)
        report['co_best'] = ['DF'] if report['co_best'] != ['DF'] else ['RL']
        self.assertFalse(policy.comparison_evidence_valid(self.p, report))

    def test_diagnostic_order_is_incidental_but_diagnostic_sign_is_checked(self):
        p = ModelParams(growth=0)
        report = compare(p, self.b, .15)
        report['comparison_precision']['refined_comparisons'].reverse()
        self.assertTrue(policy.comparison_evidence_valid(p, report))
        record = report['comparison_precision']['refined_comparisons'][0]
        record['sign'] = 1
        self.assertFalse(policy.comparison_evidence_valid(p, report))

    def test_lock_inventory_uses_metadata_without_opening_active_lock_bytes(self):
        from test_v0100_audit import inventory
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock = root/'.child.entrysignal.lock'
            lock.write_bytes(b'\0')
            data = root/'data.json'
            data.write_bytes(b'original')
            original = Path.read_bytes
            def guarded(path):
                if path == lock:
                    raise PermissionError('simulated Windows byte-range lock')
                return original(path)
            with patch.object(Path, 'read_bytes', guarded):
                before = inventory(root)
                data.write_bytes(b'changed')
                self.assertNotEqual(before, inventory(root))
                self.assertIn(lock.name, before)

    def test_comparison_amount_corruption_is_not_hidden_by_correct_sign(self):
        report = compare(ModelParams(growth=0), self.b, .15)
        record = report['comparison_precision']['refined_comparisons'][0]
        record['value'] = 123.
        self.assertFalse(policy.comparison_evidence_valid(ModelParams(growth=0), report))


if __name__ == '__main__':
    unittest.main()
