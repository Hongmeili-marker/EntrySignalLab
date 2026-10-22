"""Scientific regression and independent validation. MIT License."""
import unittest, tempfile, json, io, contextlib
from pathlib import Path
from dataclasses import replace
from math import exp
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,demand,shares,payoff,revenues,optimize,compare
from entrysignallab.model import announcement_gradient
from entrysignallab.benchmark import reference_revenues
from entrysignallab.audit import source_audit
from entrysignallab.solver import profile_announcement
from entrysignallab.workflow import manifest,verify_manifest,write_json,load_config,sweep,uncertainty
from entrysignallab.cli import main

class ValidationTests(unittest.TestCase):
    def test_invalid_parameter_values(self):
        for name,value in [("growth",-1),("network",float("nan")),("growth_end",float("inf")),("discount",True),("quality_ratio",0),("horizon",0),("margin_x",".25")]:
            with self.subTest(name=name,value=value),self.assertRaises(ValueError):ModelParams(**{name:value})
    def test_growth_end_within_horizon(self):
        with self.assertRaises(ValueError):ModelParams(growth_end=2)
    def test_unknown_parameter(self):
        with self.assertRaises(TypeError):ModelParams.from_dict({"unknown":1})
    def test_invalid_decisions(self):
        for st,t,d in [("XX",0,0),("RL",.4,1),("RF",.1,-1),("DF",.1,1)]:
            with self.subTest(st=st,t=t,d=d),self.assertRaises(ValueError):shares(ModelParams(),st,t,d)
    def test_time_domain(self):
        for t in [-.1,1.1,float("nan")]:
            with self.subTest(t=t),self.assertRaises(ValueError):demand(ModelParams(),"DF",t,.1)
    def test_bounds_validation(self):
        for b in [DecisionBounds(delay_lower=.4),DecisionBounds(delay_upper=.31),DecisionBounds(announcement_upper=-1),DecisionBounds(scouting_points=True),DecisionBounds(tolerance=0)]:
            with self.subTest(bounds=b),self.assertRaises(ValueError):b.validate(ModelParams())
    def test_unknown_and_nonfinite_config(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"config.json"
            for text in ['{"unknown":1}','{"params":{"growth":NaN}}','{"seed":true}','{"params":{"growth":0.1,"growth":0.2}}']:
                p.write_text(text)
                with self.subTest(text=text),self.assertRaises(ValueError):load_config(p)

class DemandTests(unittest.TestCase):
    def test_mass_conservation(self):
        for st in ["RF","RL","DF","DL"]:
            p=ModelParams(quality_ratio=1.7);t=np.linspace(0,1,151)
            x,y=demand(p,st,t,.15,.4 if st[0]=="R" else 0)
            np.testing.assert_allclose(x+y,p.growth*np.minimum(t,p.growth_end),rtol=1e-14,atol=1e-15)
    def test_share_range_and_sum(self):
        for st in ["RF","RL","DF","DL"]:
            x,y=shares(ModelParams(quality_ratio=.4),st,.2,.7 if st[0]=="R" else 0)
            self.assertGreaterEqual(x,0);self.assertLessEqual(x,1);self.assertAlmostEqual(x+y,1)
    def test_zero_announcement_equivalence(self):
        p=ModelParams()
        for a,b in [("RF","DF"),("RL","DL")]:
            self.assertEqual(shares(p,a,.15,0),shares(p,b,.15,0));self.assertEqual(revenues(p,a,.15,0),revenues(p,b,.15,0))
    def test_simultaneous_entry(self):
        p=ModelParams(quality_ratio=2)
        for st in ["RF","RL","DF","DL"]:
            x,y=demand(p,st,.2,0,.5 if st[0]=="R" else 0)
            self.assertAlmostEqual(x,.02/3);self.assertAlmostEqual(y,.04/3)
    def test_follower_at_growth_end(self):
        p=ModelParams()
        self.assertEqual(revenues(p,"DL",p.growth_end)[0],0)
        self.assertAlmostEqual(revenues(p,"DF",p.growth_end)[0],.006375)
    def test_demand_continuity(self):
        p=ModelParams()
        for st in ["RF","RL","DF","DL"]:
            for t in [.15,.3]:
                a=demand(p,st,t-1e-9,.15,.2 if st[0]=="R" else 0)
                b=demand(p,st,t+1e-9,.15,.2 if st[0]=="R" else 0)
                np.testing.assert_allclose(a,b,atol=3e-10)
    def test_zero_growth_and_zero_growth_period(self):
        for p in [ModelParams(growth=0),ModelParams(growth_end=0)]:
            for st in ["RF","RL","DF","DL"]:self.assertEqual(revenues(p,st,0),(0.,0.))
    def test_independent_discounted_quadrature(self):
        for r in [0,1e-12,1e-5,.5,10]:
            p=ModelParams(discount=r,quality_ratio=1.6,horizon=2,growth_end=.8)
            for st in ["RF","RL","DF","DL"]:
                d=.7 if st[0]=="R" else 0
                np.testing.assert_allclose(revenues(p,st,.22,d),reference_revenues(p,st,.22,d),rtol=1e-10,atol=1e-12)
    def test_cost_present_value(self):
        p=ModelParams(discount=.7,announcement_cost=.002,deployment_cost=.01,learning_rate=3)
        revenue=revenues(p,"RL",.2,.4)[0]
        self.assertAlmostEqual(payoff(p,"RL",.2,.4),revenue-.002*.4*.4/2-.01*exp(-3.7*.2))
    def test_intensity_gradient_independent_difference(self):
        p=ModelParams(announcement_cost=.002)
        for st in ["RF","RL"]:
            t,d,h=.15,.4,1e-5
            numerical=(payoff(p,st,t,d+h)-payoff(p,st,t,d-h))/(2*h)
            self.assertAlmostEqual(numerical,announcement_gradient(p,st,t,d),places=10)

class SolverTests(unittest.TestCase):
    def test_no_cost_follower_at_zero(self):
        p=ModelParams();r=optimize(p,"DL")
        self.assertEqual(r["delay"],0);self.assertAlmostEqual(r["payoff"],.0031875)
    def test_first_cases_hold_rival_delay(self):
        for st in ["RF","DF"]:self.assertEqual(optimize(ModelParams(),st,rival_delay=.2)["delay"],.2)
    def test_positive_cost_intensity_stationarity(self):
        p=ModelParams(announcement_cost=.0002)
        r=optimize(p,"RF");self.assertGreater(r["announcement"],0);self.assertLess(r["announcement"],2)
        self.assertLess(r["announcement_stationarity_residual"],1e-10)
    def test_unbounded_positive_cost(self):
        p=ModelParams(announcement_cost=.00001)
        r=optimize(p,"RF",DecisionBounds(announcement_upper=None))
        self.assertTrue(np.isfinite(r["payoff"]));self.assertLess(r["announcement_stationarity_residual"],1e-9)
    def test_unbounded_cost_free_is_not_ranked(self):
        report=compare(ModelParams(),DecisionBounds(announcement_upper=None))
        self.assertFalse(report["all_rankable"]);self.assertEqual(report["co_best"],[])
        self.assertEqual(report["preferred_with_outside_option"],[])
        self.assertEqual(report["results"][0]["status"],"no_finite_announcement_optimum")
    def test_unbounded_zero_effect_is_degenerate(self):
        r=optimize(ModelParams(network=0),"RF",DecisionBounds(announcement_upper=None))
        self.assertTrue(r["announcement_nonunique"]);self.assertIsNotNone(r["payoff"])
    def test_zero_intensity_cap(self):
        r=optimize(ModelParams(),"RF",DecisionBounds(announcement_upper=0))
        self.assertEqual(r["announcement"],0);self.assertEqual(r["announcement_stationarity_residual"],0)
    def test_single_delay_bound(self):
        r=optimize(ModelParams(),"RL",DecisionBounds(delay_lower=.1,delay_upper=.1))
        self.assertEqual(r["delay"],.1)
    def test_plateau_is_nonunique(self):
        r=optimize(ModelParams(growth=0),"RL")
        self.assertTrue(r["delay_nonunique"]);self.assertEqual(r["delay"],0)
    def test_interior_product_launch(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12)
        r=optimize(p,"RL")
        self.assertGreater(r["delay"],0);self.assertLess(r["delay"],p.growth_end)
        for t in np.linspace(0,p.growth_end,101):
            d,_=profile_announcement(p,"RL",float(t),2)
            self.assertGreaterEqual(r["payoff"]+1e-10,payoff(p,"RL",float(t),d))
        self.assertFalse(r["equilibrium"]);self.assertFalse(r["globally_certified"])
    def test_no_entry_reference(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12)
        r=compare(p);self.assertEqual(r["co_best"],["RL"]);self.assertEqual(r["preferred_with_outside_option"],["no_entry"])
    def test_source_audit_regression(self):
        audit=source_audit();self.assertEqual(len(audit["checks"]),6)
        self.assertTrue(all(not c["pass"] for c in audit["checks"]))
        self.assertAlmostEqual(audit["printed_candidates"]["delay_RL"],11.764705882352942)
        self.assertAlmostEqual(audit["checks"][4]["from_demand"],.0031875)
    def test_source_assumption_guard(self):
        with self.assertRaises(ValueError):source_audit(ModelParams(discount=.1))

class WorkflowTests(unittest.TestCase):
    def test_plot_exports_are_complete(self):
        from entrysignallab.plots import trajectories
        with tempfile.TemporaryDirectory() as td:
            trajectories(td,ModelParams())
            pdf=Path(td)/"demand_trajectories.pdf"
            self.assertGreater(pdf.stat().st_size,1000);self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
            self.assertTrue(pdf.read_bytes().rstrip().endswith(b"%%EOF"))
            for ext in ["png","svg"]:self.assertGreater((Path(td)/("demand_trajectories."+ext)).stat().st_size,1000)
    def test_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"value.json";write_json(p,{"value":1});manifest(td,{"a":1},104,"test")
            self.assertTrue(verify_manifest(td)["valid"])
            p.write_text("changed");self.assertFalse(verify_manifest(td)["valid"])
    def test_manifest_rejects_unsafe_path(self):
        with tempfile.TemporaryDirectory() as td:
            record=manifest(td,{},1,"test");record["artifacts_sha256"]["../outside"]="fake";write_json(Path(td)/"manifest.json",record)
            self.assertFalse(verify_manifest(td)["valid"])
    def test_sweep_changes_inputs(self):
        rows=sweep(ModelParams(),DecisionBounds(),.15,{"network":[0,.85]})
        self.assertEqual(len(rows),8);self.assertEqual({r["network"] for r in rows},{0,.85})
    def test_repeated_uncertainty_is_identical(self):
        args=(ModelParams(),DecisionBounds(),.15,{"growth":[.08,.12]})
        a=uncertainty(*args,n=5,seed=104);b=uncertainty(*args,n=5,seed=104)
        self.assertEqual(a,b);self.assertEqual(sum(x["count"] for x in a["summary"].values()),5)
    def test_invalid_sweep_and_uncertainty(self):
        for axes in [{},{"bad":[1]},{"growth_end":[.1]}]:
            with self.subTest(axes=axes),self.assertRaises(ValueError):sweep(ModelParams(),DecisionBounds(),.15,axes)
        with self.assertRaises(ValueError):uncertainty(ModelParams(),DecisionBounds(),.15,{"growth":[1,0]})
    def test_cli_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            config=Path(td)/"config.json";write_json(config,{})
            out=Path(td)/"out";out.mkdir();(out/"keep.txt").write_text("keep")
            with contextlib.redirect_stderr(io.StringIO()):code=main(["optimize","--config",str(config),"--out",str(out)])
            self.assertEqual(code,2);self.assertEqual((out/"keep.txt").read_text(),"keep")
    def test_invalid_cli_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as td:
            config=Path(td)/"config.json";write_json(config,{"params":{"growth":-1}});out=Path(td)/"out"
            with contextlib.redirect_stderr(io.StringIO()):code=main(["optimize","--config",str(config),"--out",str(out)])
            self.assertEqual(code,2);self.assertFalse(out.exists())
    def test_cli_audit_and_verify(self):
        with tempfile.TemporaryDirectory() as td:
            config=Path(td)/"config.json";write_json(config,{})
            out=Path(td)/"out"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["audit","--config",str(config),"--out",str(out)]),0)
                self.assertEqual(main(["verify",str(out)]),0)
            self.assertTrue((out/"source_audit.json").is_file())

if __name__=="__main__":unittest.main()
