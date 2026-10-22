"""Regression and rejection cases from the frozen v0.5.0 audit."""
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
import unittest,warnings,json,sys,io,contextlib
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,payoff,revenues,optimize,compare
from entrysignallab.cli import main
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from release_evidence import verify_experiment_spec

class RevenueScopeTests(unittest.TestCase):
    def params(self):return ModelParams(growth=1,growth_end=1,horizon=1e308,network=0,margin_x=1e-308,margin_y=1e308)
    def check(self,st):self.assertAlmostEqual(payoff(self.params(),st,0),.5,places=12)
    def test_rf_object_payoff(self):self.check('RF')
    def test_rl_object_payoff(self):self.check('RL')
    def test_df_object_payoff(self):self.check('DF')
    def test_dl_object_payoff(self):self.check('DL')
    def test_object_payoff_independent_of_rival_margin(self):
        p=self.params();self.assertEqual(payoff(p,'RL',.3),payoff(replace(p,margin_y=0),'RL',.3))
    def test_pair_revenue_still_requires_both_values(self):
        with self.assertRaisesRegex(ValueError,'revenue'):revenues(self.params(),'DL',0)
    def test_object_overflow_is_not_silenced(self):
        with self.assertRaisesRegex(ValueError,'object revenue'):payoff(replace(self.params(),margin_x=1e308),'DL',0)
    def test_compare_can_rank_finite_object_payoffs(self):
        r=compare(self.params(),DecisionBounds(announcement_upper=0),0);self.assertTrue(r['all_rankable']);self.assertEqual(set(r['co_best']),{'RF','RL','DF','DL'})
    def test_cli_evaluate_pair_overflow_is_controlled(self):
        with TemporaryDirectory() as td:
            p=Path(td)/'config.json';p.write_text(json.dumps({'params':self.params().__dict__}));err=io.StringIO()
            with contextlib.redirect_stderr(err),contextlib.redirect_stdout(io.StringIO()):code=main(['evaluate','--config',str(p),'--strategy','DL','--delay','0'])
            self.assertEqual(code,2);self.assertNotIn('Traceback',err.getvalue())

class NarrowMeshTests(unittest.TestCase):
    def check(self,st):
        b=DecisionBounds(delay_lower=.1,delay_upper=float(np.nextafter(.1,1.)),announcement_upper=0)
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning);r=optimize(ModelParams(),st,b)
        self.assertEqual(r['evaluations'],2);self.assertEqual(r['delay_refinement_intervals'],0);self.assertTrue(b.delay_lower<=r['delay']<=b.delay_upper)
    def test_adjacent_dl_endpoints(self):self.check('DL')
    def test_adjacent_rl_endpoints(self):self.check('RL')
    def test_subnormal_interval_has_no_fake_refinement(self):
        tiny=float(np.nextafter(0.,1.));p=ModelParams(growth_end=tiny,horizon=tiny,network=0)
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning);r=optimize(p,'DL',DecisionBounds(delay_upper=tiny),0)
        self.assertEqual(r['delay_refinement_intervals'],0);self.assertEqual(r['evaluations'],2)
    def test_multiple_ulps_keep_distinct_evaluations(self):
        hi=.1
        for _ in range(8):hi=float(np.nextafter(hi,1.))
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning);r=optimize(ModelParams(),'DL',DecisionBounds(delay_lower=.1,delay_upper=hi))
        self.assertEqual(r['evaluations'],9)

class RecipeTests(unittest.TestCase):
    def setup_record(self,d):
        (d/'examples').mkdir();p=d/'examples/a.json';p.write_text(json.dumps({'seed':7,'params':{'growth':.1}}))
        spec={'operation':'optimize','config_path':'examples/a.json'};r={'operation':'optimize','config':json.loads(p.read_text()),'seed':7};return p,spec,r
    def test_valid_recipe_binds_file(self):
        with TemporaryDirectory() as td:
            d=Path(td);p,s,r=self.setup_record(d);self.assertEqual(set(verify_experiment_spec(d,'case',r,s)),{'examples/a.json'})
    def test_wrong_operation_rejected(self):
        with TemporaryDirectory() as td:
            d=Path(td);p,s,r=self.setup_record(d);r['operation']='audit'
            with self.assertRaisesRegex(ValueError,'operation'):verify_experiment_spec(d,'case',r,s)
    def test_wrong_seed_rejected(self):
        with TemporaryDirectory() as td:
            d=Path(td);p,s,r=self.setup_record(d);r['seed']=8
            with self.assertRaisesRegex(ValueError,'seed'):verify_experiment_spec(d,'case',r,s)
    def test_wrong_record_config_rejected(self):
        with TemporaryDirectory() as td:
            d=Path(td);p,s,r=self.setup_record(d);r['config']['params']['growth']=.9
            with self.assertRaisesRegex(ValueError,'configuration'):verify_experiment_spec(d,'case',r,s)
    def test_changed_shipped_config_rejected(self):
        with TemporaryDirectory() as td:
            d=Path(td);p,s,r=self.setup_record(d);p.write_text(json.dumps({'seed':7,'params':{'growth':.9}}))
            with self.assertRaisesRegex(ValueError,'configuration'):verify_experiment_spec(d,'case',r,s)
    def test_inline_benchmark_recipe(self):
        spec={'operation':'benchmark','config':{'seed':104,'repeats':5}};r={'operation':'benchmark','config':dict(spec['config']),'seed':104}
        self.assertEqual(verify_experiment_spec(Path('.'),'benchmark',r,spec),{})
    def test_inline_benchmark_change_rejected(self):
        spec={'operation':'benchmark','config':{'seed':104,'repeats':5}};r={'operation':'benchmark','config':{'seed':104,'repeats':1},'seed':104}
        with self.assertRaisesRegex(ValueError,'configuration'):verify_experiment_spec(Path('.'),'benchmark',r,spec)
