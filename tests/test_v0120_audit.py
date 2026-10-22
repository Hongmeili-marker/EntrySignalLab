"""Regression coverage for all five confirmed v0.11.0 audit findings."""
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace,asdict
from decimal import Decimal,localcontext,MAX_EMAX,MIN_EMIN
from fractions import Fraction
from statistics import NormalDist
import json,math,unittest
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,payoff,optimize,compare,rescale_experiment
from entrysignallab.model import finite_number
from entrysignallab.batch import run_batch
from entrysignallab.workflow import prepare_sweep,prepare_uncertainty,uncertainty,read_json
from entrysignallab.solver import compare_results
from entrysignallab.research import default_research_kernel,optimize_research,ResearchKernel,ModelCapabilities
from entrysignallab.sampling import wilson_interval

def wilson_reference(k,n,confidence=.95):
    with localcontext() as c:
        c.prec=1200;c.Emax=MAX_EMAX;c.Emin=MIN_EMIN
        N=Decimal(n);K=Decimal(k);p=K/N;z=Decimal.from_float(-NormalDist().inv_cdf((1-confidence)/2));den=1+z*z/N
        center=(p+z*z/(2*N))/den;half=z*(p*(1-p)/N+z*z/(4*N*N)).sqrt()/den
        return [max(0.,float(center-half)),min(1.,float(center+half))]

