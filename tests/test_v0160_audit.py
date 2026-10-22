"""Regression behavior for the A05/A06 follow-up audit."""
from dataclasses import replace
from decimal import Decimal,localcontext
from fractions import Fraction
from math import isclose,ulp
import json,unittest
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff,compare
from entrysignallab.sampling import wilson_interval
from entrysignallab.solver import _envelope_root_candidates,NumericalError

def market(scale=1e-12):
    return ModelParams(growth=.1/scale,margin_x=.25/scale,margin_y=.25/scale,growth_end=.3*scale,
        horizon=scale,learning_rate=10/scale,deployment_cost=.01)

def tiny_upper(total,confidence):
    # z = sqrt(pi/2)*c*(1+O(c*c)); at c<=1e-8 its omitted correction
    # is smaller than binary64 rounding. Keep z*z/total in Decimal.
    with localcontext() as ctx:
        ctx.prec=120
        pi=Decimal('3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628034825342117067982148086513282306647')
        c=Decimal.from_float(confidence);squared=pi*c*c/2
        return float(squared/(Decimal(total)+squared))

class FollowupAudit(unittest.TestCase):
    def test_A05_default_tiny_time_not_attained(self):
        self.assertEqual(optimize(market(),'RL',DecisionBounds(announcement_upper=None),0)['status'],'no_finite_joint_optimum')
    def test_A05_supremum_dominates_finite_witness(self):
        p=market();r=optimize(p,'RL',DecisionBounds(announcement_upper=None),0)
        self.assertGreater(r['supremum'],payoff(p,'RL',1.5e-13,1e15))
    def test_A05_null_controls(self):
        r=optimize(market(),'RL',DecisionBounds(announcement_upper=None),0)
        self.assertEqual([r[k] for k in ['delay','announcement','payoff']],[None,None,None])
    def test_A05_partial_domain_supremum(self):
        p=market();b=DecisionBounds(delay_lower=1e-13,announcement_upper=None);r=optimize(p,'RL',b,0)
        self.assertGreater(r['supremum'],payoff(p,'RL',1.5e-13,1e15))
    def test_A05_rankability_withheld(self):
        r=compare(market(),DecisionBounds(announcement_upper=None),0,tie_tolerance=0)
        self.assertFalse(r['all_rankable']);self.assertEqual(r['co_best'],[]);self.assertEqual(r['preferred_with_outside_option'],[])
    def test_A05_ordinary_loose_tolerance(self):
        r=optimize(market(1.),'RL',DecisionBounds(announcement_upper=None,tolerance=1.),0)
        self.assertEqual(r['status'],'no_finite_joint_optimum')
    def test_A05_time_scale_invariance(self):
        for a in [1e-250,1e-100,1e-12,1.,1e12,1e100,1e250]:
            with self.subTest(scale=a):
                r=optimize(market(a),'RL',DecisionBounds(announcement_upper=None),0)
                self.assertEqual(r['status'],'no_finite_joint_optimum')
                self.assertTrue(isclose(r['supremum'],.0006778594099196,rel_tol=1e-10))
    def test_A05_root_diagnostics_are_serializable(self):
        r=optimize(market(),'RL',DecisionBounds(announcement_upper=None),0)
        self.assertTrue(r['envelope_root_diagnostics']);json.dumps(r,allow_nan=False)
        for row in r['envelope_root_diagnostics']:
            self.assertLess(row['initial_lower'],r['supremum_delay']);self.assertLess(r['supremum_delay'],row['initial_upper'])
    def test_A05_unresolved_boundary_rejects(self):
        a=1.;b=float(np.nextafter(a,2.));root=(Fraction(a)+Fraction(b))/2
        with self.assertRaises(NumericalError):_envelope_root_candidates(lambda t:Fraction(t)-root,a,b,1.)
    def test_A05_requires_sign_bracket(self):
        with self.assertRaises(NumericalError):_envelope_root_candidates(lambda t:t+1,0.,1.,1.)
    def test_A05_true_maturity_retained(self):
        p=ModelParams(deployment_cost=.05,learning_rate=1.)
        r=optimize(p,'RL',DecisionBounds(announcement_upper=None),0)
        self.assertEqual(r['status'],'attained_joint_optimum');self.assertEqual(r['delay'],p.growth_end)
    def test_A05_singleton_endpoints_retained(self):
        p=market()
        for t in [0.,p.growth_end]:
            r=optimize(p,'RL',DecisionBounds(delay_lower=t,delay_upper=t,announcement_upper=None),0)
            self.assertIsNotNone(r['payoff']);self.assertEqual(r['delay'],t)
    def test_A06_small_confidence_precision(self):
        got=wilson_interval(0,10,1e-16)[1]
        self.assertTrue(isclose(got,tiny_upper(10,1e-16),rel_tol=1e-12))
    def test_A06_representable_interval_not_zero(self):
        self.assertGreater(wilson_interval(0,10,1e-17)[1],0)
    def test_A06_very_small_confidence(self):
        self.assertTrue(isclose(wilson_interval(0,10,1e-50)[1],tiny_upper(10,1e-50),rel_tol=1e-12))
    def test_A06_subnormal_positive_endpoint(self):
        self.assertLessEqual(abs(wilson_interval(0,10,1e-160)[1]-tiny_upper(10,1e-160)),2*ulp(0.))
    def test_A06_default_95_percent(self):
        self.assertTrue(isclose(wilson_interval(0,10)[1],.2775327998628892,rel_tol=1e-14))
    def test_A06_half_confidence_continuity(self):
        a=wilson_interval(0,10,float(np.nextafter(.5,0.)))[1];b=wilson_interval(0,10,.5)[1]
        self.assertTrue(isclose(a,b,rel_tol=1e-14))
    def test_A06_true_underflow_still_zero(self):
        self.assertEqual(wilson_interval(0,10,ulp(0.)),[0.,0.])
    def test_A06_true_interior_collapse_retained(self):
        self.assertEqual(wilson_interval(1,2,1e-17),[.5,.5])
    def test_A06_numpy_counts(self):
        self.assertEqual(wilson_interval(np.int64(0),np.int64(10),1e-17),wilson_interval(0,10,1e-17))
    def test_A06_empty_sample(self):self.assertIsNone(wilson_interval(0,0,1e-17))
    def test_A06_invalid_confidence(self):
        for c in [0.,1.,-1.,True,float('nan')]:
            with self.assertRaises(ValueError):wilson_interval(0,10,c)
    def test_A06_large_count_positive_subnormal(self):
        got=wilson_interval(0,10**290,1e-16)[1];expected=tiny_upper(10**290,1e-16)
        self.assertGreater(got,0.);self.assertLessEqual(abs(got-expected),2*ulp(0.))
    def test_A06_confidence_monotonicity(self):
        values=[wilson_interval(0,10,c)[1] for c in [1e-160,1e-50,1e-17,1e-16,1e-8,.1,.5,.95]]
        self.assertTrue(all(a<b for a,b in zip(values,values[1:])))
    def test_A06_complement_symmetry(self):
        for k in [0,1,5,9,10]:
            x=wilson_interval(k,10,.25);y=wilson_interval(10-k,10,.25)
            self.assertTrue(isclose(x[0],1-y[1],abs_tol=2e-16));self.assertTrue(isclose(x[1],1-y[0],abs_tol=2e-16))

if __name__=='__main__':unittest.main()
