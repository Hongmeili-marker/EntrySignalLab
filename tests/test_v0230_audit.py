"""Regression contracts for the four v0.22.0 audit findings."""
from pathlib import Path
from dataclasses import replace
from math import nextafter,inf
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0230 import rational_derivative,decimal_derivative,coarse_case
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,compare_stability
from entrysignallab.model import announcement_gradient
from entrysignallab.solver import announcement_stationarity,NumericalError
from entrysignallab.plots import html_report

ROOT=Path(__file__).resolve().parents[1]
def frozen(name):return json.loads((ROOT/'tests/data'/name).read_text())

class AnnouncementDiagnostics(unittest.TestCase):
    def test_named_raw_and_scalar_use_exact_input_difference(self):
        old=frozen('v0220_A17_stationarity.json')[2];p=ModelParams(**old['params'])
        r=optimize(p,'RF',DecisionBounds(**old['bounds']),1)
        g,_=rational_derivative(p,'RF',r['delay'],r['announcement'])
        self.assertEqual(r['announcement_stationarity_residual'],float(abs(g)))
        self.assertEqual(announcement_gradient(p,'RF',r['delay'],r['announcement']),float(g))
        self.assertGreater(r['announcement_stationarity_residual'],5)
    def test_all_fourteen_frozen_controls_and_residuals(self):
        for old in frozen('v0220_A17_stationarity.json'):
            p=ModelParams(**old['params']);st=old['strategy'];r=optimize(p,st,DecisionBounds(**old['bounds']),1)
            g,scale=rational_derivative(p,st,r['delay'],r['announcement'])
            with self.subTest(strategy=st,scale=old['scale']):
                self.assertEqual(r['announcement'],old['result']['announcement'])
                self.assertEqual(r['payoff'],old['result']['payoff'])
                self.assertEqual(r['announcement_stationarity_residual'],float(abs(g)))
                self.assertEqual(r['announcement_stationarity_scaled_residual'],float(abs(g)/scale))
    def test_discounted_derivative_has_independent_reference(self):
        p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=1,announcement_cost=1,discount=.4)
        r=optimize(p,'RL',DecisionBounds(delay_lower=1,delay_upper=1),1)
        g,_=decimal_derivative(p,'RL',1,r['announcement'],400)
        self.assertAlmostEqual(r['announcement_stationarity_residual']/float(abs(g)),1,places=12)
        self.assertGreaterEqual(r['announcement_stationarity_diagnostic']['precision_digits'],160)
    def test_zero_rational_derivative_stays_zero(self):
        p=ModelParams(growth=1,network=1,growth_end=2,horizon=2,margin_x=1,announcement_cost=.03125)
        self.assertEqual(announcement_gradient(p,'RF',1,1),0)
        self.assertEqual(announcement_stationarity(p,'RF',1,1,'interior')['raw'],0)
    def test_fixed_zero_cap_needs_no_gradient(self):
        p=ModelParams(discount=1e308,growth_end=3,horizon=3)
        r=optimize(p,'RF',DecisionBounds(announcement_upper=0),2)
        self.assertEqual(r['announcement_stationarity_residual'],0)
        self.assertFalse(r['announcement_nonunique'])
    def test_cost_free_upper_projected_violation_is_zero(self):
        r=optimize(ModelParams(),'RF');self.assertEqual(r['announcement_stationarity_residual'],0)
        self.assertEqual(r['announcement_stationarity_diagnostic']['decision_basis'],'analytic_cost_free_upper_projection')
    def test_near_upper_boundary_sign_is_not_lost(self):
        p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=1,announcement_cost=nextafter(.125,inf))
        g,_=rational_derivative(p,'RF',1,1);self.assertLess(g,0)
        r=announcement_stationarity(p,'RF',1,1,'upper');self.assertEqual(r['raw'],float(abs(g)))
    def test_true_underflow_residual_keeps_sign_and_log(self):
        p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=1e-320,announcement_cost=1e-320)
        r=optimize(p,'RF',DecisionBounds(delay_lower=1,delay_upper=1),1)
        g,_=rational_derivative(p,'RF',1,r['announcement'])
        self.assertNotEqual(g,0);self.assertEqual(r['announcement_stationarity_residual'],0)
        self.assertEqual(r['announcement_stationarity_representation'],'underflow')
        self.assertEqual(r['announcement_stationarity_diagnostic']['gradient_sign'],(g>0)-(g<0))
        self.assertIsNotNone(r['announcement_stationarity_log_residual'])
    def test_silent_gradient_api_still_rejects(self):
        with self.assertRaises(ValueError):announcement_gradient(ModelParams(),'DL',.1,0)

