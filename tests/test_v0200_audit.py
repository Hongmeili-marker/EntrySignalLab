"""A13 signed extreme-decay gaps and A14 degenerate finite-run figures."""
from pathlib import Path
from dataclasses import replace
from fractions import Fraction as F
import json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0200 import factored_reference,plot_snapshot,uncut_gap_reference
from entrysignallab import ModelParams,DecisionBounds,compare
from entrysignallab.model import _guarded_objective_gap,_scaled_objective_gap
from entrysignallab.solver import NumericalError
from entrysignallab.workflow import sweep,uncertainty

B=DecisionBounds(delay_lower=1,delay_upper=1,announcement_upper=0)
def params(**changes):
    return ModelParams(**{'growth':1,'network':0,'growth_end':2,'horizon':2,'margin_x':1,
                         'discount':99999,'learning_rate':2,'deployment_cost':1e20,**changes})

class ExtremeDecayComparison(unittest.TestCase):
    def test_negative_original_gap_prefers_nonentry(self):
        self.assertEqual(compare(params(),B,0,tie_tolerance=0)['preferred_with_outside_option'],['no_entry'])
    def test_negative_underflow_sign_is_preserved(self):
        d=compare(params(),B,0,tie_tolerance=0)['outside_option_gap_diagnostic']
        self.assertEqual((d['value'],d['sign'],d['representation']),(0.,-1,'underflow'))
    def test_log_magnitude_matches_independent_factoring(self):
        d=compare(params(),B,0,tie_tolerance=0)['outside_option_gap_diagnostic']
        self.assertAlmostEqual(d['log_abs'],factored_reference(params(),400)[1],places=9)
    def test_extreme_comparison_records_scaled_basis(self):
        r=compare(params(),B,0,tie_tolerance=0)
        self.assertEqual(r['outside_option_gap_diagnostic']['decision_basis'],'scaled_original_input_difference')
        self.assertEqual(r['comparison_precision']['policy'],'original_input_gap_guard_v2')
    def test_positive_underflow_remains_positive(self):
        self.assertEqual(compare(params(learning_rate=20,deployment_cost=.01),B,0,tie_tolerance=0)['preferred_with_outside_option'],['RL','DL'])
    def test_default_tolerance_keeps_band_membership(self):
        r=compare(params(),B,0)
        self.assertEqual(r['preferred_with_outside_option'],['RL','DL','no_entry']);self.assertEqual(r['outside_option_gap_diagnostic']['sign'],-1)
    def test_minimum_positive_tolerance_keeps_band_membership(self):
        self.assertEqual(compare(params(),B,0,tie_tolerance=float.fromhex('0x0.0000000000001p-1022'))['outside_option_gap_diagnostic']['tolerance_relation'],0)
    def test_all_sixty_frozen_cases(self):
        rows=json.loads((Path(__file__).parent/'data/v0190_A13_boundary_corpus.json').read_text())
        for row in rows:
            with self.subTest(params=row['params']):
                p=ModelParams(**row['params']);sign,log=factored_reference(p,400)
                r=compare(p,B,0,tie_tolerance=0);self.assertEqual(r['preferred_with_outside_option'],['RL','DL'] if sign>0 else ['no_entry'])
                self.assertEqual(r['outside_option_gap_diagnostic']['sign'],sign)
    def test_previously_fully_cut_case_resolves(self):
        r=compare(params(discount=100001),B,0,tie_tolerance=0)
        self.assertEqual(r['preferred_with_outside_option'],['no_entry'])
    def test_extreme_single_term_retains_sign(self):
        p=params(growth=0,margin_x=0,discount=1e308,deployment_cost=1,growth_end=1,horizon=1)
        r=compare(p,B,0,tie_tolerance=0);self.assertEqual(r['outside_option_gap_diagnostic']['log_abs'],-1e308);self.assertEqual(r['preferred_with_outside_option'],['no_entry'])
    def test_unrepresentable_log_refuses(self):
        p=params(growth=0,margin_x=0,discount=1e308,growth_end=1e308,horizon=1e308,deployment_cost=1)
        with self.assertRaisesRegex(NumericalError,'logarithmic magnitude'):compare(p,replace(B,delay_lower=1e308,delay_upper=1e308),0)
    def test_tail_bound_blocks_false_decision(self):
        with self.assertRaisesRegex(ValueError,'comparison unresolved'):_scaled_objective_gap({None:F(1,10**43440),('exp',F(100001)):-F(1)},F(0),0)
    def test_zero_discount_extreme_learning(self):
        d=_guarded_objective_gap(params(discount=0,learning_rate=100001,deployment_cost=1),{'strategy':'DL','delay':1.,'announcement':0.},tie_tolerance=0)
        self.assertEqual((d['value'],d['sign']),(.25,1))
    def test_outside_minimum_subnormal_is_not_erased(self):
        tiny=float.fromhex('0x0.0000000000001p-1022');r=compare(params(learning_rate=20,deployment_cost=.01),B,0,tie_tolerance=0,outside_option=tiny)
        self.assertEqual(r['preferred_with_outside_option'],['no_entry']);self.assertEqual(r['outside_option_gap_diagnostic']['value'],-tiny)
    def test_shared_cost_cancels_before_underflow(self):
        p=params(network=.7,quality_ratio=1.3);a={'strategy':'RF','delay':1.,'announcement':.4};b={'strategy':'DF','delay':1.,'announcement':0.}
        ref=uncut_gap_reference(p,a,b,400);actual=_guarded_objective_gap(p,a,b,tie_tolerance=0)
        self.assertGreater(ref,0);self.assertEqual(actual['sign'],1);self.assertEqual(actual['representation'],'underflow')
    def test_reverse_difference_keeps_opposite_sign(self):
        p=params(network=.7);a={'strategy':'RL','delay':1.,'announcement':.4};b={'strategy':'DL','delay':1.,'announcement':0.}
        self.assertEqual(_guarded_objective_gap(p,a,b,tie_tolerance=0)['sign'],-_guarded_objective_gap(p,b,a,tie_tolerance=0)['sign'])
    def test_json_remains_finite(self):json.dumps(compare(params(),B,0,tie_tolerance=0),allow_nan=False)
    def test_sweep_propagates_correct_preference(self):
        rows=sweep(params(),B,0,{'deployment_cost':[1e20,1e20]},comparison={'tie_tolerance':0})
        self.assertTrue(all(r['outside_option_preferred']=='no_entry' and r['outside_option_gap_sign']==-1 for r in rows))
    def test_paired_uncertainty_propagates_correct_preference(self):
        r=uncertainty(params(),B,0,{'deployment_cost':[1e20,1e20]},n=2,comparison={'tie_tolerance':0})
        self.assertEqual(r['outside_option_summary']['non_entry_preferred'],2)

