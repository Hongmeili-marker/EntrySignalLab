"""Regression coverage for the six v0.10.0 findings; independent Decimal checks."""
import unittest,math,warnings
from dataclasses import replace
from decimal import Decimal,localcontext
from statistics import NormalDist
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,demand,payoff,rescale_experiment,compare
from entrysignallab.sampling import wilson_interval,linear_quantiles
from entrysignallab.research import ResearchKernel,ModelCapabilities,default_research_kernel,optimize_research,evaluate_research
from entrysignallab.solver import compare_results,optimize
from entrysignallab.workflow import sweep,summarize_sweep,uncertainty,prepare_uncertainty,execute_case,summarize_uncertainty

def oracle(values,qs):
    with localcontext() as c:
        c.prec=1200;v=sorted(Decimal.from_float(float(x)) for x in values);out=[]
        for q in qs:
            h=(len(v)-1)*q;i=int(h);f=Decimal.from_float(h-i)
            out.append(float(v[i]*(1-f)+v[min(i+1,len(v)-1)]*f))
        return out

class AuditV0110(unittest.TestCase):
    def setUp(self):self.p=ModelParams();self.b=DecisionBounds(scouting_points=3,announcement_upper=0)
    def wilson(self,dtype,n):
        z=-NormalDist().inv_cdf(.025)
        for k in [0,n//2,n]:
            with warnings.catch_warnings():
                warnings.simplefilter('error');v=wilson_interval(dtype(k),dtype(n))
            with localcontext() as c:
                c.prec=100;D=Decimal;nn=D(n);p=D(k)/nn;zz=D.from_float(z)**2;den=1+zz/nn
                center=(p+zz/(2*nn))/den;half=(zz*(p*(1-p)/nn+zz/(4*nn*nn))).sqrt()/den
                ref=[max(0.,float(center-half)),min(1.,float(center+half))]
            np.testing.assert_allclose(v,ref,rtol=8e-15,atol=1e-17)
    def test_A01_int32_32768(self):self.wilson(np.int32,32768)
    def test_A01_int32_65536(self):self.wilson(np.int32,65536)
    def test_A01_int64(self):self.wilson(np.int64,2147483648)
    def test_A01_uint64(self):self.wilson(np.uint64,2**64-1)
    def test_A01_python_int(self):self.wilson(int,32768)
    def test_A01_confidence_float32(self):self.assertEqual(wilson_interval(1,2,np.float32(.9)),wilson_interval(1,2,float(np.float32(.9))))
    def test_A01_huge_python_total(self):self.assertEqual(wilson_interval(0,10**10000),[0.,0.])
    def test_A01_empty(self):self.assertIsNone(wilson_interval(np.int64(0),np.int64(0)))
    def test_A01_high_confidence(self):self.assertLess(wilson_interval(0,100,np.nextafter(1.,0.))[1],1)
    def test_A01_tiny_confidence(self):self.assertEqual(wilson_interval(1,2,np.nextafter(0.,1.)),[.5,.5])
    def test_A01_invalid_counts(self):
        for k,n in [(True,3),(1,True),(-1,3),(4,3),(1.,3),(0,-1)]:
            with self.assertRaises(ValueError):wilson_interval(k,n)
    def bad(self,st,t,d,b=None,rival=.15):
        k=replace(default_research_kernel(),conditional_solver=lambda p,s,b,r:{'strategy':s,'delay':t,'announcement':d,'payoff':payoff(p,s,t,d),'attainment':'attained'})
        return optimize_research(k,self.p,st,b or self.b,rival)
    def test_A02_lower(self):
        with self.assertRaises(ValueError):self.bad('RL',.1,0,replace(self.b,delay_lower=.2))
    def test_A02_upper(self):
        with self.assertRaises(ValueError):self.bad('RL',.25,0,replace(self.b,delay_upper=.2))
    def test_A02_cap(self):
        with self.assertRaises(ValueError):self.bad('RL',.1,1)
    def test_A02_fixed_rival(self):
        with self.assertRaises(ValueError):self.bad('DF',.2,0)
    def test_A02_silent_intensity(self):
        with self.assertRaises(ValueError):self.bad('DL',.1,1)
    def test_A02_valid_boundary(self):self.assertEqual(self.bad('RL',.2,0,replace(self.b,delay_lower=.2))['delay'],.2)
    def test_A02_default_solver(self):
        for st in ['RF','RL','DF','DL']:
            r=optimize_research(default_research_kernel(),self.p,st,self.b,.15);self.assertEqual(r['payoff'],optimize(self.p,st,self.b,.15)['payoff'])
    def test_A02_missing_validator(self):
        k=replace(default_research_kernel(),validate_solution=None)
        with self.assertRaisesRegex(ValueError,'validate_solution'):optimize_research(k,self.p,'RL',self.b,.15)
    def test_A02_noncallable_validator(self):
        with self.assertRaises(ValueError):replace(default_research_kernel(),validate_solution=3).validate()
    def test_A02_custom_model_owns_bounds(self):
        params={'offset':2};bounds={'limit':7};seen=[]
        def validate(p,s,b,r,v):seen.append((p,s,b,r));return v['delay']<=b['limit'] and v['announcement']==r
        k=ResearchKernel(ModelCapabilities('toy','2',False,False),lambda p,s,t,d:t+p['offset'],lambda p:None,lambda p,s,t,d:None,
            lambda p,s,b,r:{'strategy':s,'delay':7,'announcement':r,'payoff':9},validate)
        self.assertEqual(optimize_research(k,params,'custom',bounds,4)['payoff'],9);self.assertIs(seen[0][2],bounds)
        with self.assertRaises(ValueError):optimize_research(k,params,'custom',{'limit':6},4)
    def test_A02_validator_requires_true(self):
        with self.assertRaises(ValueError):optimize_research(replace(default_research_kernel(),validate_solution=lambda *a:None),self.p,'DL',self.b,.15)
    def test_A02_objective_still_checked(self):
        k=replace(default_research_kernel(),conditional_solver=lambda p,s,b,r:{'strategy':s,'delay':.2,'announcement':0,'payoff':5})
        with self.assertRaisesRegex(ValueError,'payoff disagrees'):optimize_research(k,self.p,'DL',self.b,.15)
    def test_A02_unattained(self):self.assertIsNone(optimize_research(default_research_kernel(),self.p,'RF',replace(self.b,announcement_upper=None),.15)['payoff'])
    def test_A02_evaluation_only_unchanged(self):self.assertEqual(evaluate_research(default_research_kernel(),self.p,'DL',.1)['payoff'],payoff(self.p,'DL',.1))
    def converted(self,explicit=False):return rescale_experiment(self.p,replace(self.b,delay_upper=.2) if explicit else self.b,.15,12,1000)
    def test_A03_none(self):self.assertIsNone(self.converted()[1].delay_upper)
    def test_A03_explicit(self):self.assertAlmostEqual(self.converted(True)[1].delay_upper,2.4)
    def test_A03_roundtrip(self):
        for explicit in [False,True]:
            p,b,r=self.converted(explicit);pp,bb,rr=rescale_experiment(p,b,r,1/12,1/1000)
            self.assertEqual(bb.delay_upper is None,not explicit);self.assertAlmostEqual(pp.growth_end,self.p.growth_end);self.assertAlmostEqual(rr,.15)
    def test_A03_scaled_sweep(self):
        p,b,r=self.converted();rows=sweep(p,b,r,{'growth_end':[.2*12,.3*12]});self.assertEqual(summarize_sweep(rows)['completed_cases'],2)
    def test_A03_scaled_uncertainty(self):
        p,b,r=self.converted();self.assertEqual(uncertainty(p,b,r,{'growth_end':[.2*12,.3*12]},n=2)['completed_samples'],2)
    def test_A03_same_controls(self):
        p,b,r=self.converted()
        for st in ['RF','RL','DF','DL']:self.assertTrue(math.isclose(payoff(self.p,st,.15),payoff(p,st,r),rel_tol=2e-13,abs_tol=1e-15))
    def test_A03_explicit_still_restricts(self):
        p,b,r=self.converted(True)
        with self.assertRaises(ValueError):sweep(p,b,r,{'growth_end':[.18*12,.3*12]})
    def test_A04_complex_scalar(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',.2+2j,.15)
    def test_A04_numpy_complex_scalar(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',np.complex128(.2),.15)
    def test_A04_complex_vector(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            with self.assertRaises(ValueError):demand(self.p,'DL',np.array([.2+2j,.4+7j]),.15)
    def test_A04_complex_matrix(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',[[.2,.3],[.4+1j,.5]],.15)
    def test_A04_object_complex(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',np.array([.2+0j],dtype=object),.15)
    def test_A04_real_matrix(self):
        t=np.array([[0,.2],[.4,1]]);x,y=demand(self.p,'DL',t,.15)
        for i in np.ndindex(t.shape):self.assertEqual((x[i],y[i]),demand(self.p,'DL',float(t[i]),.15))
    def test_A04_real_integers(self):self.assertEqual(demand(self.p,'DL',1,.15),demand(self.p,'DL',1.,.15))
    def test_A04_bounds_still_checked(self):
        for t in [-1,float('nan'),float('inf'),self.p.horizon+1]:
            with self.assertRaises(ValueError):demand(self.p,'DL',t,.15)
    def test_A05_subnormal(self):
        u=float(np.nextafter(0,1));qs=[0.,.05,.25,.5,.75,.95,1.]
        for a,b in [(-1,2),(3,-2),(1,2),(-2,-1),(-1,1),(0,1),(0,-1)]:
            v=[a*u,b*u];self.assertEqual(linear_quantiles(v,qs),oracle(v,qs))
    def test_A05_multiple_points(self):
        u=float(np.nextafter(0,1));v=[-10*u,2*u,3*u,7*u];q=[.05,.25,.5,.75,.95];self.assertEqual(linear_quantiles(v,q),oracle(v,q))
    def test_A05_huge_endpoints(self):
        v=[-1.7e308,1.7e308];q=[0,.05,.5,.95,1];self.assertEqual(linear_quantiles(v,q),oracle(v,q))
    def test_A05_ordinary(self):
        v=[-3.,2.,4.,10.];q=[0,.05,.5,.95,1];self.assertEqual(linear_quantiles(v,q),oracle(v,q))
    def test_A05_actual_uncertainty(self):
        u=float(np.nextafter(0,1));p=ModelParams(growth=1,network=0,growth_end=1,horizon=3)
        r=uncertainty(p,self.b,0,{'margin_x':[0,4*u],'deployment_cost':[0,4*u]},n=2,seed=2,correlation={'names':['margin_x','deployment_cost'],'matrix':[[1,-1],[-1,1]]})
        for st in ['RF','RL','DF','DL']:
            v=[x['payoff'] for x in r['rows'] if x['strategy']==st];self.assertEqual(r['payoff_summaries'][st]['quantiles_05_50_95'],oracle(v,[.05,.5,.95]));self.assertEqual(r['payoff_summaries'][st]['quantiles_05_50_95'][1],0)
    def records(self,quality=True):return [{'strategy':s,'payoff':1.,'local_quality_passed':quality} for s in ['RF','RL','DF','DL']]
    def test_A06_pass(self):self.assertEqual(compare_results(self.records())['local_quality_status'],'pass')
    def test_A06_fail(self):
        r=self.records();r[0]['local_quality_passed']=False;x=compare_results(r);self.assertEqual(x['local_quality_status'],'fail');self.assertIs(x['all_local_quality_passed'],False)
    def test_A06_not_assessed(self):
        r=self.records();r[0].pop('local_quality_passed');x=compare_results(r);self.assertEqual(x['local_quality_status'],'not_assessed');self.assertIsNone(x['all_local_quality_passed']);self.assertTrue(x['all_rankable'])
    def test_A06_unattained(self):
        x=compare(self.p,replace(self.b,announcement_upper=None),.15);self.assertEqual(x['local_quality_status'],'not_assessed');self.assertEqual(x['local_quality_by_strategy']['RF'],'not_applicable');self.assertFalse(x['all_rankable'])
    def test_A06_fail_precedence(self):
        r=self.records();r[0]['payoff']=None;r[1]['local_quality_passed']=False;x=compare_results(r);self.assertEqual(x['local_quality_status'],'fail');self.assertFalse(x['local_quality_assessment_complete'])
    def test_A06_no_finite(self):
        r=self.records();[x.update(payoff=None) for x in r];self.assertEqual(compare_results(r)['local_quality_status'],'not_assessed')
    def test_A06_uncertainty_counts(self):
        r=uncertainty(self.p,replace(self.b,announcement_upper=None),.15,{'growth':[.1,.11]},n=2);self.assertEqual(r['quality_warning_samples'],0);self.assertEqual(r['quality_status_counts'],{'pass':0,'fail':0,'not_assessed':2});self.assertEqual(r['summary']['unrankable']['count'],2)
    def test_A06_sweep_counts(self):
        r=summarize_sweep(sweep(self.p,replace(self.b,announcement_upper=None),.15,{'growth':[.1,.11]}));self.assertEqual(r['quality_warning_cases'],0);self.assertEqual(r['quality_status_counts']['not_assessed'],2)
    def test_A06_real_failure_counts(self):
        m,t=prepare_uncertainty(self.p,self.b,.15,{'growth':[.1,.11]},n=2)
        def bad(*a):return {**optimize(*a),'local_quality_passed':False}
        r=summarize_uncertainty((execute_case(self.p,self.b,.15,x,m,bad) for x in t()),m);self.assertEqual(r['quality_warning_samples'],2);self.assertEqual(r['quality_status_counts']['fail'],2)
    def test_A06_config_failure_excluded(self):
        r=uncertainty(self.p,self.b,.15,{'growth_end':[.1,.1]},n=2,on_error='record');self.assertEqual(r['quality_status_counts'],{'pass':0,'fail':0,'not_assessed':0});self.assertEqual(r['quality_excluded_failed_samples'],2)

if __name__=='__main__':unittest.main()
