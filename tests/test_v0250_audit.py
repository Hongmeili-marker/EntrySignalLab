"""Regression witnesses for typed boundary controls and recorded local probes."""
from pathlib import Path
from fractions import Fraction
from dataclasses import replace
from tempfile import TemporaryDirectory
import json,sys,unittest,csv
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0250 import typed_delay,check_probe_result
from entrysignallab import ModelParams,DecisionBounds,optimize,compare
from entrysignallab.solver import profile_announcement,NumericalError
from entrysignallab.workflow import csv_export_row
from entrysignallab.plots import write_csv,html_report,_display_disagreements
ROOT=Path(__file__).resolve().parents[1]
CASES={x['name']:x for x in json.loads((ROOT/'tests/data/v0240_probe_baselines.json').read_text())}
def case(name,st='RL'):
    c=CASES[name]['config'];p=ModelParams(**c.get('params',{}));b=DecisionBounds(**c.get('bounds',{}));rival=c.get('rival_delay',min(.15,p.growth_end));return p,b,rival,optimize(p,st,b,rival)
class TypedBoundary(unittest.TestCase):
    def test_fraction_cap_and_tolerance_are_native_before_structural_branch(self):
        p=ModelParams(growth_end=1,horizon=1,announcement_cost=.01);t=Fraction(1)-Fraction(1,2**80)
        self.assertEqual(profile_announcement(p,'RF',t,Fraction(2),Fraction(1,10**10)),(0.,False))
    def test_cost_free_uncapped_maturity_is_nonunique(self):
        p=ModelParams(growth_end=1,horizon=1);t=Fraction(1)-Fraction(1,2**80)
        self.assertEqual(profile_announcement(p,'RL',t,None),(0.,True))
    def test_zero_cap_at_maturity_is_unique(self):
        p=ModelParams(growth_end=1,horizon=1);t=Fraction(1)-Fraction(1,2**80)
        self.assertEqual(profile_announcement(p,'RL',t,Fraction(0)),(0.,False))
    def test_silent_profile_preserves_typed_boundary(self):
        self.assertEqual(profile_announcement(ModelParams(growth_end=1,horizon=1),'DF',Fraction(1)-Fraction(1,2**80),2),(0.,False))
    def test_invalid_real_controls_still_reject(self):
        p=ModelParams()
        for t,cap,tol in [(True,2,1e-10),(.1,True,1e-10),(.1,2,True),(-1,2,1e-10),(.1,-1,1e-10),(.1,2,0),(.1,2,float('inf'))]:
            with self.subTest(control=(t,cap,tol)),self.assertRaises(ValueError):profile_announcement(p,'RF',t,cap,tol)
    def test_nonzero_underflow_still_rejects(self):
        with self.assertRaises(ValueError):profile_announcement(ModelParams(),'RF',Fraction(1,10**400),2)

for index,row in enumerate(json.loads((ROOT/'tests/data/v0240_ingress_observations.json').read_text())):
    def make_test(x):
        def test(self):
            if x['input_type']=='longdouble_below' and np.finfo(np.longdouble).nmant<=np.finfo(float).nmant:self.skipTest('measured longdouble is not wider than binary64')
            p=ModelParams(**x['params']);self.assertEqual(profile_announcement(p,x['strategy'],typed_delay(x),x['cap']),tuple(x['canonical_reference']))
        return test
    setattr(TypedBoundary,'test_frozen_typed_case_'+str(index).zfill(2),make_test(row))

