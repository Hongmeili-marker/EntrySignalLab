"""Regression coverage for the four v0.13.0 audit findings."""
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import math
import subprocess
import sys
import unittest
import numpy as np
from entrysignallab import ModelParams, DecisionBounds, compare, optimize, payoff
from entrysignallab.model import finite_float_text
from entrysignallab.research import ResearchKernel, ModelCapabilities, default_research_kernel, optimize_research
from entrysignallab.workflow import configured_feasibility, write_json, read_json, load_config, prepare_sweep, execute_case
from entrysignallab.plots import resolve_plot_settings
from entrysignallab.batch import CheckpointStore, _export_csv


class V0140Audit(unittest.TestCase):
    def setUp(self):
        self.p = ModelParams()
        self.b = DecisionBounds()

    def candidate(self, p=None, strategy='DL', delay=.125, intensity=0., value=None, **options):
        p = self.p if p is None else p
        result = {'strategy': strategy, 'delay': delay, 'announcement': intensity,
                  'payoff': payoff(p, strategy, delay, intensity) if value is None else value}
        result.update(options)
        return result

    def research(self, result, p=None, b=None, **kernel_options):
        kernel = replace(default_research_kernel(), conditional_solver=lambda *a: dict(result), **kernel_options)
        return optimize_research(kernel, self.p if p is None else p, result['strategy'], self.b if b is None else b, .125)

    def test_A01_fraction_follower_singleton(self):
        b = replace(self.b, delay_lower=.1, delay_upper=.1)
        self.assertTrue(configured_feasibility(self.p, b, .15, 'DL', Fraction(1, 10), 0)['within_configured_bounds'])

    def test_A01_fraction_RF_fixed(self):
        self.assertTrue(configured_feasibility(self.p, self.b, .1, 'RF', Fraction(1, 10), 0)['within_configured_bounds'])

    def test_A01_fraction_DF_fixed(self):
        self.assertTrue(configured_feasibility(self.p, self.b, .1, 'DF', Fraction(1, 10), 0)['within_configured_bounds'])

    def test_A01_fraction_RL_singleton(self):
        b = replace(self.b, delay_lower=.1, delay_upper=.1)
        self.assertTrue(configured_feasibility(self.p, b, .15, 'RL', Fraction(1, 10), Fraction(3, 10))['within_configured_bounds'])

    def test_A01_fraction_cap(self):
        self.assertTrue(configured_feasibility(self.p, replace(self.b, announcement_upper=.3), .15, 'RL', .1, Fraction(3, 10))['within_configured_bounds'])

    def test_A01_actual_violation_retained(self):
        result = configured_feasibility(self.p, replace(self.b, delay_upper=.1), .15, 'DL', .1001, 0)
        self.assertFalse(result['within_configured_bounds'])
        self.assertEqual(result['bound_violations'][0]['actual'], .1001)

    def test_A01_numpy_reals(self):
        self.assertTrue(configured_feasibility(self.p, self.b, np.float32(.125), 'RF', np.float32(.125), np.int64(0))['within_configured_bounds'])

    def test_A01_invalid_controls(self):
        for value in [True, complex(.1), float('inf'), Fraction(-1, 10), Fraction(1, 10**500)]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                configured_feasibility(self.p, self.b, .15, 'DL', value, 0)

    def test_A01_plot_fraction_controls(self):
        b = replace(self.b, delay_lower=.1, delay_upper=.1, announcement_upper=.3)
        result = resolve_plot_settings(self.p, b, Fraction(1, 10),
                                       {'delay': Fraction(1, 10), 'announcement': Fraction(3, 10), 'surface_announcement_max': Fraction(3, 10)})
        self.assertEqual(result['trajectory_controls']['RL'], {'delay': .1, 'announcement': .3})
        json.dumps(result, allow_nan=False)

    def test_A01_plot_rejects_invalid_rival(self):
        with self.assertRaises(ValueError):
            resolve_plot_settings(self.p, self.b, self.p.horizon)

    def test_A02_small_false_zero(self):
        p = replace(self.p, margin_x=1e-280, deployment_cost=1e-280)
        with self.assertRaisesRegex(ValueError, 'payoff disagrees'):
            self.research(self.candidate(p=p, value=0.), p=p)

    def test_A02_small_false_positive(self):
        p = replace(self.p, margin_x=1e-280, deployment_cost=1e-280)
        with self.assertRaises(ValueError):
            self.research(self.candidate(p=p, value=1e-11), p=p)

    def test_A02_small_false_negative_scale(self):
        p = replace(self.p, margin_x=1e-280, deployment_cost=1e-280)
        with self.assertRaises(ValueError):
            self.research(self.candidate(p=p, value=-1e-11), p=p)

    def test_A02_no_false_entry_through_compare(self):
        p = replace(self.p, margin_x=1e-280, deployment_cost=1e-280)
        def solver(p, st, b, rival):
            r = optimize(p, st, b, rival)
            return {**r, 'payoff': 1e-11} if st == 'RF' else r
        kernel = replace(default_research_kernel(), conditional_solver=solver)
        self.assertEqual(compare(p, tie_tolerance=0)['preferred_with_outside_option'], ['no_entry'])
        with self.assertRaises(ValueError):
            compare(p, tie_tolerance=0, optimizer=lambda p, st, b, r: optimize_research(kernel, p, st, b, r))

    def test_A02_correct_small_negative(self):
        p = replace(self.p, margin_x=1e-280, deployment_cost=1e-280)
        r = self.candidate(p=p)
        self.assertEqual(self.research(r, p=p)['payoff'], r['payoff'])

    def test_A02_correct_small_positive(self):
        p = replace(self.p, margin_x=1e-280)
        r = self.candidate(p=p)
        self.assertGreater(self.research(r, p=p)['payoff'], 0)

    def toy(self, reference, reported, **options):
        result = {'strategy': 'toy', 'delay': -1., 'announcement': -2., 'payoff': reported}
        kernel = ResearchKernel(ModelCapabilities('toy', '1', False, False), lambda *a: reference,
                                lambda *a: None, lambda *a: None, lambda *a: dict(result), lambda *a: True, **options)
        return optimize_research(kernel, {}, 'toy', {'custom': True})

    def test_A02_zero_reference_guard(self):
        with self.assertRaises(ValueError): self.toy(0., math.ulp(0.))

    def test_A02_subnormal_false_zero_guard(self):
        with self.assertRaises(ValueError): self.toy(math.ulp(0.), 0.)

    def test_A02_subnormal_sign_guard(self):
        with self.assertRaises(ValueError): self.toy(math.ulp(0.), -math.ulp(0.))

    def test_A02_correct_subnormal(self):
        self.assertEqual(self.toy(math.ulp(0.), math.ulp(0.))['payoff'], math.ulp(0.))

    def test_A02_ordinary_roundoff(self):
        self.assertEqual(self.toy(1., math.nextafter(1., 2.))['objective_consistency']['status'], 'passed')

    def test_A02_ordinary_error(self):
        with self.assertRaises(ValueError): self.toy(1., 1.001)

    def test_A02_large_opposite_values(self):
        with self.assertRaises(ValueError): self.toy(sys.float_info.max, -sys.float_info.max)

    def test_A02_solver_quality_cannot_relax(self):
        p = replace(self.p, margin_x=1e-280, deployment_cost=1e-280)
        with self.assertRaises(ValueError):
            self.research(self.candidate(p=p, value=1e-11), p=p, b=replace(self.b, payoff_atol=1e9, payoff_rtol=1e9))

    def test_A02_explicit_absolute_policy_recorded(self):
        r = self.toy(0., 1e-11, objective_atol=1e-10)
        self.assertEqual(r['objective_consistency']['absolute_tolerance'], 1e-10)
        self.assertFalse(r['objective_consistency']['zero_sign_guard'])

    def test_A02_explicit_relative_policy_recorded(self):
        r = self.toy(1., 1.0001, objective_rtol=1e-3)
        self.assertEqual(r['objective_consistency']['relative_tolerance'], 1e-3)

    def test_A02_policy_invalid_values(self):
        for name in ['objective_atol', 'objective_rtol']:
            for value in [True, -1., float('inf'), float('nan'), Fraction(1, 10**500)]:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.toy(1., 1., **{name: value})

    def test_A02_policy_native_types(self):
        r = self.toy(1., 1., objective_atol=np.int64(0), objective_rtol=np.float32(1e-8))
        self.assertIs(type(r['objective_consistency']['relative_tolerance']), float)
        json.dumps(r, allow_nan=False)

    def test_A02_null_not_marked_checked(self):
        r = optimize_research(default_research_kernel(), self.p, 'RL', replace(self.b, announcement_upper=None), .125)
        self.assertEqual(r['objective_consistency']['status'], 'not_applicable')

    def test_A02_untrusted_check_is_overwritten(self):
        r = self.research(self.candidate(objective_consistency={'status': 'invented'}))
        self.assertEqual(r['objective_consistency']['status'], 'passed')

    def export(self, candidate):
        result = self.research(candidate)
        with TemporaryDirectory() as td:
            path = Path(td) / 'result.json'
            write_json(path, result)
            self.assertEqual(read_json(path), result)
        for name in ['delay', 'announcement', 'payoff']:
            self.assertIs(type(result[name]), float)
        return result

    def test_A03_fraction_delay(self): self.export(self.candidate(delay=Fraction(1, 8)))
    def test_A03_float32_delay(self): self.export(self.candidate(delay=np.float32(.125)))
    def test_A03_int64_announcement(self): self.export(self.candidate(intensity=np.int64(0)))
    def test_A03_fraction_announcement(self): self.export(self.candidate(intensity=Fraction(0)))

    def test_A03_input_unchanged(self):
        candidate = self.candidate(delay=Fraction(1, 8), intensity=np.int64(0))
        self.export(candidate)
        self.assertIs(type(candidate['delay']), Fraction)
        self.assertIs(type(candidate['announcement']), np.int64)
        self.assertNotIn('objective_consistency', candidate)

    def test_A03_callback_receives_native_controls(self):
        seen = []
        kernel = replace(default_research_kernel(), conditional_solver=lambda *a: self.candidate(delay=Fraction(1, 8), intensity=np.int64(0)),
                         validate_solution=lambda p, s, b, r, v: seen.append((type(v['delay']), type(v['announcement']), type(v['payoff']))) is None)
        optimize_research(kernel, self.p, 'DL', self.b, .125)
        self.assertEqual(seen, [(float, float, float)])

    def test_A03_invalid_control_rejected_before_callback(self):
        seen = []
        for value in [True, .125+0j, float('nan'), Fraction(1, 10**500)]:
            result = {'strategy': 'DL', 'delay': value, 'announcement': 0., 'payoff': 1.}
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.research(result, validate_solution=lambda *a: seen.append(a) is None)
        self.assertEqual(seen, [])

    def test_A03_custom_negative_domain_retained(self):
        r = self.toy(-1., -1.)
        self.assertEqual((r['delay'], r['announcement']), (-1., -2.))

    def test_A03_extra_metadata_is_not_reinterpreted(self):
        marker = {'label': '1e-400'}
        result = self.research(self.candidate(extra=marker))
        self.assertIs(result['extra'], marker)

    def adapter(self):
        def solver(p, strategy, bounds, rival):
            return {'strategy': strategy, 'delay': Fraction(1, 8), 'announcement': np.int64(0),
                    'payoff': payoff(p, strategy, .125)}
        kernel = replace(default_research_kernel(), conditional_solver=solver)
        return lambda p, st, b, r: optimize_research(kernel, p, st, b, r)

    def test_A03_comparison_export(self):
        r = compare(self.p, self.b, .125, optimizer=self.adapter())
        self.assertEqual(len(json.loads(json.dumps(r, allow_nan=False))['results']), 4)

    def test_A03_actual_case_checkpoint_and_csv(self):
        meta, tasks = prepare_sweep(self.p, self.b, .125, {'deployment_cost': [.001]})
        case = execute_case(self.p, self.b, .125, next(tasks()), meta, self.adapter())
        with TemporaryDirectory() as td:
            directory = Path(td)
            store = CheckpointStore(directory / 'checkpoint.sqlite', {'test': 'research_core_controls'})
            try:
                store.add(case); store.commit(); _export_csv(directory, 'sweep', store)
                self.assertEqual(list(store.cases())[0], case)
            finally: store.close()
            with (directory / 'sweep.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(float(row['delay']) == .125 for row in rows))

    def cli(self, delay='0', announcement='0', diagnostic=False):
        with TemporaryDirectory() as td:
            path = Path(td) / 'config.json'
            write_json(path, {'bounds': {'delay_lower': 0., 'delay_upper': 0.}})
            command = [sys.executable, '-m', 'entrysignallab.cli', 'evaluate', '--config', str(path), '--strategy', 'DL',
                       '--delay=' + delay, '--announcement=' + announcement]
            if diagnostic: command.append('--allow-outside-bounds')
            return subprocess.run(command, capture_output=True, text=True, timeout=30)

    def test_A04_positive_delay_underflow(self):
        r = self.cli(delay='1e-400'); self.assertEqual(r.returncode, 2); self.assertIn('underflows', r.stderr)
    def test_A04_negative_delay_underflow(self): self.assertEqual(self.cli(delay='-1e-400').returncode, 2)
    def test_A04_positive_silent_intensity_underflow(self): self.assertEqual(self.cli(announcement='1e-400').returncode, 2)
    def test_A04_negative_silent_intensity_underflow(self): self.assertEqual(self.cli(announcement='-1e-400').returncode, 2)
    def test_A04_exact_zero(self): self.assertEqual(self.cli('0e-400', '0e-400').returncode, 0)
    def test_A04_signed_exact_zero(self): self.assertEqual(self.cli('-0e-400', '-0e-400').returncode, 0)
    def test_A04_minimum_subnormal(self):
        r = self.cli('5e-324', diagnostic=True)
        self.assertEqual(r.returncode, 0); self.assertEqual(json.loads(r.stdout)['delay'], math.ulp(0.))
    def test_A04_regular_outside_still_rejected(self): self.assertEqual(self.cli('.001').returncode, 2)
    def test_A04_regular_nonzero_silent_rejected(self): self.assertEqual(self.cli(announcement='.001').returncode, 2)
    def test_A04_overflow_rejected(self): self.assertEqual(self.cli('1e400').returncode, 2)
    def test_A04_nonfinite_rejected(self):
        for value in ['nan', 'inf', '-Infinity']:
            with self.subTest(value=value): self.assertEqual(self.cli(value).returncode, 2)
    def test_A04_underscore_underflow(self): self.assertEqual(self.cli('1_0e-400').returncode, 2)
    def test_A04_unicode_underflow(self): self.assertEqual(self.cli('１e-400').returncode, 2)
    def test_A04_python_float_grammar(self):
        self.assertEqual(finite_float_text('  +1_0.5e-2  '), .105)
        self.assertEqual(finite_float_text('１２.５e-2'), .125)
    def test_A04_json_guard_preserved(self):
        with TemporaryDirectory() as td:
            path = Path(td) / 'config.json'; path.write_text('{"params":{"growth":1e-400}}')
            with self.assertRaises(ValueError): load_config(path)


if __name__ == '__main__': unittest.main()
