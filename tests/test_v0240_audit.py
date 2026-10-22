"""Scientific regression tests for cancellation and representable root endpoints."""
from pathlib import Path
from dataclasses import replace
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0240 import rational_payoff,rational_gradient,policy_reference,captured_node_case
from validate_wheel import mutation_checks
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,compare_stability
from entrysignallab.solver import profile_announcement,NumericalError

ROOT=Path(__file__).resolve().parents[1]
def load(name):return json.loads((ROOT/'tests/data'/name).read_text())
def named():
    return ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=1e16,announcement_cost=1e29,deployment_cost=3.8333332949616664e16)
B=DecisionBounds(delay_lower=1,delay_upper=1)

class Cancellation(unittest.TestCase):
    def test_default_ranking_matches_exact_reference(self):
        r=compare(named(),B,1);self.assertEqual(r['co_best'],['RF']);self.assertEqual(policy_reference(named(),r,1e-8)[0],['RF'])
    def test_gap_uses_original_gross_components(self):
        r=compare(named(),B,1);self.assertAlmostEqual(r['entry_payoff_gap'],24.691358024690995,places=12)
        self.assertNotEqual(r['entry_payoff_gap'],r['results'][0]['payoff']-r['results'][2]['payoff'])
    def test_outside_option_checks_original_values(self):
        p=named();r=compare(p,B,1)
        for offset in [-1.,0.,1.]:
            outside=float(rational_payoff(p,r['results'][0]))+offset
            x=compare(p,B,1,outside_option=outside)
            self.assertEqual(x['preferred_with_outside_option'],policy_reference(p,x,1e-8,outside)[1])
    def test_negative_and_positive_net_signs_and_strict_tolerance(self):
        corpus=load('v0230_cancellation_comparisons.json')
        for i in [0,1,110,111,448,449,894,895]:
            x=corpus[i];p=ModelParams(**x['params']);r=compare(p,DecisionBounds(**x['bounds']),1,tie_tolerance=x['tie_tolerance'])
            a,b=policy_reference(p,r,x['tie_tolerance']);self.assertEqual(r['co_best'],a);self.assertEqual(r['preferred_with_outside_option'],b)
    def test_mesh_reports_use_corrected_policy(self):
        r=compare_stability(named(),B,1,factors=(1,2));self.assertTrue(all(x['co_best']==['RF'] for x in r['reports']))
    def test_external_optimizer_keeps_its_values(self):
        r=compare(named(),B,1,optimizer=lambda p,s,b,r:{'strategy':s,'payoff':1.},outside_option=1.)
        self.assertEqual(r['co_best'],['RF','RL','DF','DL']);self.assertNotIn('comparison_precision',r)
    def test_evaluated_delay_node_witness_is_repaired(self):
        p=ModelParams(growth=1,network=0,growth_end=3,horizon=3,margin_x=1e8,deployment_cost=271828180.1249044,learning_rate=1)
        r,points,refs=captured_node_case(p,DecisionBounds(announcement_upper=0))
        self.assertEqual(refs[0],refs[1]);self.assertEqual(refs[1]['gap'],0)
        self.assertEqual(r['search_precision']['evaluated_candidate_consistency_checks'],len(points)-1)
    def test_non_cancelling_comparison_remains_correct(self):
        p=replace(named(),deployment_cost=0.);r=compare(p,B,1);self.assertEqual(r['co_best'],policy_reference(p,r,1e-8)[0])

class RootEndpoints(unittest.TestCase):
    def test_minimum_positive_exact_root_is_accepted(self):
        x=next(x for x in load('v0230_representable_root_edges.json') if x['group']=='minimum' and x['exponent']==537 and x['strategy']=='RF' and x['bounds']['announcement_upper'] is None)
        p=ModelParams(**x['params']);d,_=profile_announcement(p,'RF',x['rival_delay'],None)
        self.assertEqual(d,x['reference_root']);self.assertEqual(rational_gradient(p,'RF',x['rival_delay'],d),0)
    def test_near_maximum_exact_root_is_in_range(self):
        x=next(x for x in load('v0230_representable_root_edges.json') if x['group']=='maximum' and x['j']==2 and x['bounds']['announcement_upper'] is None)
        p=ModelParams(**x['params']);d,_=profile_announcement(p,'RF',1,None)
        self.assertGreater(d,0);self.assertEqual(rational_gradient(p,'RF',1,d),0)
    def test_all_eighty_representable_root_constructions(self):
        for x in load('v0230_representable_root_edges.json'):
            p=ModelParams(**x['params']);b=replace(DecisionBounds(**x['bounds']),delay_lower=x['rival_delay'],delay_upper=x['rival_delay'])
            r=optimize(p,x['strategy'],b,x['rival_delay'])
            self.assertGreater(r['announcement'],0)
    def test_true_below_range_roots_still_refuse(self):
        for x in load('v0220_A18_roots.json'):
            with self.assertRaises(NumericalError):optimize(ModelParams(**x['params']),x['result']['strategy'],DecisionBounds(**x['bounds']),2)
    def test_finite_derivative_proves_root_below_minimum(self):
        x=next(x for x in load('v0230_representable_root_edges.json') if x['group']=='minimum' and x['exponent']==537 and x['strategy']=='RF')
        p=replace(ModelParams(**x['params']),announcement_cost=x['params']['announcement_cost']*2)
        self.assertLess(rational_gradient(p,'RF',x['rival_delay'],x['reference_root']),0)
        with self.assertRaisesRegex(NumericalError,'below floating-point range'):profile_announcement(p,'RF',x['rival_delay'],None)
    def test_finite_derivative_proves_root_above_maximum(self):
        x=next(x for x in load('v0230_representable_root_edges.json') if x['group']=='maximum' and x['j']==2)
        p=replace(ModelParams(**x['params']),margin_x=x['params']['margin_x']*4)
        self.assertGreater(rational_gradient(p,'RF',1,sys.float_info.max),0)
        with self.assertRaisesRegex(NumericalError,'exceeds floating-point range'):profile_announcement(p,'RF',1,None)
    def test_cost_free_finite_cap_still_exact(self):
        self.assertEqual(profile_announcement(ModelParams(),'RF',.1,2),(2.,False))
    def test_fixed_zero_cap_keeps_zero(self):
        self.assertEqual(profile_announcement(ModelParams(announcement_cost=1),'RF',.1,0),(0.,False))

class WheelMetadata(unittest.TestCase):
    def test_valid_current_wheel_and_ten_semantic_mutations(self):
        rows=mutation_checks(ROOT);self.assertEqual(len(rows),11);self.assertTrue(all(x['pass'] for x in rows))

if __name__=='__main__':unittest.main()