class FiniteRunVisibility(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()
    def snap(self,points):
        rows=[{'strategy':st,'growth':x,'payoff':y} for st in ['RF','RL','DF','DL'] for x,y in points]
        return plot_snapshot(Path(self.tmp.name),rows,False)['series']
    def test_repeated_coordinate_is_visible(self):self.assertTrue(all(r['all_unique_finite_coordinates_visible'] for r in self.snap([(4,1),(4,1)])))
    def test_repeated_coordinate_marks_once(self):self.assertTrue(all(r['markevery']==[0] for r in self.snap([(4,1),(4,1)])))
    def test_isolated_values_are_visible(self):self.assertTrue(all(r['all_unique_finite_coordinates_visible'] for r in self.snap([(1,1),(2,None),(3,1)])))
    def test_isolated_values_mark_actual_indices(self):self.assertTrue(all(r['markevery']==[0,2] for r in self.snap([(1,1),(2,None),(3,1)])))
    def test_mixed_line_and_point(self):self.assertTrue(all(r['markevery']==[3] and r['nonzero_finite_segments']==[0] for r in self.snap([(1,1),(2,2),(3,None),(4,1)])))
    def test_distinct_strategy_markers(self):self.assertEqual(len({r['marker'] for r in self.snap([(4,1),(4,1)])}),4)
    def test_null_breaks_are_retained(self):self.assertTrue(all(r['vertices']==[[1.,1.],[2.,None],[3.,1.]] for r in self.snap([(1,1),(2,None),(3,1)])))
    def test_repeated_vertices_are_retained(self):self.assertTrue(all(r['vertices']==[[4.,1.],[4.,1.]] for r in self.snap([(4,1),(4,1)])))
    def test_connected_curve_retains_no_marker(self):self.assertTrue(all(r['marker']=='None' for r in self.snap([(1,1),(2,2)])))
    def test_all_null_creates_no_marker(self):self.assertTrue(all(r['marker']=='None' and r['finite_observations']==0 for r in self.snap([(1,None),(2,None)])))
    def test_empty_creates_no_fabricated_points(self):self.assertTrue(all(r['finite_observations']==0 for r in self.snap([])))
    def test_duplicate_then_connected_needs_no_marker(self):self.assertTrue(all(r['marker']=='None' and r['all_unique_finite_coordinates_visible'] for r in self.snap([(1,1),(1,1),(2,2)])))
    def test_negative_and_zero_isolated_points(self):self.assertTrue(all(r['all_unique_finite_coordinates_visible'] for r in self.snap([(1,-1),(2,None),(3,0)])))

if __name__=='__main__':unittest.main()
