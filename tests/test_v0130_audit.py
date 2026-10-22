"""Regression cases for the five v0.12.0 audit findings."""
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import json,math,subprocess,sys,unittest
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,compare,demand,payoff,payoff_grid,revenues,shares
from entrysignallab.model import decisions,announcement_gradient
from entrysignallab.solver import compare_results
from entrysignallab.workflow import load_config,read_json,write_json
from entrysignallab.research import default_research_kernel,optimize_research,ResearchKernel,ModelCapabilities

class V0130Audit(unittest.TestCase):
    def setUp(self):self.p=ModelParams();self.b=DecisionBounds()
    def rows(self,values):return [{'strategy':s,'payoff':v,'local_quality_passed':True} for s,v in zip(['RF','RL','DF','DL'],values)]
    def config(self,source,reader=load_config):
        with TemporaryDirectory() as td:
            p=Path(td)/'config.json';p.write_text(source);return reader(p)
    def test_A01_int64_ranking(self):
        r=compare_results(self.rows([np.int64(2**63-1),np.int64(-(2**63-1)),np.int64(0),np.int64(-1)]),0)
        self.assertEqual(r['co_best'],['RF']);self.assertEqual(r['preferred_with_outside_option'],['RF']);json.dumps(r,allow_nan=False)
    def test_A01_float32_gap(self):
        x=np.float32(3e38);r=compare_results(self.rows([x,-x,-x,-x]),0)
        self.assertEqual(r['entry_payoff_gap'],float(x)-float(-x));self.assertEqual(r['entry_payoff_gap_diagnostic']['representation'],'finite');json.dumps(r)
    def test_A01_uint64(self):
        r=compare_results(self.rows([np.uint64(0),np.uint64(2**64-1),np.uint64(1),np.uint64(2)]),0)
        self.assertEqual(r['co_best'],['RL'])
    def test_A01_native_result_types(self):
        r=compare_results(self.rows([np.float64(4),np.float32(3),np.int32(2),Fraction(1,1)]))
        self.assertTrue(all(type(v['payoff']) is float for v in r['results']))
    def test_A01_input_not_mutated(self):
        rows=self.rows([np.int64(4),3.,2.,1.]);r=compare_results(rows)
        self.assertIs(type(rows[0]['payoff']),np.int64);self.assertIsNot(r['results'][0],rows[0])
    def test_A01_custom_optimizer(self):
        rows=self.rows([np.int64(2**63-1),np.int64(-(2**63-1)),np.int64(0),np.int64(-1)])
        r=compare(self.p,tie_tolerance=0,optimizer=lambda p,s,b,r:next(x for x in rows if x['strategy']==s));self.assertEqual(r['co_best'],['RF'])
    def test_A01_true_binary64_overflow(self):
        r=compare_results(self.rows([sys.float_info.max,-sys.float_info.max,-sys.float_info.max,-sys.float_info.max]),0)
        self.assertEqual(r['co_best'],['RF']);self.assertIsNone(r['entry_payoff_gap']);self.assertEqual(r['entry_payoff_gap_diagnostic']['representation'],'outside_float_range')
    def test_A01_null_and_numpy_bool(self):
        rows=self.rows([1.,None,0.,-1.]);rows[0]['local_quality_passed']=np.bool_(True)
        r=compare_results(rows);self.assertFalse(r['all_rankable']);self.assertIsNone(r['all_local_quality_passed']);json.dumps(r)
    def test_A01_boolean_payoff(self):
        with self.assertRaises(ValueError):compare_results(self.rows([True,2.,1.,0.]))
    def test_A01_underflow_payoff(self):
        with self.assertRaises(ValueError):compare_results(self.rows([Fraction(1,10**500),2.,1.,0.]))
    def test_A02_negative_json_underflow(self):
        with self.assertRaisesRegex(ValueError,'underflows'):self.config('{"params":{"deployment_cost":-1e-400}}')
    def test_A02_positive_json_underflow(self):
        with self.assertRaisesRegex(ValueError,'underflows'):self.config('{"params":{"growth":1e-400}}')
    def test_A02_lexical_mantissa(self):
        for x in ['1.000e-999','-0.001e-999','0.00000000000001E-999','1e-99999999999999999999']:
            with self.subTest(x=x),self.assertRaises(ValueError):self.config('{"params":{"growth":'+x+'}}')
    def test_A02_exact_zero(self):
        for x in ['0e-400','-0e-400','0.000E99999999999999999999','-0.0e-99999']:
            with self.subTest(x=x):self.assertEqual(self.config('{"params":{"growth":'+x+'}}')[1].growth,0.)
    def test_A02_minimum_subnormal(self):self.assertEqual(self.config('{"params":{"growth":5e-324}}')[1].growth,math.ulp(0.))
    def test_A02_overflow(self):
        with self.assertRaises(ValueError):self.config('{"params":{"growth":1e999}}')
    def test_A02_duplicate_keys(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):self.config('{"params":{"growth":0.1,"growth":0.2}}')
    def test_A02_nonfinite_constant(self):
        with self.assertRaises(ValueError):self.config('{"params":{"growth":NaN}}')
    def test_A02_integer_semantics(self):
        seed=10**100+1;r=self.config(json.dumps({'seed':seed}));self.assertIs(type(r[4]),int);self.assertEqual(r[4],seed)
    def test_A02_string_literal_untouched(self):self.assertEqual(self.config('{"label":"1e-400"}')[0]['label'],'1e-400')
    def test_A02_archive_reader_underflow(self):
        with self.assertRaises(ValueError):self.config('{"x":-1e-400}',read_json)
    def test_A02_archive_roundtrip(self):
        with TemporaryDirectory() as td:
            p=Path(td)/'x.json';write_json(p,{'x':math.ulp(0.),'n':10**100});self.assertEqual(read_json(p),{'x':math.ulp(0.),'n':10**100})
    def cli(self,source):
        with TemporaryDirectory() as td:
            p=Path(td)/'config.json';out=Path(td)/'output';p.write_text(source)
            r=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(p),'--out',str(out)],capture_output=True,text=True)
            return r.returncode,out.exists(),r.stderr
    def test_A02_cli_negative(self):self.assertEqual(self.cli('{"params":{"deployment_cost":-1e-400}}')[:2],(2,False))
    def test_A02_cli_positive(self):self.assertEqual(self.cli('{"params":{"growth":1e-400}}')[:2],(2,False))
    def test_A02_cli_exact_zero(self):self.assertEqual(self.cli('{"params":{"growth":0e-400}}')[:2],(0,True))
    def tiny(self):
        v=np.longdouble('1e-400')
        if not(v!=0 and float(v)==0):self.skipTest('host longdouble is not wider than binary64')
        return v
    def test_A03_negative_scalar_time(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',-self.tiny(),.1)
    def test_A03_negative_vector_time(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',np.array([-self.tiny()]),.1)
    def test_A03_negative_matrix_time(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',np.array([[-self.tiny(),.2]],dtype=np.longdouble),.1)
    def test_A03_positive_time_underflow(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',np.array([self.tiny()]),.1)
    def test_A03_grid_negative_delay(self):
        with self.assertRaises(ValueError):payoff_grid(self.p,'DL',np.array([-self.tiny()]),[0.])
    def test_A03_grid_positive_delay(self):
        with self.assertRaises(ValueError):payoff_grid(self.p,'DL',np.array([self.tiny()]),[0.])
    def test_A03_grid_silent_intensity(self):
        with self.assertRaises(ValueError):payoff_grid(self.p,'DL',[.1],np.array([self.tiny()]))
    def test_A03_grid_negative_intensity(self):
        with self.assertRaises(ValueError):payoff_grid(self.p,'RL',[.1],np.array([-self.tiny()]))
    def test_A03_discounted_silent(self):
        with self.assertRaises(ValueError):payoff_grid(replace(self.p,discount=.4),'DL',[.1],np.array([self.tiny()]))
    def test_A03_fraction_time_underflow(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',[Fraction(1,10**500)],.1)
    def test_A03_fraction_object_time(self):
        a=demand(self.p,'DL',[Fraction(1,8),Fraction(1,4)],.1);b=demand(self.p,'DL',[.125,.25],.1)
        for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
    def test_A03_minimum_subnormal(self):
        v=math.ulp(0.);demand(self.p,'DL',[v],0.);self.assertTrue(np.isfinite(payoff_grid(self.p,'DL',[v],[0.])).all())
    def test_A03_negative_subnormal(self):
        with self.assertRaises(ValueError):demand(self.p,'DL',[-math.ulp(0.)],.1)
    def test_A03_shapes_empty_integer(self):
        for t in [np.array([],dtype=float),np.array([[0,1],[1,0]],dtype=np.uint64)]:
            for x in demand(self.p,'DL',t,.1):self.assertEqual(x.shape,t.shape)
    def test_A03_complex_rejection(self):
        for t in [.2+0j,np.array([.2+0j]),np.array([.2+0j],dtype=object)]:
            with self.subTest(t=t),self.assertRaises(ValueError):demand(self.p,'DL',t,.1)
    def test_A03_boolean_string_rejection(self):
        for t in [[True],['0.2']]:
            with self.subTest(t=t),self.assertRaises(ValueError):demand(self.p,'DL',t,.1)
    def test_A03_grid_budget(self):
        with self.assertRaises(ValueError):payoff_grid(self.p,'RL',np.zeros(1001),np.zeros(1001))
    def test_A04_all_strategies_shapes(self):
        for st in ['RF','RL','DF','DL']:
            for times in [.2,[.2,.3],np.array([[.2,.3]])]:
                with self.subTest(st=st,times=times):
                    for a,b in zip(demand(self.p,st,times,Fraction(1,8)),demand(self.p,st,times,.125)):np.testing.assert_array_equal(a,b)
    def test_A04_decisions_return_unchanged(self):self.assertIsNone(decisions(self.p,'DL',Fraction(1,8),0.))
    def test_A04_scalar_api_correspondence(self):
        for st in ['RF','RL','DF','DL']:
            d=Fraction(1,8) if st.startswith('R') else Fraction(0)
            self.assertEqual(payoff(self.p,st,Fraction(1,8),d),payoff(self.p,st,.125,float(d)))
            self.assertEqual(revenues(self.p,st,Fraction(1,8),d),revenues(self.p,st,.125,float(d)))
            self.assertEqual(shares(self.p,st,Fraction(1,8),d),shares(self.p,st,.125,float(d)))
    def test_A04_numpy_controls(self):
        t=np.float32(.125);d=np.float32(.25)
        self.assertEqual(payoff(self.p,'RL',t,d),payoff(self.p,'RL',float(t),float(d)))
        np.testing.assert_array_equal(demand(self.p,'RL',[.2,.3],t,d),demand(self.p,'RL',[.2,.3],float(t),float(d)))
    def test_A04_gradient(self):self.assertEqual(announcement_gradient(self.p,'RL',Fraction(1,8),Fraction(1,4)),announcement_gradient(self.p,'RL',.125,.25))
    def test_A04_bad_control_still_rejected(self):
        for t in [Fraction(-1,8),Fraction(1,10**500),.1+0j]:
            with self.subTest(t=t),self.assertRaises(ValueError):demand(self.p,'DL',[.2,.3],t)
    def research(self,change=None,p=None,b=None,st='RL'):
        p=p or self.p;b=b or replace(self.b,announcement_upper=None);k=default_research_kernel();r=optimize_research(k,p,st,b,.15)
        if change:r.update(change)
        return optimize_research(replace(k,conditional_solver=lambda *a:dict(r)),p,st,b,.15)
    def test_A05_attained_status(self):
        with self.assertRaises(ValueError):self.research({'status':'attained_joint_optimum'})
    def test_A05_profile_status(self):
        with self.assertRaises(ValueError):self.research({'status':'profile_optimum'})
    def test_A05_false_value(self):
        with self.assertRaises(ValueError):self.research({'supremum':1000.})
    def test_A05_negative_position(self):
        with self.assertRaises(ValueError):self.research({'supremum_delay':-.1})
    def test_A05_outside_position(self):
        with self.assertRaises(ValueError):self.research({'supremum_delay':1000.})
    def test_A05_inside_wrong_position(self):
        with self.assertRaises(ValueError):self.research({'supremum_delay':.2})
    def test_A05_missing_value(self):
        with self.assertRaises(ValueError):self.research({'supremum':None})
    def test_A05_missing_position(self):
        with self.assertRaises(ValueError):self.research({'supremum_delay':None})
    def test_A05_missing_status(self):
        with self.assertRaises(ValueError):self.research({'status':None})
    def test_A05_original_null(self):
        for st in ['RF','RL']:self.assertIsNone(self.research(st=st)['payoff'])
    def test_A05_alternative_equal_location(self):self.assertEqual(self.research({'supremum_delay':math.ulp(0.)})['supremum_delay'],math.ulp(0.))
    def test_A05_quality_settings_do_not_relax(self):
        with self.assertRaises(ValueError):self.research({'supremum':1000.},b=DecisionBounds(announcement_upper=None,payoff_atol=1e9,payoff_rtol=1e9))
    def test_A05_small_scale(self):
        with self.assertRaises(ValueError):self.research({'supremum':0.},p=replace(self.p,margin_x=1e-280))
    def test_A05_RF_unsupported_metadata(self):
        with self.assertRaises(ValueError):self.research({'supremum':1.},st='RF')
    def test_A05_boundary_attained(self):
        p=replace(self.p,deployment_cost=.05,learning_rate=1)
        r=optimize_research(default_research_kernel(),p,'RL',replace(self.b,announcement_upper=None),0.)
        self.assertEqual(r['status'],'attained_joint_optimum');self.assertEqual(r['delay'],p.growth_end)
    def test_A05_finite_spurious_metadata(self):
        k=default_research_kernel();r={'strategy':'DL','delay':.1,'announcement':0.,'payoff':payoff(self.p,'DL',.1),'supremum':1000.}
        with self.assertRaises(ValueError):optimize_research(replace(k,conditional_solver=lambda *a:r),self.p,'DL',self.b,.15)
    def test_A05_custom_model_owns_semantics(self):
        result={'strategy':'custom','payoff':None,'delay':None,'announcement':None,'attainment':'not_attained','status':'custom_open_limit','supremum':-1.,'supremum_delay':-5.}
        k=ResearchKernel(ModelCapabilities('custom','1',False,False),lambda *a:0.,lambda *a:None,lambda *a:None,lambda *a:dict(result),lambda p,s,b,r,v:b=={'open':True})
        self.assertEqual(optimize_research(k,{},'custom',{'open':True})['supremum_delay'],-5.)
    def test_A05_literal_true_callback(self):
        k=replace(default_research_kernel(),validate_solution=lambda *a:np.bool_(True))
        with self.assertRaises(ValueError):optimize_research(k,self.p,'DL',self.b,.15)

if __name__=='__main__':unittest.main()
