"""Regression cases for the six confirmed v0.9.0 audit findings."""
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from decimal import Decimal,localcontext
from itertools import islice
from statistics import NormalDist
import hashlib,json,math,sys,unittest,io
from contextlib import redirect_stdout,redirect_stderr
from entrysignallab.cli import main
from entrysignallab.workflow import write_json
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,demand,payoff
from entrysignallab.sampling import SamplingPlan,linear_quantiles,wilson_interval
from entrysignallab.workflow import prepare_sweep,prepare_uncertainty,uncertainty,manifest,verify_manifest
from entrysignallab.batch import run_batch
from entrysignallab.locking import DirectoryLock


def inventory(path):
    result={}
    for p in path.rglob('*'):
        if not p.is_file():continue
        if p.name.endswith('.entrysignal.lock'):
            # Windows byte-range locks deliberately deny reads by other handles.
            # Retain identity/size/mtime checks instead of reading the locked byte.
            s=p.stat();value=('lock',s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        else:value=hashlib.sha256(p.read_bytes()).hexdigest()
        result[str(p.relative_to(path))]=value
    return result


def decimal_quantiles(values,qs):
    with localcontext() as c:
        c.prec=1000;v=sorted(Decimal.from_float(x) for x in values);out=[]
        for q in qs:
            h=Decimal.from_float(q)*(len(v)-1);i=int(h);f=h-i
            out.append(float(v[i]*(1-f)+v[min(i+1,len(v)-1)]*f))
        return out


class AuditV0100(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.p=ModelParams();self.b=DecisionBounds(scouting_points=3,announcement_upper=0)
    def sweep(self,axes,workers=1):
        return prepare_sweep(self.p,self.b,.15,axes,batch={'workers':workers,'checkpoint_every':1})
    def interrupted(self,path,meta,tasks,config):
        def stop(n):
            if n==1:raise RuntimeError('intentional stop')
        with self.assertRaises(RuntimeError):run_batch(path,self.p,self.b,.15,meta,tasks,config,progress_callback=stop)
    def changed_axes(self,config,workers=1,values=None):
        m,t=self.sweep({'growth':[.1,.11,.12]},workers);out=self.root/'run';self.interrupted(out,m,t,config)
        before=inventory(out);m2,t2=self.sweep({'growth':values or [.7,.8,.9]},workers)
        with self.assertRaises(ValueError):run_batch(out,self.p,self.b,.15,m2,t2,config,resume=True)
        self.assertEqual(before,inventory(out))
        r=run_batch(out,self.p,self.b,.15,m,t,config,resume=True);self.assertEqual(r['batch_execution']['resume_prefix_cases'],1)
    def test_R01_empty_config(self):self.changed_axes({})
    def test_R01_partial_config(self):self.changed_axes({'label':'audit'})
    def test_R01_full_config(self):self.changed_axes({'axes':{'growth':[.1,.11,.12]}})
    def test_R01_two_workers(self):self.changed_axes({},2)
    def test_R01_order_identity(self):self.changed_axes({},values=[.12,.11,.1])
    def test_R01_duplicates_preserved(self):
        m,t=self.sweep({'growth':[.1,.1,.2]});self.assertEqual(m['axes']['growth'],[.1,.1,.2]);self.assertEqual([x['changes']['growth'] for x in t()],[.1,.1,.2])
    def test_R01_axis_key_order(self):
        a,_=self.sweep({'growth':[.1],'network':[.2]});b,_=self.sweep({'network':[.2],'growth':[.1]});self.assertEqual(a,b)
    def test_R01_complete_prefix_empty_factory(self):
        m,t=self.sweep({'growth':[.1,.11]});out=self.root/'run';run_batch(out,self.p,self.b,.15,m,t,{})
        r=run_batch(out,self.p,self.b,.15,m,lambda:iter([]),{},resume=True);self.assertEqual(r['batch_execution']['resume_prefix_cases'],2)
    def quantiles(self,values):
        qs=[0.,.05,.25,.5,.75,.95,1.];got=linear_quantiles(values,qs);ref=decimal_quantiles(values,qs)
        for a,b in zip(got,ref):self.assertTrue(math.isclose(a,b,rel_tol=3e-15,abs_tol=1e-320),(a,b))
        self.assertEqual(got,sorted(got));self.assertTrue(all(min(values)<=v<=max(values) for v in got))
    def test_R02_opposite_extremes(self):self.quantiles([-1.7e308,1.7e308])
    def test_R02_multiple_points(self):self.quantiles([1.6e308,-1.7e308,-1e307,0.,1e307])
    def test_R02_positive_extremes(self):self.quantiles([1.6e308,1.7e308])
    def test_R02_negative_extremes(self):self.quantiles([-1.7e308,-1.6e308])
    def test_R02_duplicates(self):self.quantiles([1.7e308]*4)
    def test_R02_ordinary(self):
        v=[-3.,4.,1.,4.,9.];self.quantiles(v);np.testing.assert_allclose(linear_quantiles(v,[.05,.5,.95]),np.quantile(v,[.05,.5,.95]))
    def test_R02_empty_and_invalid(self):
        for v,q in [([],[.5]),([float('inf')],[.5]),([1.],[1.1])]:
            with self.assertRaises(ValueError):linear_quantiles(v,q)
    def test_R02_actual_payoff_summary(self):
        p=ModelParams(growth=1,network=0,growth_end=1,horizon=3)
        r=uncertainty(p,self.b,0,{'margin_x':[0,1e308],'deployment_cost':[0,1.7e308]},n=2,seed=2,correlation={'names':['margin_x','deployment_cost'],'matrix':[[1,-1],[-1,1]]})
        self.assertEqual(r['failed_samples'],0)
        for st in ['RF','RL','DF','DL']:
            v=[x['payoff'] for x in r['rows'] if x['strategy']==st];ref=decimal_quantiles(v,[.05,.5,.95]);got=r['payoff_summaries'][st]['quantiles_05_50_95']
            np.testing.assert_allclose(got,ref,rtol=5e-15)
    def extreme_params(self):return ModelParams(growth=1,network=1e100,growth_end=1e100,horizon=1e100,quality_ratio=1e300,margin_x=1e300)
    def test_R03_representable_weighted_stock(self):
        p=self.extreme_params();x,y=demand(p,'DL',p.horizon,1)
        with localcontext() as c:
            c.prec=200;D=lambda x:Decimal.from_float(float(x));ref=D(p.growth)*(D(p.growth_end)-1)/(1+D(p.quality_ratio)*(1+D(p.network)*D(p.growth)))
        self.assertGreater(x,0);self.assertTrue(math.isclose(x,float(ref),rel_tol=3e-12));self.assertTrue(math.isclose(y,p.horizon,rel_tol=3e-12))
    def test_R03_vector_and_scalar(self):
        p=self.extreme_params();ts=np.array([[0.,1.],[1e50,1e100]]);x,y=demand(p,'RL',ts,1)
        for i in np.ndindex(ts.shape):self.assertEqual((x[i],y[i]),demand(p,'RL',ts[i],1))
    def test_R03_conservation(self):
        t=np.linspace(0,1,51)
        for st in ['RF','RL','DF','DL']:
            x,y=demand(self.p,st,t,.15,.2 if st.startswith('R') else 0);np.testing.assert_allclose(x+y,self.p.growth*np.minimum(t,self.p.growth_end),rtol=5e-15,atol=1e-17)
    def test_R03_integral_payoff(self):
        p=self.extreme_params();x,_=demand(p,'DL',p.horizon,1);value=(x*.5)*p.horizon*p.margin_x
        self.assertTrue(math.isclose(value,payoff(p,'DL',1),rel_tol=3e-12))
    def test_R03_zero_growth(self):
        x,y=demand(replace(self.p,growth=0),'RF',[0,.2,1],.15,.2);self.assertTrue(np.array_equal(x,[0,0,0]));self.assertTrue(np.array_equal(y,[0,0,0]))
    def test_R03_true_overflow(self):
        p=ModelParams(growth=1e308,growth_end=10,horizon=10)
        with self.assertRaises(ValueError):demand(p,'DF',10,10)
    def corr(self,names=None):return {'names':names or ['growth_end','horizon'],'matrix':[[1,1],[1,1]]}
    def test_R04_equal_joint_domain(self):
        r=uncertainty(self.p,self.b,.15,{'growth_end':[.3,.6],'horizon':[.3,.6]},n=3,correlation=self.corr());self.assertEqual(r['failed_samples'],0);self.assertEqual(r['domain_preflight_issues'],[])
    def test_R04_independent_crossing_rejected(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth_end':[.3,.6],'horizon':[.3,.6]})
    def test_R04_explicit_le_ge(self):
        for relation in ['le','ge']:
            m,t=prepare_uncertainty(self.p,self.b,.15,{'growth_end':[.3,.6],'horizon':[.3,.6]},n=8,correlation=self.corr(),constraints=[{'left':'growth_end','relation':relation,'right':'horizon'}]);self.assertTrue(all(x['sampling_error'] is None for x in t()))
    def test_R04_different_marginals_conservative(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth_end':[.3,.6],'horizon':[.4,.7]},correlation=self.corr())
    def test_R04_near_perfect_not_proven(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth_end':[.3,.6],'horizon':[.3,.6]},correlation={'names':['growth_end','horizon'],'matrix':[[1,.999999],[.999999,1]]})
    def test_R04_singular_three_variables(self):
        ranges={'growth_end':[.3,.6],'horizon':[.3,.6],'margin_x':[.2,.5]};c={'names':list(ranges),'matrix':[[1,1,.5],[1,1,.5],[.5,.5,1]]};plan=SamplingPlan(self.p,ranges,correlation=c)
        self.assertTrue(all((d:=plan.draw(i))['growth_end']==d['horizon'] for i in range(100)))
    def test_R04_order_replay(self):
        r={'growth_end':[.3,.6],'horizon':[.3,.6]};a=SamplingPlan(self.p,r,correlation=self.corr());b=SamplingPlan(self.p,dict(reversed(list(r.items()))),correlation=self.corr(['horizon','growth_end']))
        self.assertEqual([a.draw(i) for i in range(10)],[b.draw(i) for i in range(10)])
    def test_R05_parent_active(self):
        parent=self.root/'run';parent.mkdir();before=inventory(parent)
        with DirectoryLock(parent):
            with self.assertRaises(ValueError):
                with DirectoryLock(parent/'child'):pass
        self.assertEqual(before,inventory(parent))
    def test_R05_child_active(self):
        parent=self.root/'run';child=parent/'child'
        with DirectoryLock(child):
            before=inventory(parent)
            with self.assertRaises(ValueError):
                with DirectoryLock(parent):pass
            self.assertEqual(before,inventory(parent))
    def test_R05_completed_parent(self):
        m,t=self.sweep({'growth':[.1]});parent=self.root/'run'
        with DirectoryLock(parent) as lease:
            run_batch(parent,self.p,self.b,.15,m,t,{},lock=lease);manifest(parent,{},104,'sweep')
        before=inventory(parent)
        with self.assertRaises(ValueError):
            with DirectoryLock(parent/'child'):pass
        self.assertEqual(before,inventory(parent));self.assertTrue(verify_manifest(parent)['valid'])
    def test_R05_completed_child(self):
        m,t=self.sweep({'growth':[.1]});parent=self.root/'run';child=parent/'child';run_batch(child,self.p,self.b,.15,m,t,{})
        before=inventory(parent)
        with self.assertRaises(ValueError):
            with DirectoryLock(parent):pass
        self.assertEqual(before,inventory(parent))
    def test_R05_sibling_leases(self):
        with DirectoryLock(self.root/'a'):
            with DirectoryLock(self.root/'b') as lease:lease.assert_owned(self.root/'b')
    def test_R05_symlink_alias(self):
        actual=self.root/'actual';actual.mkdir();alias=self.root/'alias'
        try:alias.symlink_to(actual,target_is_directory=True)
        except OSError:self.skipTest('symlinks unavailable')
        with DirectoryLock(actual):
            with self.assertRaises(ValueError):
                with DirectoryLock(alias/'child'):pass
    def cli_child_denied(self,command,active=False):
        parent=self.root/'parent';parent.mkdir();cfg=self.root/'config.json';write_json(cfg,{'bounds':{'scouting_points':3,'announcement_upper':0}})
        args=[command,'--out',str(parent/'child')]
        if command!='benchmark':args+=['--config',str(cfg)]
        if not active:manifest(parent,{},104,'audit')
        before=inventory(parent)
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            if active:
                with DirectoryLock(parent):code=main(args)
            else:code=main(args)
        self.assertEqual(code,2);self.assertEqual(before,inventory(parent))
    def test_R05_audit_cli_completed_parent(self):self.cli_child_denied('audit')
    def test_R05_optimize_cli_active_parent(self):self.cli_child_denied('optimize',True)
    def test_R05_reproduce_cli_completed_parent(self):self.cli_child_denied('reproduce')
    def test_R05_benchmark_cli_completed_parent(self):self.cli_child_denied('benchmark')
    def test_R06_maximal_confidence(self):
        confidence=float(np.nextafter(1.,0.));z=-NormalDist().inv_cdf((1-confidence)/2);half=z/(2*math.sqrt(2+z*z));np.testing.assert_allclose(wilson_interval(1,2,confidence),[.5-half,.5+half],rtol=1e-13)
    def test_R06_default(self):np.testing.assert_allclose(wilson_interval(1,2),[.09453120573423074,.9054687942657693],rtol=1e-14)
    def test_R06_tiny_confidence(self):
        a,b=wilson_interval(1,2,float(np.nextafter(0.,1.)));self.assertEqual([a,b],[.5,.5])
    def test_R06_extreme_counts(self):
        for n in [1,2,1000]:
            for k in [0,n]:
                a,b=wilson_interval(k,n,float(np.nextafter(1.,0.)));self.assertTrue(0<=a<=k/n<=b<=1)
    def test_R06_empty_and_invalid(self):
        self.assertIsNone(wilson_interval(0,0))
        for args in [(1,0,.95),(0,1,1),(0,1,0),(True,1,.95)]:
            with self.assertRaises(ValueError):wilson_interval(*args)

if __name__=='__main__':unittest.main()
