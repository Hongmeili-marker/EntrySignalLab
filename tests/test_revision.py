"""Regression tests for strict audit counterexamples and joint attainment."""
import contextlib,csv,io,json,tempfile,unittest
from pathlib import Path
from math import exp,isfinite
from unittest.mock import patch
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,payoff,shares,rescale_experiment
from entrysignallab.model import announcement_gradient,response_mass,revenues
from entrysignallab.solver import profile_announcement,checked_root,NumericalError
from entrysignallab.plots import resolve_plot_settings,profit_surface
from entrysignallab.cli import main

class RevisionTests(unittest.TestCase):
    def test_joint_unbounded_attained_maturity(self):
        p=ModelParams(deployment_cost=.05,learning_rate=1)
        r=optimize(p,'RL',DecisionBounds(announcement_upper=None))
        self.assertEqual(r['status'],'attained_joint_optimum')
        self.assertEqual(r['delay'],p.growth_end);self.assertEqual(r['announcement'],0)
        self.assertAlmostEqual(r['payoff'],-.05*exp(-.3))
        self.assertTrue(r['announcement_nonunique']);self.assertFalse(r['delay_nonunique'])
    def test_joint_boundary_rankable_at_zero_rival_lag(self):
        p=ModelParams(deployment_cost=.05,learning_rate=1)
        r=compare(p,DecisionBounds(announcement_upper=None),rival_delay=0)
        self.assertTrue(r['all_rankable']);self.assertEqual(r['co_best'],['RL','DL'])
        self.assertEqual(r['preferred_with_outside_option'],['no_entry'])
    def test_joint_right_limit_at_zero_is_not_attained(self):
        p=ModelParams();r=optimize(p,'RL',DecisionBounds(announcement_upper=None))
        self.assertEqual(r['status'],'no_finite_joint_optimum')
        self.assertEqual(r['supremum_delay'],0);self.assertIsNone(r['payoff'])
        self.assertGreater(r['supremum'],payoff(p,'RL',0))
    def test_joint_interior_supremum(self):
        p=ModelParams(growth_end=.9,deployment_cost=.01,learning_rate=12)
        r=optimize(p,'RL',DecisionBounds(announcement_upper=None))
        self.assertEqual(r['attainment'],'not_attained')
        self.assertGreater(r['supremum_delay'],0);self.assertLess(r['supremum_delay'],.9)
        ts=np.linspace(0,.9,10001)
        upper=max(p.margin_x*p.growth*response_mass(p,float(t))-.01*exp(-12*t) for t in ts)
        self.assertLess(abs(r['supremum']-upper),1e-9)
    def test_joint_discounted_envelope(self):
        p=ModelParams(discount=.8,deployment_cost=.07,learning_rate=.5)
        r=optimize(p,'RL',DecisionBounds(announcement_upper=None))
        upper=max(p.margin_x*p.growth*response_mass(p,float(t))-.07*exp(-1.3*t) for t in np.linspace(0,.3,5001))
        self.assertAlmostEqual(r['supremum'],upper,places=9)
    def test_joint_restricted_interval_cannot_reach_maturity(self):
        p=ModelParams(deployment_cost=.05,learning_rate=1)
        r=optimize(p,'RL',DecisionBounds(delay_lower=.1,delay_upper=.2,announcement_upper=None))
        self.assertEqual(r['status'],'no_finite_joint_optimum');self.assertEqual(r['supremum_delay'],.2)
    def test_singleton_zero_and_maturity_are_attained(self):
        for t in [0,.3]:
            r=optimize(ModelParams(),'RL',DecisionBounds(delay_lower=t,delay_upper=t,announcement_upper=None))
            self.assertEqual(r['delay'],t);self.assertIsNotNone(r['payoff']);self.assertFalse(r['delay_nonunique'])
    def test_zero_margin_delay_nonunique(self):
        for st in ['RL','DL']:
            r=optimize(ModelParams(margin_x=0),st)
            self.assertTrue(r['delay_nonunique']);self.assertEqual(r['payoff'],0)
    def test_singleton_delay_not_nonunique(self):
        r=optimize(ModelParams(growth=0),'RL',DecisionBounds(delay_lower=.1,delay_upper=.1))
        self.assertFalse(r['delay_nonunique'])
    def test_changing_cost_prevents_flat_delay(self):
        r=optimize(ModelParams(margin_x=0,deployment_cost=.01,learning_rate=1),'DL')
        self.assertFalse(r['delay_nonunique']);self.assertEqual(r['delay'],.3)
    def test_gradient_extreme_share_weights(self):
        p=ModelParams(growth=1e-150,network=1e150,quality_ratio=1e155)
        g=announcement_gradient(p,'RF',.15,0)
        self.assertTrue(isfinite(g));self.assertGreater(g,0)
        self.assertTrue(isfinite(optimize(p,'RF')['payoff']))
    def test_share_normalization_when_raw_weights_overflow(self):
        x,y=shares(ModelParams(network=1e300,growth=1e100),'RL',.2,1e100)
        self.assertTrue(isfinite(x+y));self.assertAlmostEqual(x+y,1,places=12)
    def test_tiny_positive_cost_has_finite_root(self):
        p=ModelParams(announcement_cost=1e-100)
        r=optimize(p,'RF',DecisionBounds(announcement_upper=None))
        self.assertTrue(isfinite(r['payoff']));self.assertGreater(r['announcement'],1e30)
        self.assertLess(abs(announcement_gradient(p,'RF',.15,r['announcement'])),1e-75)
    def test_tiny_cost_cli_no_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'c.json';c.write_text(json.dumps({'params':{'announcement_cost':1e-100},'bounds':{'announcement_upper':None}}))
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()) as err:
                code=main(['optimize','--config',str(c),'--out',str(Path(td)/'out')])
            self.assertEqual(code,0);self.assertNotIn('Traceback',err.getvalue())
    def test_root_failure_is_explicit(self):
        class Info: converged=False
        with patch('entrysignallab.solver.brentq',return_value=(.5,Info())):
            with self.assertRaises(NumericalError):checked_root(lambda x:x-.5,0,1,1e-10)
    def test_benchmark_validation_before_directory(self):
        with tempfile.TemporaryDirectory() as td:
            for flag,value in [('--grid-points','1'),('--seed','-1'),('--repeats','0'),('--accuracy-cases','0')]:
                out=Path(td)/flag[2:]
                with contextlib.redirect_stderr(io.StringIO()):code=main(['benchmark',flag,value,'--out',str(out)])
                self.assertEqual(code,2);self.assertFalse(out.exists())
    def test_reference_trajectory_respects_small_cap(self):
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'c.json';c.write_text(json.dumps({'bounds':{'announcement_upper':.1}}));out=Path(td)/'out'
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main(['reproduce','--config',str(c),'--out',str(out)]),0)
            with (out/'demand_trajectories.csv').open() as f: rows=list(csv.DictReader(f))
            self.assertTrue(all(float(x['announcement'])<=.1 for x in rows))
            settings=json.loads((out/'plot_settings.json').read_text())
            self.assertEqual(settings['trajectory_controls']['RF']['announcement'],.1)
    def test_invalid_plot_reference_before_directory(self):
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'c.json';c.write_text(json.dumps({'bounds':{'announcement_upper':.1},'plot':{'announcement':.2}}));out=Path(td)/'out'
            with contextlib.redirect_stderr(io.StringIO()):code=main(['reproduce','--config',str(c),'--out',str(out)])
            self.assertEqual(code,2);self.assertFalse(out.exists())
    def test_unbounded_surface_window_disclosed(self):
        settings=resolve_plot_settings(ModelParams(),DecisionBounds(announcement_upper=None),.15,{'surface_announcement_max':7})
        self.assertTrue(settings['surface_is_finite_window']);self.assertEqual(settings['surface_announcement_max'],7)
    def test_degenerate_surfaces_export(self):
        with tempfile.TemporaryDirectory() as td:
            for b in [DecisionBounds(announcement_upper=0),DecisionBounds(delay_lower=.1,delay_upper=.1)]:
                profit_surface(td,ModelParams(),b)
                self.assertTrue((Path(td)/'rl_payoff_surface.pdf').read_bytes().startswith(b'%PDF'))
    def test_time_and_consumer_units_preserve_values(self):
        p=ModelParams(discount=.7,announcement_cost=.0002,deployment_cost=.012,learning_rate=3,quality_ratio=1.8)
        q,b,rival=rescale_experiment(p,DecisionBounds(),.15,time_factor=12,consumer_factor=1000)
        for st in ['RF','RL','DF','DL']:
            delta=.4 if st.startswith('R') else 0
            self.assertAlmostEqual(payoff(p,st,.2,delta),payoff(q,st,2.4,delta*1000/12),places=12)
            np.testing.assert_allclose(shares(p,st,.2,delta),shares(q,st,2.4,delta*1000/12),rtol=1e-13)
        self.assertEqual(b.announcement_upper,2*1000/12);self.assertAlmostEqual(rival,1.8)
    def test_unit_rescaling_preserves_optimizer_value(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12,discount=.4,quality_ratio=1.6)
        q,b,rival=rescale_experiment(p,DecisionBounds(),.15,12,1000)
        a=optimize(p,'RL');c=optimize(q,'RL',b,rival)
        self.assertAlmostEqual(a['payoff'],c['payoff'],places=11)
    def test_invalid_unit_factor(self):
        with self.assertRaises(ValueError):rescale_experiment(ModelParams(),DecisionBounds(),.15,0,1)

if __name__=='__main__':unittest.main()
