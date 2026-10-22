"""Regressions for original-input comparison gaps and visible point plots."""
from pathlib import Path
from dataclasses import replace
from fractions import Fraction as F
from math import nextafter,inf
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0190 import simultaneous_reference,plot_snapshot
from entrysignallab import ModelParams,DecisionBounds,compare
from entrysignallab.solver import compare_results,NumericalError,compare_stability
from entrysignallab.model import _guarded_objective_gap
from entrysignallab.units import rescale_experiment
from entrysignallab.workflow import sweep,uncertainty
from entrysignallab import plots
ST=['RF','RL','DF','DL'];B=DecisionBounds(delay_upper=0,announcement_upper=2)
def params(scale=1e14):return ModelParams(growth=4*scale,network=0,growth_end=1,horizon=1,margin_x=1,margin_y=1)

class OriginalInputComparison(unittest.TestCase):
    def test_positive_gap_enters(self):
        r=compare(params(),B,0,outside_option=1e14-.25);self.assertEqual(r['outside_option_gap'],.25);self.assertEqual(r['preferred_with_outside_option'],ST)
    def test_negative_gap_exits(self):
        r=compare(params(1e12),B,0,outside_option=1e12+1/4096);self.assertEqual(r['outside_option_gap'],-1/4096);self.assertEqual(r['preferred_with_outside_option'],['no_entry'])
    def test_exact_zero_ties_at_low_scale(self):self.assertEqual(compare(params(1e8),B,0,outside_option=1e8)['preferred_with_outside_option'],ST+['no_entry'])
    def test_exact_zero_ties_at_high_scale(self):self.assertEqual(compare(params(),B,0,outside_option=1e14)['preferred_with_outside_option'],ST+['no_entry'])
    def test_cost_translation(self):
        p=params();o=1e14-.25;a=compare(p,B,0,outside_option=o);b=compare(replace(p,deployment_cost=o),B,0)
        self.assertEqual(a['outside_option_gap'],b['outside_option_gap']);self.assertEqual(a['preferred_with_outside_option'],b['preferred_with_outside_option'])
    def test_exact_time_units(self):
        p,b,r=rescale_experiment(params(),B,0,time_factor=2);self.assertEqual(simultaneous_reference(p),F(10**14));self.assertEqual(compare(p,b,r,outside_option=1e14-.25)['outside_option_gap'],.25)
    def test_exact_consumer_units(self):
        p,b,r=rescale_experiment(params(),B,0,consumer_factor=4);self.assertEqual(simultaneous_reference(p),F(10**14));self.assertEqual(compare(p,b,r,outside_option=1e14-.25)['outside_option_gap'],.25)
    def test_large_tolerance_edge(self):self.assertEqual(compare(params(),B,0,tie_tolerance=1e14-.25)['preferred_with_outside_option'],ST)
    def test_exact_tolerance_edge(self):self.assertEqual(compare(params(),B,0,tie_tolerance=1e14)['preferred_with_outside_option'],ST+['no_entry'])
    def test_tolerance_above_gap(self):self.assertEqual(compare(params(),B,0,tie_tolerance=nextafter(1e14,inf))['preferred_with_outside_option'],ST+['no_entry'])
    def test_underflow_retains_decision_sign(self):
        tiny=float.fromhex('0x0.0000000000001p-1022')
        # pi=tiny is representable; use half of it with growth=2*tiny.
        p=replace(params(),growth=2*tiny);r=compare(p,B,0,tie_tolerance=0)
        self.assertEqual(r['outside_option_gap'],0);self.assertEqual(r['outside_option_gap_diagnostic']['representation'],'underflow');self.assertEqual(r['outside_option_gap_diagnostic']['sign'],1);self.assertEqual(r['preferred_with_outside_option'],ST)
    def test_discounted_equal_scenarios(self):
        r=compare(replace(params(),discount=.5),B,0);self.assertEqual(r['co_best'],ST)
    def test_common_discounted_revenue_cancels_exactly(self):
        p=replace(params(),discount=.5,announcement_cost=1)
        left={'strategy':'RF','delay':0.,'announcement':1.};right={'strategy':'DL','delay':0.,'announcement':0.}
        r=_guarded_objective_gap(p,left,right,tie_tolerance=.5);self.assertEqual(r['value'],-.5);self.assertEqual(r['tolerance_relation'],0)
    def test_discounted_near_outside_uses_adaptive_guard(self):
        p=replace(params(),discount=1e-100);r=compare(p,B,0,outside_option=1e14,tie_tolerance=0)
        self.assertLess(r['outside_option_gap'],0);self.assertEqual(r['preferred_with_outside_option'],['no_entry']);self.assertEqual(r['outside_option_gap_diagnostic']['decision_basis'],'adaptive_original_input_difference')
    def test_unresolved_raises_controlled_error(self):
        p=ModelParams(growth=0,network=0,margin_x=0,deployment_cost=1,discount=1e308,growth_end=1e308,horizon=1e308)
        with self.assertRaisesRegex(NumericalError,'comparison unresolved'):compare(p,DecisionBounds(delay_lower=1e308,delay_upper=1e308,announcement_upper=0),0)
    def test_external_results_keep_float_contract(self):
        rows=[{'strategy':s,'payoff':99999999999999.42} for s in ST]
        r=compare_results(rows,outside_option=1e14-.25);self.assertEqual(r['preferred_with_outside_option'],['no_entry']);self.assertNotIn('comparison_precision',r)
    def test_custom_optimizer_not_reinterpreted(self):
        r=compare(params(),B,0,optimizer=lambda p,s,b,r:{'strategy':s,'payoff':1.},outside_option=1.);self.assertEqual(r['preferred_with_outside_option'],ST+['no_entry']);self.assertNotIn('comparison_precision',r)
    def test_null_results_still_unrankable(self):
        r=compare(ModelParams(),DecisionBounds(announcement_upper=None));self.assertFalse(r['all_rankable']);self.assertEqual(r['co_best'],[]);self.assertEqual(r['preferred_with_outside_option'],[])
    def test_gap_provenance_and_json(self):
        r=compare(params(),B,0,outside_option=1e14-.25);self.assertEqual(r['outside_option_gap_diagnostic']['decision_basis'],'exact_original_input_difference');json.dumps(r,allow_nan=False)
    def test_stability_reports_correct_decision(self):
        r=compare_stability(params(),B,0,{'outside_option':1e14-.25});self.assertTrue(r['ranking_stable']);self.assertTrue(all(x['outside_option_gap']==.25 for x in r['reports']))
    def test_sweep_uses_guarded_gap(self):
        rows=sweep(params(),B,0,{'quality_ratio':[1.]},{'outside_option':1e14-.25});self.assertTrue(all(x['outside_option_gap']==.25 and x['outside_option_preferred']=='RF|RL|DF|DL' for x in rows));self.assertEqual(rows[0]['outside_option_gap_basis'],'exact_original_input_difference')
    def test_uncertainty_counts_correct_participation(self):
        r=uncertainty(params(),B,0,{'quality_ratio':[1.,1.]},n=4,comparison={'outside_option':1e14-.25});self.assertEqual(r['outside_option_summary']['entry_preferred'],4)

