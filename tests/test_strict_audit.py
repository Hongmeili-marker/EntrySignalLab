"""Strict v0.2.0 audit regressions: numerical states and evidence contracts."""
import contextlib,io,json,math,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from entrysignallab import ModelParams,DecisionBounds,payoff,optimize,rescale_experiment
from entrysignallab.workflow import manifest,write_json,verify_manifest,current_source_hashes,canonical_hash
from entrysignallab.model import deployment_present_value
from entrysignallab.cli import main

class StrictAuditTests(unittest.TestCase):
    def test_large_rates_small_lag_deployment(self):
        p=ModelParams(growth_end=2e-308,horizon=1e-307,discount=1e308,learning_rate=1e308,deployment_cost=1,margin_x=0,margin_y=0)
        self.assertAlmostEqual(payoff(p,'DL',1e-308),-math.exp(-2),places=14)
    def test_large_cost_rescues_discount_underflow(self):
        p=ModelParams(deployment_cost=1e308,learning_rate=1000)
        expected=math.exp(math.log(1e308)-1000)
        self.assertGreater(deployment_present_value(p,1),0)
        self.assertAlmostEqual(deployment_present_value(p,1)/expected,1,places=14)
    def test_deployment_at_zero_and_zero_cost(self):
        self.assertEqual(deployment_present_value(ModelParams(deployment_cost=.5,discount=1e308,learning_rate=1e308),0),.5)
        self.assertEqual(deployment_present_value(ModelParams(),.2),0)
    def test_conversion_rejects_cost_underflow(self):
        with self.assertRaisesRegex(ValueError,'announcement_cost.*underflow'):
            rescale_experiment(ModelParams(announcement_cost=1e-200),DecisionBounds(announcement_upper=None),.15,1e-100,1)
    def test_conversion_avoids_intermediate_product_overflow(self):
        p=ModelParams(growth=1e300)
        q,b,r=rescale_experiment(p,DecisionBounds(),.15,1e100,1e100)
        self.assertAlmostEqual(q.growth/p.growth,1,places=14)
    def test_conversion_avoids_intermediate_squared_ratio_overflow(self):
        p=ModelParams(growth=0,margin_x=0,margin_y=0,announcement_cost=1e-300)
        q,b,r=rescale_experiment(p,DecisionBounds(announcement_upper=None),0,1e200,1)
        self.assertAlmostEqual(q.announcement_cost/1e100,1,places=14)
    def test_conversion_rejects_positive_growth_loss(self):
        with self.assertRaisesRegex(ValueError,'growth.*underflow'):
            rescale_experiment(ModelParams(growth=1e-300),DecisionBounds(),.15,1e100,1)
    def test_positive_tiny_intensity_is_interior(self):
        r=optimize(ModelParams(announcement_cost=1e6),'RF')
        self.assertGreater(r['announcement'],0);self.assertEqual(r['announcement_active'],'interior')
    def test_active_labels_are_unit_invariant(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12)
        a=optimize(p,'RL');q,b,r=rescale_experiment(p,DecisionBounds(),.15,1e-9,1)
        c=optimize(q,'RL',b,r)
        self.assertEqual((a['delay_active'],a['announcement_active']),(c['delay_active'],c['announcement_active']))
        self.assertAlmostEqual(a['payoff'],c['payoff'],places=13)
    def test_singleton_delay_active_is_fixed(self):
        r=optimize(ModelParams(),'DL',DecisionBounds(delay_lower=.1,delay_upper=.1))
        self.assertEqual(r['delay_active'],'fixed')
    def make_manifest(self,path):
        write_json(path/'config.json',{});return manifest(path,{},104,'test')
    def test_manifest_source_binding_opt_in(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r=self.make_manifest(p);r['source_sha256']['model.py']='0'*64;write_json(p/'manifest.json',r)
            self.assertTrue(verify_manifest(p)['valid'])
            self.assertFalse(verify_manifest(p,current_source_hashes())['valid'])
    def test_manifest_rejects_extra_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.make_manifest(p);write_json(p/'extra.json',{})
            self.assertFalse(verify_manifest(p)['valid'])
    def test_manifest_rejects_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);self.make_manifest(p);(p/'config.json').unlink()
            self.assertFalse(verify_manifest(p)['valid'])
    def test_manifest_configuration_cross_check(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r=self.make_manifest(p);r['config']={'a':1};r['config_sha256']=canonical_hash(r['config']);write_json(p/'manifest.json',r)
            self.assertFalse(verify_manifest(p)['valid'])
    def test_manifest_bad_schema_is_controlled(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for value in [[],{'artifacts_sha256':None},{'artifacts_sha256':{},'source_sha256':{}}]:
                write_json(p/'manifest.json',value);self.assertFalse(verify_manifest(p)['valid'])
    def test_verify_cli_bad_schema_no_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            write_json(Path(td)/'manifest.json',{'artifacts_sha256':None})
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()) as err:code=main(['verify',td])
            self.assertEqual(code,2);self.assertNotIn('Traceback',err.getvalue())
    def test_manifest_unsafe_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);r=self.make_manifest(p);r['artifacts_sha256']['../outside']='0'*64;write_json(p/'manifest.json',r)
            self.assertFalse(verify_manifest(p)['valid'])

if __name__=='__main__':unittest.main()

class BenchmarkSummaryTests(unittest.TestCase):
    def test_gaps_use_best_of_all_repeats(self):
        from entrysignallab.benchmark import summarize_optimizer_trials
        trials=[]
        for method,values in [('a',[1.,3.]),('b',[2.,2.])]:
            for rep,v in enumerate(values):
                trials.append({'case':0,'method':method,'repeat':rep,'payoff':v,'seconds':rep+1.,'delay':.1,'announcement':0.,'evaluations':10,'solver_success':rep==0})
        rows=summarize_optimizer_trials(trials);a,b=rows
        self.assertEqual(a['payoff'],3.);self.assertEqual(a['selected_repeat'],1)
        self.assertEqual(a['gap_to_best_observed'],0);self.assertEqual(b['gap_to_best_observed'],1)
        self.assertEqual(a['successful_repeats'],1);self.assertEqual(a['median_seconds'],1.5)
