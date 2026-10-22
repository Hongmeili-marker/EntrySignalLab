"""v0.3.0 strict-audit regressions with independent counterexample values."""
from pathlib import Path
from math import exp
from tempfile import TemporaryDirectory
import unittest,json
from entrysignallab import ModelParams,DecisionBounds,payoff,optimize,rescale_experiment
from entrysignallab.workflow import manifest,write_json,verify_manifest,current_source_hashes,record_validation,verify_validation
from entrysignallab.solver import profile_announcement

class EdgeAndScaleTests(unittest.TestCase):
    def test_peak_in_first_mesh_cell(self):
        p=ModelParams(growth=1,network=0,growth_end=1,horizon=2,margin_x=1,deployment_cost=.01,learning_rate=1000)
        r=optimize(p,'DL')
        self.assertAlmostEqual(r['payoff'],.7466987410448572,places=13)
        self.assertAlmostEqual(r['delay'],.0023037376257176593,places=9)
        self.assertEqual(r['delay_active'],'interior')
    def test_peak_in_last_mesh_cell(self):
        t=.999;p=ModelParams(growth=1,network=0,growth_end=1,horizon=2,margin_x=1,
            learning_rate=3,deployment_cost=(2-t)*exp(3*t)/6)
        r=optimize(p,'DL')
        self.assertAlmostEqual(r['delay'],t,places=7)
    def test_edge_peak_tiny_time_units(self):
        p=ModelParams(growth=1,network=0,growth_end=1,horizon=2,margin_x=1,deployment_cost=.01,learning_rate=1000)
        q,b,r=rescale_experiment(p,DecisionBounds(),.15,1e-120,1)
        answer=optimize(q,'DL',b,r)
        self.assertAlmostEqual(answer['payoff'],.7466987410448572,places=11)
    def test_small_time_revenue_not_silently_zero(self):
        p=ModelParams();q,b,r=rescale_experiment(p,DecisionBounds(),.15,1e-200,1)
        self.assertAlmostEqual(payoff(q,'DF',.15e-200),.004931079990063347,places=13)
    def test_large_time_representable_revenue(self):
        p=ModelParams();q,b,r=rescale_experiment(p,DecisionBounds(),.15,1e200,1)
        self.assertAlmostEqual(payoff(q,'DF',.15e200),.004931079990063347,places=13)
    def test_discount_and_margin_scale_balanced(self):
        p=ModelParams(discount=.4);q,b,r=rescale_experiment(p,DecisionBounds(),.15,1e-240,1)
        self.assertAlmostEqual(payoff(q,'RL',.15e-240,.4e240),payoff(p,'RL',.15,.4),places=12)
    def test_zero_margins_do_not_overflow_moments(self):
        p=ModelParams(growth_end=1e200,horizon=2e200,growth=1e200,margin_x=0,margin_y=0)
        self.assertEqual(payoff(p,'DF',1e199),0.)
    def test_invalid_delay_rejected_by_profiler(self):
        with self.assertRaises(ValueError):profile_announcement(ModelParams(),'DL',-.1,2)
    def test_invalid_options_rejected_by_profiler(self):
        with self.assertRaises(ValueError):profile_announcement(ModelParams(),'DL',.1,-1)

class ReceiptTests(unittest.TestCase):
    def create(self,p):
        write_json(p/'config.json',{});return manifest(p,{},104,'test')
    def test_missing_metadata_rejected(self):
        with TemporaryDirectory() as td:
            p=Path(td);m=self.create(p);m.pop('version');write_json(p/'manifest.json',m)
            self.assertFalse(verify_manifest(p,current_source_hashes())['valid'])
    def test_bool_seed_rejected(self):
        with TemporaryDirectory() as td:
            p=Path(td);m=self.create(p);m['seed']=True;write_json(p/'manifest.json',m)
            self.assertFalse(verify_manifest(p)['valid'])
    def test_duplicate_record_key_rejected(self):
        with TemporaryDirectory() as td:
            p=Path(td);self.create(p);f=p/'manifest.json';s=f.read_text();f.write_text(s.replace('{','{"version":"0.4.0",',1))
            self.assertFalse(verify_manifest(p)['valid'])
    def test_legacy_complete_metadata_accepted(self):
        with TemporaryDirectory() as td:
            p=Path(td);m=self.create(p);m.pop('manifest_schema');write_json(p/'manifest.json',m)
            self.assertTrue(verify_manifest(p)['valid'])
    def test_validation_source_and_validator_bound(self):
        with TemporaryDirectory() as td:
            p=Path(td);write_json(p/'summary.json',{'all_pass':True});record_validation(p,Path(__file__))
            self.assertTrue(verify_validation(p,Path(__file__))['valid'])
            m=json.loads((p/'manifest.json').read_text());m['source_sha256']['model.py']='0'*64;write_json(p/'manifest.json',m)
            self.assertFalse(verify_validation(p,Path(__file__))['valid'])
    def test_validation_output_change_rejected(self):
        with TemporaryDirectory() as td:
            p=Path(td);write_json(p/'summary.json',{'all_pass':True});record_validation(p,Path(__file__))
            write_json(p/'summary.json',{'all_pass':False})
            self.assertFalse(verify_validation(p,Path(__file__))['valid'])

if __name__=='__main__':unittest.main()
