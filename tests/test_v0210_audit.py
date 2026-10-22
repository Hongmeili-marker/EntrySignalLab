"""A15 preserves original objective order throughout follower search."""
from pathlib import Path
from dataclasses import replace
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0210 import named_params,independent_value,independent_stationary,snapshot_optimize
from entrysignallab import DecisionBounds,compare,compare_stability,optimize
from entrysignallab.solver import NumericalError
from entrysignallab.workflow import sweep,uncertainty

B=DecisionBounds(delay_lower=1,delay_upper=2,announcement_upper=0)

class CandidateOrder(unittest.TestCase):
    def test_RL_selects_positive_original_objective(self):
        r=optimize(named_params(),'RL',B);self.assertGreater(independent_value(named_params(),r['delay'],0,400),0)
    def test_DL_selects_positive_original_objective(self):
        r=optimize(named_params(),'DL',B);self.assertGreater(independent_value(named_params(),r['delay'],0,400),0)
    def test_zero_tolerance_prefers_entry(self):self.assertEqual(compare(named_params(),B,0,tie_tolerance=0)['preferred_with_outside_option'],['RL','DL'])
    def test_default_tolerance_keeps_band(self):self.assertEqual(compare(named_params(),B,0)['preferred_with_outside_option'],['RL','DL','no_entry'])
    def test_minimum_positive_tolerance_keeps_band(self):self.assertEqual(compare(named_params(),B,0,tie_tolerance=float.fromhex('0x0.0000000000001p-1022'))['preferred_with_outside_option'],['RL','DL','no_entry'])
    def test_fixed_negative_remains_negative(self):self.assertEqual(compare(named_params(),replace(B,delay_upper=1),0,tie_tolerance=0)['preferred_with_outside_option'],['no_entry'])
    def test_fixed_positive_remains_positive(self):self.assertEqual(compare(named_params(),replace(B,delay_lower=2),0,tie_tolerance=0)['preferred_with_outside_option'],['RL','DL'])
    def test_frozen_twenty_four_cases(self):
        rows=json.loads((Path(__file__).parent/'data/v0200_A15_boundary_corpus.json').read_text())
        from entrysignallab import ModelParams
        for row in rows:
            p=ModelParams(**row['params'])
            with self.subTest(params=row['params']):
                r=optimize(p,'DL',B);self.assertGreater(independent_value(p,r['delay'],0,400),0)
    def test_returned_candidate_dominates_every_evaluated_node(self):
        p=named_params();r,points=snapshot_optimize(p,'DL',B);selected=independent_value(p,r['delay'],0,400)
        self.assertTrue(all(selected>=independent_value(p,x['delay'],x['announcement'],400) for x in points))
    def test_stationary_reference_matches(self):self.assertLess(abs(optimize(named_params(),'DL',B)['delay']-independent_stationary(named_params())),2e-8)
    def test_announcing_profile_original_order(self):
        p=named_params(network=.85);r=optimize(p,'RL',replace(B,announcement_upper=1));self.assertEqual(r['announcement'],1);self.assertGreater(independent_value(p,r['delay'],1,400),0)
    def test_same_sign_positive_zero_outputs_choose_lower(self):self.assertEqual(optimize(named_params(deployment_cost=0),'DL',B)['delay'],1)
    def test_same_sign_negative_zero_outputs_choose_upper(self):self.assertEqual(optimize(named_params(growth=0,deployment_cost=1),'DL',B)['delay'],2)
    def test_true_constant_zero_is_not_refused(self):
        r=optimize(named_params(growth=0,deployment_cost=0),'DL',B);self.assertEqual(r['payoff'],0);self.assertTrue(r['delay_nonunique']);self.assertEqual(r['evaluations'],1)
    def test_ordinary_representable_candidate(self):
        p=named_params(discount=100);r=optimize(p,'DL',B);self.assertGreater(r['payoff'],0);self.assertAlmostEqual(r['payoff']/float(independent_value(p,r['delay'],0,400)),1,places=10)
    def test_search_precision_is_disclosed(self):
        r=optimize(named_params(),'DL',B);s=r['search_precision'];self.assertEqual(s['policy'],'original_input_profile_order_v1');self.assertGreater(s['rounded_order_disagreements'],0);self.assertGreater(s['guarded_golden_refinements'],0)
    def test_evaluated_count_remains_budgeted(self):
        r,points=snapshot_optimize(named_params(),'DL',B);self.assertEqual(r['evaluations'],len(points));self.assertEqual(r['search_precision']['evaluated_candidate_consistency_checks'],len(points)-1)
    def test_budget_exhaustion_is_controlled(self):
        with self.assertRaisesRegex(NumericalError,'budget'):optimize(named_params(),'DL',replace(B,max_evaluations=65))
    def test_unrepresentable_search_gap_refuses(self):
        p=named_params(growth=0,discount=1e308,growth_end=1e308,horizon=1e308,deployment_cost=1)
        with self.assertRaisesRegex(NumericalError,'logarithmic magnitude'):optimize(p,'DL',replace(B,delay_lower=5e307,delay_upper=1e308))
    def test_strict_quality_detects_underflow_improvement(self):
        r=optimize(named_params(),'DL',replace(B,scouting_points=3,tolerance=1,payoff_atol=0,payoff_rtol=0));self.assertFalse(r['local_quality_passed']);self.assertEqual(r['last_probe_improvement'],0);self.assertEqual(r['last_probe_improvement_diagnostic']['sign'],1)
    def test_derived_quality_threshold_overflow_is_controlled(self):
        p=named_params(discount=0,growth_end=1,horizon=1,margin_x=1e308,deployment_cost=0)
        with self.assertRaisesRegex(NumericalError,'quality threshold'):
            optimize(p,'DL',DecisionBounds(delay_upper=1,announcement_upper=0,payoff_rtol=1e308))
    def test_stability_returns_correct_preferences(self):
        r=compare_stability(named_params(),B,0,{'tie_tolerance':0},(1,2,4));self.assertTrue(r['ranking_stable']);self.assertTrue(all(x['preferred_with_outside_option']==['RL','DL'] for x in r['reports']))
    def test_sweep_preference(self):self.assertTrue(all(x['outside_option_preferred']=='RL|DL' for x in sweep(named_params(),B,0,{'deployment_cost':[1e45]},comparison={'tie_tolerance':0})))
    def test_uncertainty_participation(self):self.assertEqual(uncertainty(named_params(),B,0,{'deployment_cost':[1e45,1e45]},n=1,comparison={'tie_tolerance':0})['outside_option_summary']['entry_preferred'],1)
    def test_external_optimizer_keeps_supplied_float_semantics(self):
        def supplied(p,st,b,r):return {'strategy':st,'payoff':0.}
        r=compare(named_params(),B,0,tie_tolerance=0,optimizer=supplied);self.assertEqual(r['preferred_with_outside_option'],['RF','RL','DF','DL','no_entry']);self.assertNotIn('comparison_precision',r)
    def test_new_diagnostics_are_finite_JSON(self):json.dumps(compare(named_params(),B,0,tie_tolerance=0),allow_nan=False)

if __name__=='__main__':unittest.main()