class AnnouncementEffect(unittest.TestCase):
    def test_all_twelve_extreme_cost_free_caps(self):
        for x in frozen('v0220_A18_effect.json'):
            r=optimize(ModelParams(**x['params']),x['result']['strategy'],DecisionBounds(**x['bounds']),2)
            self.assertEqual(r['announcement'],2);self.assertFalse(r['announcement_nonunique'])
    def test_all_six_positive_unrepresentable_roots_refuse(self):
        for x in frozen('v0220_A18_roots.json'):
            with self.assertRaises(NumericalError):optimize(ModelParams(**x['params']),x['result']['strategy'],DecisionBounds(**x['bounds']),2)
    def test_large_finite_exponent_is_not_zero_effect(self):
        p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=1,discount=1000)
        r=optimize(p,'RL',DecisionBounds(delay_lower=2,delay_upper=2),2)
        self.assertEqual(r['announcement'],2);self.assertFalse(r['announcement_nonunique'])
    def test_maturity_remains_nonunique_when_free(self):
        p=ModelParams(growth_end=3,horizon=3,discount=1e308)
        r=optimize(p,'RF',DecisionBounds(),3);self.assertEqual(r['announcement'],0);self.assertTrue(r['announcement_nonunique'])
    def test_actual_zero_network_remains_nonunique(self):
        p=ModelParams(network=0,growth_end=3,horizon=3,discount=1e308)
        r=optimize(p,'RF',DecisionBounds(),2);self.assertTrue(r['announcement_nonunique'])
    def test_no_cap_positive_effect_retains_nonexistence(self):
        r=optimize(ModelParams(growth_end=3,horizon=3,discount=1e308),'RF',DecisionBounds(announcement_upper=None),2)
        self.assertEqual(r['status'],'no_finite_announcement_optimum')

class LegacyResidual(unittest.TestCase):
    def test_failed_last_probe_is_not_a_measured_zero(self):
        p,b=coarse_case()
        for st in ['RL','DL']:
            r=optimize(p,st,b,0);self.assertIsNone(r['local_improvement_residual'])
            self.assertFalse(r['local_quality_passed']);self.assertEqual(r['local_improvement_residual_assessment']['status'],'not_assessed')
            self.assertEqual(r['local_improvement_residual_assessment']['last_probe_quality_status'],'fail')
    def test_promoted_candidate_can_pass_without_final_neighborhood_measurement(self):
        p,b=coarse_case();r=optimize(p,'RL',replace(b,payoff_atol=.01),0)
        self.assertTrue(r['local_quality_passed']);self.assertGreater(r['last_probe_improvement'],0)
        self.assertIsNone(r['local_improvement_residual']);self.assertFalse(r['local_improvement_residual_assessment']['final_control_neighborhood_assessed'])
    def test_no_improving_measured_neighbors_have_assessed_zero(self):
        p=ModelParams(growth=1,network=0,growth_end=3,horizon=3,margin_x=1)
        r=optimize(p,'DL',DecisionBounds(announcement_upper=0,scouting_points=3,tolerance=1),0)
        self.assertEqual(r['local_improvement_residual'],0);self.assertEqual(r['local_improvement_residual_assessment']['status'],'assessed_zero')
    def test_collapsed_probe_cannot_claim_assessed_neighborhood(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12)
        b=DecisionBounds(delay_lower=.1,delay_upper=.10000000000001,scouting_points=3,tolerance=1)
        r=optimize(p,'DL',b,0)
        self.assertEqual(r['delay']+(b.delay_upper-b.delay_lower)*1e-5,r['delay'])
        self.assertIsNone(r['local_improvement_residual'])
        self.assertFalse(r['local_improvement_residual_assessment']['final_control_neighborhood_assessed'])
        self.assertEqual(r['local_improvement_residual_assessment']['status'],'not_assessed')
    def test_analytic_flat_domain_has_analytic_zero(self):
        r=optimize(ModelParams(growth=0),'DL')
        self.assertEqual(r['local_improvement_residual'],0);self.assertEqual(r['local_improvement_residual_assessment']['status'],'analytic_zero')
    def test_first_mover_residual_not_applicable(self):
        r=optimize(ModelParams(),'DF');self.assertIsNone(r['local_improvement_residual'])
        self.assertEqual(r['local_improvement_residual_assessment']['status'],'not_applicable')
    def test_fixed_follower_residual_not_applicable(self):
        r=optimize(ModelParams(),'DL',DecisionBounds(delay_lower=.1,delay_upper=.1))
        self.assertIsNone(r['local_improvement_residual']);self.assertEqual(r['local_improvement_residual_assessment']['status'],'not_applicable')