class AuditV0120(unittest.TestCase):
    def setUp(self):
        self.p=ModelParams();self.b=DecisionBounds(scouting_points=3,announcement_upper=0)
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def batch(self,order,workers=1,resume=False,suffix=False):
        meta,factory=prepare_sweep(self.p,self.b,.15,{'growth':[.1,.11]},batch={'workers':workers,'checkpoint_every':1});tasks=list(factory());out=self.root/'run'
        if resume:
            def stop(n):
                if n==1:raise RuntimeError('intentional interruption')
            with self.assertRaises(RuntimeError):run_batch(out,self.p,self.b,.15,meta,factory,{},progress_callback=stop)
        seq=[tasks[i] if isinstance(i,int) and not isinstance(i,bool) and 0<=i<2 else {**tasks[0],'case_index':i} for i in order]
        return out,lambda:run_batch(out,self.p,self.b,.15,meta,lambda:iter(seq),{},resume=resume)
    def bad_batch(self,order,workers=1,resume=False):
        out,call=self.batch(order,workers,resume)
        with self.assertRaises(ValueError):call()
        self.assertNotEqual(read_json(out/'batch_progress.json')['state'],'completed')
    def test_A01_middle_duplicate_serial(self):self.bad_batch([0,0,1])
    def test_A01_tail_duplicate_serial(self):self.bad_batch([0,1,1])
    def test_A01_middle_duplicate_parallel(self):self.bad_batch([0,0,1],2)
    def test_A01_tail_duplicate_parallel(self):self.bad_batch([0,1,1],2)
    def test_A01_tail_duplicate_resume(self):self.bad_batch([0,1,1],resume=True)
    def test_A01_prefix_duplicate_resume(self):self.bad_batch([0,0,1],resume=True)
    def test_A01_tail_duplicate_parallel_resume(self):self.bad_batch([0,1,1],2,True)
    def test_A01_negative_index(self):self.bad_batch([-1,0,1])
    def test_A01_boolean_index(self):self.bad_batch([False,1])
    def test_A01_float_index(self):self.bad_batch([0.,1])
    def test_A01_missing_case(self):self.bad_batch([0])
    def test_A01_extra_index(self):self.bad_batch([0,1,2])
    def test_A01_full_resume(self):
        out,call=self.batch([0,1],resume=True);self.assertEqual(call()['batch_execution']['resume_prefix_cases'],1)
    def test_A01_suffix_resume(self):
        out,call=self.batch([1],resume=True);self.assertEqual(call()['completed_cases'],2)
    def test_A01_valid_two_workers(self):
        out,call=self.batch([0,1],2);self.assertEqual(call()['completed_cases'],2)
    def test_A01_complete_empty_factory(self):
        m,t=prepare_sweep(self.p,self.b,.15,{'growth':[.1]});out=self.root/'run';run_batch(out,self.p,self.b,.15,m,t,{})
        self.assertEqual(run_batch(out,self.p,self.b,.15,m,lambda:iter([]),{},resume=True)['completed_cases'],1)
    def normalized(self,dtype,field):
        b=replace(self.b,**{field:dtype(1e-8)});b.validate(self.p);self.assertIs(type(getattr(b,field)),float)
        json.dumps(asdict(b),allow_nan=False);r=compare(self.p,b,.15);self.assertEqual(r['local_quality_status'],'pass')
        self.assertTrue(all(type(x['local_quality_passed']) is bool for x in r['results']));json.dumps(r,allow_nan=False)
    def test_A02_atol_float64(self):self.normalized(np.float64,'payoff_atol')
    def test_A02_atol_float32(self):self.normalized(np.float32,'payoff_atol')
    def test_A02_rtol_float64(self):self.normalized(np.float64,'payoff_rtol')
    def test_A02_rtol_float32(self):self.normalized(np.float32,'payoff_rtol')
    def test_A02_all_bound_float_fields(self):
        b=DecisionBounds(delay_lower=np.float32(0),delay_upper=np.float64(.2),announcement_upper=np.float32(0),tolerance=np.float64(1e-10),payoff_atol=np.float32(1e-10),payoff_rtol=np.float64(1e-8))
        self.assertTrue(all(type(getattr(b,n)) is float for n in ['delay_lower','delay_upper','announcement_upper','tolerance','payoff_atol','payoff_rtol']))
    def test_A02_uncertainty(self):
        b=replace(self.b,payoff_atol=np.float64(1e-10));v=uncertainty(self.p,b,.15,{'growth':[.1,.11]},n=2);self.assertEqual(v['quality_status_counts']['pass'],2);json.dumps(v,allow_nan=False)
    def test_A02_batch_serial(self):
        b=replace(self.b,payoff_rtol=np.float32(1e-8));m,t=prepare_sweep(self.p,b,.15,{'growth':[.1,.11]});v=run_batch(self.root/'run',self.p,b,.15,m,t,{});self.assertEqual(v['quality_status_counts']['pass'],2)
    def test_A02_batch_parallel(self):
        b=replace(self.b,payoff_atol=np.float64(1e-10));m,t=prepare_sweep(self.p,b,.15,{'growth':[.1,.11]},batch={'workers':2});self.assertEqual(run_batch(self.root/'run',self.p,b,.15,m,t,{})['completed_cases'],2)
    def test_A02_explicit_numpy_bool(self):
        for value,expected in [(np.bool_(True),'pass'),(np.bool_(False),'fail')]:
            v=compare_results([{'strategy':s,'payoff':1.,'local_quality_passed':value} for s in ['RF','RL','DF','DL']]);self.assertEqual(v['local_quality_status'],expected);json.dumps(v)
    def test_A02_no_truthy_coercion(self):
        for value in [1,'true',None]:
            v=compare_results([{'strategy':s,'payoff':1.,'local_quality_passed':value} for s in ['RF','RL','DF','DL']]);self.assertEqual(v['local_quality_status'],'not_assessed')
    def test_A02_invalid_still_rejected(self):
        for b in [replace(self.b,tolerance=0),replace(self.b,payoff_atol=-1),replace(self.b,payoff_rtol=float('inf'))]:
            with self.assertRaises(ValueError):b.validate(self.p)
    def test_A03_fraction_positive(self):
        with self.assertRaisesRegex(ValueError,'underflow'):finite_number(Fraction(1,10**500),'value',positive=True)
    def test_A03_horizon(self):
        with self.assertRaises(ValueError):ModelParams(growth_end=0,horizon=Fraction(1,10**500))
    def test_A03_quality_ratio(self):
        with self.assertRaises(ValueError):ModelParams(quality_ratio=Fraction(1,10**500))
    def test_A03_growth_underflow(self):
        with self.assertRaises(ValueError):ModelParams(growth=Fraction(1,10**500))
    def test_A03_extended_positive(self):
        value=np.longdouble('1e-500')
        if value>0:
            with self.assertRaises(ValueError):ModelParams(growth_end=0,horizon=value)
        else:
            with self.assertRaises(ValueError):ModelParams(growth_end=0,horizon=value)
    def test_A03_huge_integer(self):
        with self.assertRaises(ValueError):ModelParams(growth=10**10000)
    def test_A03_minimum_subnormal(self):self.assertEqual(ModelParams(growth_end=0,horizon=float(np.nextafter(0,1))).horizon,float(np.nextafter(0,1)))
    def test_A03_normal_fraction(self):self.assertEqual(ModelParams(growth=Fraction(1,10)).growth,.1)
    def test_A03_zero_and_signed_zero(self):
        self.assertEqual(ModelParams(growth=-0.).growth,0.)
        with self.assertRaises(ValueError):ModelParams(horizon=0,growth_end=0)
    def test_A03_tiny_bounds(self):
        with self.assertRaises(ValueError):replace(self.b,tolerance=Fraction(1,10**500)).validate(self.p)
    def test_A03_unit_factor(self):
        with self.assertRaises(ValueError):rescale_experiment(self.p,self.b,.15,time_factor=Fraction(1,10**500))
    def research(self,state='attained',payoff_value='real',controls=True,st='DL',bounds=None,extra=None):
        v={'strategy':st,'delay':.1 if controls else None,'announcement':0 if controls else None,'payoff':payoff(self.p,st,.1) if payoff_value=='real' else payoff_value}
        if state is not None:v['attainment']=state
        v.update(extra or {});k=replace(default_research_kernel(),conditional_solver=lambda *a:v)
        return optimize_research(k,self.p,st,bounds or self.b,.15)
    def test_A04_finite_unattained(self):
        with self.assertRaises(ValueError):self.research('not_attained')
    def test_A04_unknown_state(self):
        with self.assertRaises(ValueError):self.research('unknown_state')
    def test_A04_omitted_is_candidate(self):self.assertEqual(self.research(None)['attainment'],'candidate')
    def test_A04_attained(self):self.assertEqual(self.research()['attainment'],'attained')
    def test_A04_candidate(self):self.assertEqual(self.research('candidate')['attainment'],'candidate')
    def test_A04_false_unattained(self):
        with self.assertRaises(ValueError):self.research('not_attained',None,False)
    def test_A04_finite_cap_false_unattained(self):
        with self.assertRaises(ValueError):self.research('not_attained',None,False,'RF')
    def test_A04_genuine_unattained(self):
        for st in ['RF','RL']:
            r=optimize_research(default_research_kernel(),self.p,st,replace(self.b,announcement_upper=None),.15);self.assertEqual(r['attainment'],'not_attained')
    def test_A04_conflicting_status(self):
        with self.assertRaises(ValueError):self.research(extra={'status':'no_finite_joint_optimum'})
    def test_A04_nonfinite_supremum(self):
        with self.assertRaises(ValueError):self.research(extra={'supremum':float('nan')})
    def test_A04_missing_controls(self):
        k=replace(default_research_kernel(),conditional_solver=lambda p,s,b,r:{'strategy':s,'payoff':None,'attainment':'not_attained'})
        with self.assertRaises(ValueError):optimize_research(k,self.p,'RF',replace(self.b,announcement_upper=None),.15)
    def test_A04_custom_unattained_owned(self):
        k=ResearchKernel(ModelCapabilities('toy','1',False,False),lambda *a:1.,lambda *a:None,lambda *a:None,
            lambda p,s,b,r:{'strategy':s,'delay':None,'announcement':None,'payoff':None,'attainment':'not_attained'},lambda p,s,b,r,v:b=={'open':True})
        self.assertEqual(optimize_research(k,{},'toy',{'open':True})['attainment'],'not_attained')
    def wilson(self,k,n,c=.95):
        v=wilson_interval(k,n,c);ref=wilson_reference(k,n,c)
        for a,b in zip(v,ref):self.assertLessEqual(abs(a-b),2*math.ulp(b),(v,ref))
    def test_A05_original(self):
        self.wilson(10**25,10**325);v=wilson_interval(10**25,10**325);self.assertLess(v[0],v[1])
    def test_A05_subnormal_reciprocal(self):self.wilson(10**25,10**320)
    def test_A05_subnormal_endpoint(self):self.wilson(10**5,10**325)
    def test_A05_large_balanced(self):self.wilson(10**324,10**325)
    def test_A05_zero_and_full(self):
        for k in [0,10**325]:self.wilson(k,10**325)
    def test_A05_enormous_integer(self):self.assertEqual(wilson_interval(0,10**10000),[0.,0.])
    def test_A05_confidence_extremes(self):
        for c in [np.nextafter(1.,0.),np.nextafter(0.,1.)]:self.wilson(10**25,10**325,float(c))
    def test_A05_numpy_retained(self):
        for dtype,n in [(np.int32,32768),(np.int64,2**31),(np.uint64,2**64-1)]:
            self.assertEqual(wilson_interval(dtype(0),dtype(n)),wilson_interval(0,n))

if __name__=='__main__':unittest.main()
