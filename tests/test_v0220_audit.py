"""Independent A16 spread regressions and D01 configuration behavior."""
from pathlib import Path
from dataclasses import replace
from fractions import Fraction as F
from unittest.mock import patch
import json,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0220 import named_params,named_bounds,rational_objective,decimal_objective,comparison_projection
from entrysignallab import ModelParams,DecisionBounds,compare_stability
from validation_portability import frozen_matches, comparison_evidence_valid
from entrysignallab.solver import NumericalError


class MeshSpread(unittest.TestCase):
    def test_named_rejects_false_stability(self):
        r=compare_stability(named_params(),named_bounds(),0,{'tie_tolerance':0})
        self.assertFalse(r['payoff_stable']);self.assertTrue(r['ranking_stable'])
        self.assertGreater(r['strategies'][1]['observed_payoff_spread'],1e-8)
    def test_named_amount_matches_independent_rational_integral(self):
        p=named_params();r=compare_stability(p,named_bounds(),0)
        values=[rational_objective(p,x['results'][1]) for x in r['reports']]
        self.assertEqual(r['strategies'][1]['observed_payoff_spread'],float(max(values)-min(values)))
    def test_all_frozen_rational_cases_match(self):
        cases=json.loads((Path(__file__).parent/'data/v0210_A16_rational_corpus.json').read_text())
        for case in cases:
            p=ModelParams(**case['params']);r=compare_stability(p,DecisionBounds(**case['bounds']),0,{'tie_tolerance':0})
            with self.subTest(case=case['name']):
                self.assertTrue(frozen_matches(comparison_projection(r['reports']),comparison_projection(case['report']['reports'])))
                self.assertTrue(all(comparison_evidence_valid(p,mesh) for mesh in r['reports']))
                for i,row in enumerate(r['strategies']):
                    values=[rational_objective(p,x['results'][i]) for x in r['reports']];spread=max(values)-min(values)
                    self.assertEqual(row['observed_payoff_spread'],float(spread))
                    self.assertEqual(row['within_quality_tolerance'],spread<=F(row['quality_threshold']))
    def test_diagnostic_preserves_nonzero_sign(self):
        r=compare_stability(named_params(),named_bounds(),0);row=r['strategies'][1]
        self.assertEqual(row['observed_payoff_spread_diagnostic']['sign'],1)
        self.assertEqual(row['observed_payoff_spread_diagnostic']['tolerance_relation'],1)
    def test_maximum_and_minimum_factors_identify_controls(self):
        p=named_params();r=compare_stability(p,named_bounds(),0);row=r['strategies'][1]
        values=[rational_objective(p,x['results'][1]) for x in r['reports']]
        self.assertEqual(values[r['factors'].index(row['maximum_payoff_factor'])],max(values))
        self.assertEqual(values[r['factors'].index(row['minimum_payoff_factor'])],min(values))
    def test_local_quality_and_mesh_agreement_stay_separate(self):
        p=ModelParams(growth=1,network=0,growth_end=3,horizon=3,margin_x=1,discount=1000,learning_rate=100,deployment_cost=1e45)
        b=DecisionBounds(delay_lower=1,delay_upper=2,announcement_upper=0,scouting_points=3,tolerance=1,payoff_atol=0,payoff_rtol=0)
        r=compare_stability(p,b,0,factors=(1,2))
        self.assertTrue(r['payoff_stable'])
        self.assertTrue(all(x['local_quality_status']=='fail' for x in r['reports']))
    def test_fixed_controls_have_exact_zero_spread(self):
        r=compare_stability(named_params(),named_bounds(delay_lower=.25,delay_upper=.25),0)
        self.assertTrue(r['payoff_stable'])
        self.assertTrue(all(x['observed_payoff_spread_diagnostic']['sign']==0 for x in r['strategies']))
    def test_exact_zero_model_remains_supported(self):
        r=compare_stability(ModelParams(growth=0,deployment_cost=0),DecisionBounds(),0)
        self.assertTrue(r['payoff_stable'])
        self.assertTrue(all(x['observed_payoff_spread']==0 for x in r['strategies']))
    def test_underflow_strict_zero_does_not_pass(self):
        p=ModelParams(growth=1,network=0,growth_end=3,horizon=3,margin_x=1,discount=1000,learning_rate=100,deployment_cost=1e45)
        b=DecisionBounds(delay_lower=1,delay_upper=2,announcement_upper=0,scouting_points=3,tolerance=1,payoff_atol=0,payoff_rtol=0)
        r=compare_stability(p,b,0,{'tie_tolerance':0})
        self.assertFalse(r['payoff_stable'])
        for i in (1,3):
            row=r['strategies'][i];self.assertEqual(row['observed_payoff_spread'],0)
            self.assertEqual(row['observed_payoff_spread_diagnostic']['representation'],'underflow')
            self.assertEqual(row['observed_payoff_spread_diagnostic']['sign'],1)
            self.assertFalse(row['within_quality_tolerance'])
    def test_underflow_positive_band_can_pass(self):
        p=ModelParams(growth=1,network=0,growth_end=3,horizon=3,margin_x=1,discount=1000,learning_rate=100,deployment_cost=1e45)
        b=DecisionBounds(delay_lower=1,delay_upper=2,announcement_upper=0,scouting_points=3,tolerance=1,payoff_atol=float.fromhex('0x0.0000000000001p-1022'),payoff_rtol=0)
        r=compare_stability(p,b,0,{'tie_tolerance':0});self.assertTrue(r['payoff_stable'])
    def test_relative_band_uses_disclosed_displayed_scale(self):
        r=compare_stability(named_params(),named_bounds(payoff_atol=0,payoff_rtol=1e-16),0)
        row=r['strategies'][1];self.assertEqual(row['quality_threshold'],1e-16*max(abs(x) for x in row['payoffs']))
        self.assertTrue(row['within_quality_tolerance'])
    def test_null_results_withhold_spread_and_stability(self):
        r=compare_stability(ModelParams(),DecisionBounds(announcement_upper=None),.15,factors=(1,2))
        self.assertFalse(r['payoff_stable']);self.assertFalse(r['ranking_stable'])
        for row in r['strategies'][:2]:
            self.assertIsNone(row['observed_payoff_spread_diagnostic']);self.assertIsNone(row['maximum_payoff_factor'])
    def test_unrepresentable_derived_threshold_refuses(self):
        with self.assertRaisesRegex(NumericalError,'mesh stability quality threshold'):
            compare_stability(ModelParams(growth=0,margin_x=0,deployment_cost=1e308),DecisionBounds(announcement_upper=0,payoff_rtol=1e308),0,factors=(1,2))
    def test_discounted_spread_matches_independent_integral(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12,discount=.4)
        r=compare_stability(p,DecisionBounds(scouting_points=3,tolerance=.1),0)
        for i,row in enumerate(r['strategies']):
            v=[decimal_objective(p,x['results'][i]) for x in r['reports']]
            self.assertEqual(row['within_quality_tolerance'],max(v)-min(v)<=row['quality_threshold'])
    def test_policy_scope_is_explicit(self):
        r=compare_stability(named_params(),named_bounds(),0)
        self.assertEqual(r['payoff_stability_precision']['policy'],'original_input_mesh_spread_v1');self.assertFalse(r['globally_certified'])


class DocumentationContract(unittest.TestCase):
    def test_generated_counts_follow_contract(self):
        from sync_api_docs import synchronize
        synchronize(Path(__file__).resolve().parents[1],check=True)
    def test_stale_generated_count_is_rejected(self):
        from sync_api_docs import synchronize
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'scripts').mkdir();(root/'docs').mkdir()
            original=Path(__file__).resolve().parents[1]
            text=(original/'docs/api.md').read_text();(root/'docs/api.md').write_text(text)
            c=json.loads((original/'scripts/release_contract.json').read_text());c['validators']['new_validator']={}
            (root/'scripts/release_contract.json').write_text(json.dumps(c))
            with self.assertRaisesRegex(ValueError,'stale'):synchronize(root,check=True)