class ReportStates(unittest.TestCase):
    def report(self,comparison,stability=None):
        with tempfile.TemporaryDirectory() as td:
            html_report(td,comparison,stability=stability);return (Path(td)/'report.html').read_text()
    def test_actual_quality_failure_is_visible(self):
        p,b=coarse_case();s=self.report(compare(p,b,0));self.assertIn('id="numerical-quality" data-status="fail"',s);self.assertIn('Warning:',s)
    def test_stable_ranking_does_not_hide_unstable_payoffs(self):
        p,b=coarse_case();s=self.report(compare(p,b,0),compare_stability(p,b,0))
        self.assertIn('Payoff agreement: unstable.',s);self.assertIn('Ranking agreement: stable.',s)
    def test_quality_pass_visible(self):
        p=ModelParams();b=DecisionBounds(delay_lower=.1,delay_upper=.1,announcement_upper=0)
        s=self.report(compare(p,b,0),compare_stability(p,b,0));self.assertIn('id="numerical-quality" data-status="pass"',s);self.assertIn('id="mesh-stability" data-status="pass"',s)
    def test_unattained_is_not_a_pass(self):
        p=ModelParams();b=DecisionBounds(announcement_upper=None)
        s=self.report(compare(p,b),compare_stability(p,b));self.assertIn('id="numerical-quality" data-status="not_assessed"',s);self.assertIn('Payoff agreement: not assessed.',s)
    def test_disabled_stability_is_not_a_pass(self):
        s=self.report(compare(ModelParams()));self.assertIn('id="mesh-stability" data-status="not_checked"',s)
    def test_actual_json_diagnostic_links_are_present(self):
        p,b=coarse_case();s=self.report(compare(p,b,0),compare_stability(p,b,0))
        self.assertIn('href="comparison.json"',s);self.assertIn('href="stability.json"',s)
    def test_underflow_spread_is_explained_in_html(self):
        p=ModelParams(growth=1,network=0,growth_end=3,horizon=3,margin_x=1,discount=1000,learning_rate=100,deployment_cost=1e45)
        b=DecisionBounds(delay_lower=1,delay_upper=2,announcement_upper=0,scouting_points=3,tolerance=1,payoff_atol=0,payoff_rtol=0)
        s=self.report(compare(p,b,0,tie_tolerance=0),compare_stability(p,b,0,{'tie_tolerance':0},(1,2,4)))
        self.assertIn('Positive spread below the floating-point display range',s);self.assertIn('Payoff agreement: unstable.',s)
    def test_external_unassessed_results_remain_unassessed(self):
        from entrysignallab.solver import compare_results
        r=compare_results([{'strategy':st,'payoff':1} for st in ['RF','RL','DF','DL']])
        self.assertIn('id="numerical-quality" data-status="not_assessed"',self.report(r))