class ProbeRecords(unittest.TestCase):
    def test_all_frozen_scientific_results_are_preserved(self):
        for name in CASES:
            for st in ['RF','RL','DF','DL']:
                p,b,rival,result=case(name,st);old=next(x for x in CASES[name]['original_comparison']['results'] if x['strategy']==st)
                with self.subTest(name=name,strategy=st):self.assertTrue(all(result[k]==v for k,v in old.items()))
    def test_independent_global_integrals_verify_recorded_gains(self):
        for name in ['product_launch','quality_warning_html','recorded_probe_promoted','recorded_probe_subnormal']:
            for st in ['RL','DL']:
                p,b,rival,result=case(name,st)
                with self.subTest(name=name,strategy=st):self.assertTrue(all(x['pass'] for x in check_probe_result(p,b,result)))
    def test_four_failed_rounds_are_recorded(self):
        p,b,rival,result=case('quality_warning_html');r=result['local_probe_diagnostics']['rounds']
        self.assertEqual(len(r),4);self.assertEqual(r[-1]['termination'],'round_limit');self.assertFalse(r[-1]['passed'])
    def test_pass_after_promotion_does_not_assess_new_neighborhood(self):
        p,b,rival,result=case('recorded_probe_promoted');d=result['local_probe_diagnostics']
        self.assertEqual(d['reason'],'control_promoted');self.assertTrue(result['local_quality_passed']);self.assertFalse(d['final_control_neighborhood_assessed'])
    def test_native_controls_have_complete_actual_records(self):
        p,b,rival,result=case('product_launch')
        for r in result['local_probe_diagnostics']['rounds']:
            self.assertEqual([x['side'] for x in r['probes']],['lower','upper']);self.assertIn('payoff',r['probes'][0]['control']);self.assertIn('announcement',r['selected_control']);self.assertIs(type(r['quality_threshold']),float)
    def test_narrow_interval_records_coincident_probes(self):
        p,b,rival,result=case('recorded_probe_coincidence','DL');d=result['local_probe_diagnostics']
        self.assertEqual(d['reason'],'probe_control_coincidence');self.assertFalse(d['final_control_neighborhood_assessed']);self.assertTrue(all(not x['distinct_from_start'] for x in d['rounds'][0]['probes']))
    def test_subnormal_step_is_not_an_assessed_neighborhood(self):
        p,b,rival,result=case('recorded_probe_subnormal','DL');d=result['local_probe_diagnostics']
        self.assertEqual(d['reason'],'probe_control_coincidence');self.assertFalse(d['final_control_neighborhood_assessed']);self.assertEqual(d['rounds'][0]['probes'][0]['control']['delay'],result['delay'])
    def test_fixed_domain_retains_actual_legacy_probe(self):
        p,b,rival,result=case('quality_pass_html');d=result['local_probe_diagnostics']
        self.assertEqual(d['reason'],'fixed_delay');self.assertEqual(len(d['rounds']),1);self.assertFalse(d['final_control_neighborhood_assessed'])
    def test_boundary_has_only_one_feasible_displacement(self):
        p,b,rival,result=case('boundary','DL');d=result['local_probe_diagnostics']
        self.assertTrue(d['final_control_neighborhood_assessed']);self.assertFalse(d['rounds'][-1]['probes'][0]['distinct_from_start']);self.assertTrue(d['rounds'][-1]['probes'][1]['distinct_from_start'])
    def test_flat_profile_has_no_fabricated_probes(self):
        p,b,rival,result=case('analytic_flat');self.assertEqual(result['local_probe_diagnostics']['status'],'analytic_flat');self.assertEqual(result['local_probe_diagnostics']['rounds'],[])
    def test_first_entrant_has_no_follower_probes(self):
        p,b,rival,result=case('product_launch','RF');self.assertEqual(result['local_probe_diagnostics']['reason'],'fixed_rival_delay');self.assertEqual(result['local_probe_diagnostics']['rounds'],[])
    def test_unattained_result_has_no_probe_claim(self):
        p,b,rival,result=case('unbounded_announcement');self.assertIsNone(result['payoff']);self.assertEqual(result['local_probe_diagnostics']['status'],'not_applicable');self.assertEqual(result['local_probe_diagnostics']['rounds'],[])
    def test_attained_envelope_is_not_neighborhood_assessment(self):
        p,b,rival,result=case('joint_boundary');self.assertEqual(result['status'],'attained_joint_optimum');self.assertEqual(result['local_probe_diagnostics']['reason'],'attained_joint_envelope');self.assertEqual(result['local_probe_diagnostics']['rounds'],[])
    def test_budget_exhaustion_still_refuses(self):
        p,b,rival,result=case('quality_warning_html')
        with self.assertRaises(NumericalError):optimize(p,'RL',replace(b,max_evaluations=4),rival)
    def test_round_control_snapshots_are_independent(self):
        p,b,rival,result=case('product_launch');r=result['local_probe_diagnostics']['rounds'][0];selected=dict(r['selected_control']);r['probes'][0]['control']['payoff']=12345
        self.assertEqual(r['selected_control'],selected);self.assertEqual(result['payoff'],selected['payoff'])

class ProbeExports(unittest.TestCase):
    def report(self,name,**options):
        c=CASES[name]['config'];return compare(ModelParams(**c.get('params',{})),DecisionBounds(**c.get('bounds',{})),c.get('rival_delay',.15),**options)
    def test_probe_csv_cell_is_strict_json(self):
        result=case('quality_warning_html')[3]
        with TemporaryDirectory() as td:
            p=Path(td)/'rows.csv';write_csv(p,[result])
            with p.open(newline='') as f:row=next(csv.DictReader(f))
            self.assertEqual(json.loads(row['local_probe_diagnostics']),result['local_probe_diagnostics'])
    def test_other_csv_values_keep_their_existing_semantics(self):
        old={'value':3.,'legacy':{'x':True},'local_probe_diagnostics':{'rounds':[]}};r=csv_export_row(old)
        self.assertIs(r['legacy'],old['legacy']);self.assertEqual(r['value'],3.);self.assertIsInstance(old['local_probe_diagnostics'],dict)
    def test_known_display_ranking_disagreement_is_explained(self):
        r=self.report('gross_cancellation_ranking');self.assertEqual(r['co_best'],['RF']);self.assertTrue(_display_disagreements(r))
        with TemporaryDirectory() as td:
            html_report(td,r);s=(Path(td)/'report.html').read_text();self.assertIn('id="payoff-display-warning"',s);self.assertIn('exact_original_input_difference',s);self.assertIn('Guarded sign',s)
    def test_outside_decision_disagreement_is_explained(self):
        r=self.report('gross_cancellation_ranking',outside_option=383716750.);self.assertEqual(r['preferred_with_outside_option'],['no_entry']);self.assertTrue(any(x['right']=='outside_option' for x in _display_disagreements(r)))
    def test_ordinary_report_has_no_false_precision_warning(self):
        r=self.report('product_launch');self.assertEqual(_display_disagreements(r),[])
        with TemporaryDirectory() as td:
            html_report(td,r);s=(Path(td)/'report.html').read_text();self.assertNotIn('id="payoff-display-warning"',s);self.assertIn('href="config.json"',s);self.assertIn('local_probe_diagnostics',s)
    def test_report_contains_actual_rounds_and_thresholds(self):
        r=self.report('quality_warning_html')
        with TemporaryDirectory() as td:
            html_report(td,r);s=(Path(td)/'report.html').read_text();self.assertEqual(s.count('data-probe-round='),8);self.assertIn('Payoff threshold',s);self.assertIn(str(r['results'][1]['local_probe_diagnostics']['rounds'][0]['starting_control']['delay']),s)
    def test_supplied_float_semantics_remain_external(self):
        p=ModelParams();r=compare(p,optimizer=lambda p,s,b,r:{'strategy':s,'payoff':1.});self.assertEqual(_display_disagreements(r),[])

if __name__=='__main__':unittest.main()