class PointPlotRegression(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.out=Path(self.tmp.name);self.p=params(1.)
    def tearDown(self):self.tmp.cleanup()
    def surface(self,b):return plot_snapshot(lambda:plots.profit_surface(self.out,self.p,b),False)
    def sweep(self,rows):return plot_snapshot(lambda:plots.sweep_plot(self.out,rows,'growth'),False)
    def rows(self,value=1.):return [{'strategy':s,'growth':4.,'payoff':value} for s in ST]
    def test_singleton_surface_has_actual_point(self):
        r=self.surface(replace(B,announcement_upper=0));self.assertEqual(r['collections'][0]['offsets'],[[0.,1.]]);self.assertTrue(r['collections'][0]['paths'])
    def test_singleton_surface_names_fixed_control(self):self.assertIn('point at delay=0, intensity=0',self.surface(replace(B,announcement_upper=0))['title'])
    def test_nonzero_fixed_delay_point(self):
        r=self.surface(DecisionBounds(delay_lower=.5,delay_upper=.5,announcement_upper=0));self.assertEqual(r['collections'][0]['offsets'],[[0.,.25]])
    def test_intensity_slice_stays_line(self):self.assertEqual(len(self.surface(B)['lines'][0]['finite_coordinates']),81)
    def test_delay_slice_stays_line(self):self.assertEqual(len(self.surface(DecisionBounds(announcement_upper=0))['lines'][0]['finite_coordinates']),81)
    def test_sweep_singleton_has_markers(self):self.assertTrue(all(x['marker']!='None' for x in self.sweep(self.rows())['lines'][:4]))
    def test_overlapping_strategy_markers_differ(self):self.assertEqual(len({x['marker'] for x in self.sweep(self.rows())['lines'][:4]}),4)
    def test_single_finite_value_among_nulls(self):
        r=self.sweep(self.rows(None)+[{**x,'growth':8.} for x in self.rows()]);self.assertTrue(all(x['marker']!='None' and len(x['finite_coordinates'])==1 for x in r['lines'][:4]))
    def test_all_null_does_not_fabricate_data(self):self.assertTrue(all(not x['finite_coordinates'] for x in self.sweep(self.rows(None))['lines'][:4]))
    def test_multiple_finite_values_stay_lines(self):
        r=self.sweep(self.rows()+[{**x,'growth':8.,'payoff':2.} for x in self.rows()]);self.assertTrue(all(len(x['finite_coordinates'])==2 and x['marker']=='None' for x in r['lines'][:4]))

if __name__=='__main__':unittest.main()
