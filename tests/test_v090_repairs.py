"""Audit counterexamples and directory ownership across real processes."""
from pathlib import Path
from dataclasses import replace
from decimal import Decimal,localcontext
from threading import Thread,Event
from itertools import islice
from unittest.mock import patch
from contextlib import contextmanager,redirect_stdout,redirect_stderr
import hashlib,io,json,os,subprocess,sys,tempfile,time,unittest
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff_grid
from entrysignallab.solver import compare_results,NumericalError
from entrysignallab.workflow import uncertainty,prepare_sweep,prepare_uncertainty,manifest,verify_manifest,current_source_hashes
from entrysignallab.batch import run_batch,runtime_fingerprint
from entrysignallab.locking import DirectoryLock
from entrysignallab.cli import main


def decimal_zero_network(p,strategy,tau):
    with localcontext() as c:
        c.prec=100
        s,m,h,t,a=[Decimal.from_float(float(v)) for v in [p.growth,p.margin_x,p.growth_end,p.horizon,tau]]
        mass=(h-a)*(t-h)+(h-a)**2/2
        return m*s*(mass/2+(a*t-a*a/2 if strategy.endswith('F') else 0))


def snapshot(path):return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}


class Repairs(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=ModelParams();self.b=DecisionBounds(scouting_points=3)
    def tearDown(self):self.tmp.cleanup()
    def prepared(self):return prepare_sweep(self.p,self.b,.15,{'growth':[.1,.11,.12,.13]},batch={'checkpoint_every':1})
    def interrupted(self,path):
        meta,tasks=self.prepared()
        def stop(n):
            if n==1:raise RuntimeError('controlled interruption')
        with self.assertRaises(RuntimeError):run_batch(path,self.p,self.b,.15,meta,tasks,{},progress_callback=stop)
        return meta,tasks
    @contextmanager
    def owner(self,path):
        ready=self.root/'ready';ready.unlink(missing_ok=True)
        code="from pathlib import Path\nfrom entrysignallab.locking import DirectoryLock\nimport sys\nwith DirectoryLock(sys.argv[1]):\n Path(sys.argv[2]).write_text('ready')\n sys.stdin.read(1)\n"
        proc=subprocess.Popen([sys.executable,'-u','-c',code,str(path),str(ready)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            until=time.monotonic()+10
            while not ready.exists() and proc.poll() is None and time.monotonic()<until:time.sleep(.01)
            self.assertTrue(ready.exists(),'owner failed: '+str(proc.poll()))
            yield proc
        finally:
            if proc.poll() is None:proc.communicate('\n',timeout=10)
            else:proc.communicate(timeout=10)
    def test_negative_zero_matches_positive_zero(self):
        a=optimize(self.p,'DL',replace(self.b,delay_lower=-0.,max_evaluations=100));b=optimize(self.p,'DL',replace(self.b,max_evaluations=100))
        self.assertEqual(a,b);self.assertLessEqual(a['evaluations'],100)
    def test_signed_zero_lattice_is_bounded(self):
        hi=float(np.nextafter(0.,1.));p=ModelParams(growth=0,growth_end=hi,horizon=hi)
        for sign in [-0.,0.]:
            r=optimize(p,'DL',DecisionBounds(delay_lower=sign,delay_upper=hi,max_evaluations=1));self.assertEqual(r['evaluations'],1)
    def test_negative_zero_small_budget_rejects_promptly(self):
        with self.assertRaises(NumericalError):optimize(self.p,'DL',replace(self.b,delay_lower=-0.,max_evaluations=2))
    def test_negative_zero_cli_finishes(self):
        c=self.root/'config.json';c.write_text(json.dumps({'bounds':{'delay_lower':-0.,'scouting_points':3,'max_evaluations':1000}}))
        p=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(c),'--out',str(self.root/'out')],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
    def test_subnormal_grid_against_decimal(self):
        tiny=float(np.nextafter(0.,1.))
        for units in [1,2,3,7,31,1024]:
            h=tiny*units
            for multiple in [1,3]:
                p=ModelParams(growth=1e308,margin_x=1e308,network=0,growth_end=h,horizon=h*multiple)
                ts=[0,h/2,h]
                for st in ['RF','RL','DF','DL']:
                    values=payoff_grid(p,st,ts,[0])[0]
                    for tau,actual in zip(ts,values):
                        ref=float(decimal_zero_network(p,st,tau))
                        if ref==0:self.assertEqual(actual,0)
                        else:self.assertLess(abs(float(actual)-ref)/ref,2e-11)
    def test_subnormal_first_mover_maturity_half_is_preserved(self):
        h=float(np.nextafter(0.,1.));p=ModelParams(growth=1e308,margin_x=1e308,network=0,growth_end=h,horizon=h)
        self.assertLess(abs(payoff_grid(p,'RF',[h],[0])[0,0]/float(decimal_zero_network(p,'RF',h))-1),2e-11)
    def test_outside_option_ulp_comparisons_match_decimal(self):
        for outside in [1.,-1.,1e-300,-1e-300,1e308,-1e308]:
            for direction in [-np.inf,np.inf]:
                best=float(np.nextafter(outside,direction));ulp=abs(best-outside)
                for tol in [0.,ulp*.75,ulp,ulp*1.5]:
                    rows=[{'strategy':s,'payoff':best} for s in ['RF','RL','DF','DL']]
                    r=compare_results(rows,tol,outside)
                    with localcontext() as c:
                        c.prec=1000;difference=Decimal.from_float(best)-Decimal.from_float(outside);bound=Decimal.from_float(tol)
                    expected=['RF','RL','DF','DL'] if difference>bound else ['no_entry'] if difference<bound.copy_negate() else ['RF','RL','DF','DL','no_entry']
                    self.assertEqual(r['preferred_with_outside_option'],expected)
    def test_outside_option_overflow_keeps_classification(self):
        r=compare_results([{'strategy':s,'payoff':1e308} for s in ['RF','RL','DF','DL']],1e-8,-1e308)
        self.assertNotIn('no_entry',r['preferred_with_outside_option']);self.assertIsNone(r['outside_option_gap']);json.dumps(r,allow_nan=False)
    def test_all_rejected_attempts_are_counted(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[0,1]},n=1,on_error='record',constraints=[{'left':'growth','relation':'le','value':1e-15}],constraint_mode='resample',max_draw_attempts=3)
        self.assertEqual((r['draw_attempts'],r['accepted_draws'],r['rejected_draw_attempts'],r['sampling_numerical_failures'],r['exhausted_samples']),(3,0,3,0,1))
    def test_first_draw_acceptance_is_counted(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=2);self.assertEqual((r['draw_attempts'],r['accepted_draws'],r['rejected_draw_attempts']),(2,2,0))
    def test_recorded_constraint_rejection_is_not_a_retry(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[0,1]},n=1,on_error='record',constraints=[{'left':'growth','relation':'le','value':.1}])
        self.assertEqual((r['draw_attempts'],r['accepted_draws'],r['rejected_draw_attempts'],r['exhausted_samples']),(1,0,1,0))
    def test_retry_then_accept_counts_both_outcomes(self):
        with patch('entrysignallab.sampling.SamplingPlan.draw',side_effect=[{'growth':.2},{'growth':.05}]):
            r=uncertainty(self.p,self.b,.15,{'growth':[0,1]},n=1,on_error='record',constraints=[{'left':'growth','relation':'le','value':.1}],constraint_mode='resample',max_draw_attempts=3)
        self.assertEqual((r['draw_attempts'],r['accepted_draws'],r['rejected_draw_attempts']),(2,1,1))
    def test_sampling_numerical_failure_is_separate(self):
        with patch('entrysignallab.sampling.SamplingPlan.draw',side_effect=[{'growth':.2},ValueError('inverse transform failed')]):
            r=uncertainty(self.p,self.b,.15,{'growth':[0,1]},n=1,on_error='record',constraints=[{'left':'growth','relation':'le','value':.1}],constraint_mode='resample',max_draw_attempts=3)
        self.assertEqual((r['draw_attempts'],r['accepted_draws'],r['rejected_draw_attempts'],r['sampling_numerical_failures']),(2,0,1,1));self.assertEqual(r['failed_samples'],1)
    def test_optimization_failure_does_not_reject_accepted_draw(self):
        with patch('entrysignallab.workflow.compare',side_effect=ValueError('injected optimization failure')):
            r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=1,on_error='record')
        self.assertEqual((r['accepted_draws'],r['rejected_draw_attempts'],r['failed_samples']),(1,0,1))
    def test_self_constraints_preserve_draws_and_labels(self):
        a=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=3)
        for relation in ['le','ge']:
            b=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=3,constraints=[{'left':'growth','relation':relation,'right':'growth'}])
            self.assertEqual(a['rows'],b['rows']);self.assertEqual(a['summary'],b['summary'])
    def test_impossible_constraints_still_rejected(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},constraints=[{'left':'growth','relation':'le','value':.01}])
    def test_short_factory_cannot_complete(self):
        m,t=self.prepared();out=self.root/'short'
        with self.assertRaisesRegex(ValueError,'before requested'):run_batch(out,self.p,self.b,.15,m,lambda:islice(t(),2),{})
        progress=json.loads((out/'batch_progress.json').read_text());self.assertEqual((progress['state'],progress['processed_cases'],progress['requested_cases']),('interrupted',2,4));self.assertFalse((out/'sweep_summary.json').exists())
    def test_empty_factory_cannot_complete_new_run(self):
        m,t=self.prepared()
        with self.assertRaises(ValueError):run_batch(self.root/'empty',self.p,self.b,.15,m,lambda:iter([]),{})
    def test_extra_case_is_not_stored(self):
        m,t=self.prepared();out=self.root/'extra'
        def extra():
            yield from t();yield {'case_index':4,'changes':{'growth':.2},'sampling_attempts':1}
        with self.assertRaisesRegex(ValueError,'exceeds requested'):run_batch(out,self.p,self.b,.15,m,extra,{})
        r=run_batch(out,self.p,self.b,.15,m,t,{},resume=True);self.assertEqual(r['requested_cases'],4)
    def test_completed_prefix_accepts_empty_remaining_factory(self):
        m,t=self.prepared();out=self.root/'done';run_batch(out,self.p,self.b,.15,m,t,{})
        r=run_batch(out,self.p,self.b,.15,m,lambda:iter([]),{},resume=True);self.assertEqual(r['batch_execution']['processed_cases'],4)
    def test_resume_runtime_mismatch_preserves_checkpoint(self):
        out=self.root/'runtime';m,t=self.interrupted(out);before=snapshot(out)
        with patch('entrysignallab.batch.runtime_fingerprint',return_value={**runtime_fingerprint(),'numpy':'different'}),self.assertRaisesRegex(ValueError,'mismatch'):
            run_batch(out,self.p,self.b,.15,m,t,{},resume=True)
        self.assertEqual(snapshot(out),before)
        self.assertEqual(run_batch(out,self.p,self.b,.15,m,t,{},resume=True)['requested_cases'],4)
    def test_thread_overlap_is_rejected_without_mutation(self):
        out=self.root/'overlap';m,tasks=self.interrupted(out);paused=Event();release=Event();result={}
        def pause(n):
            if n==2:
                paused.set()
                if not release.wait(10):raise RuntimeError('coordination timeout')
        def first():
            try:result['summary']=run_batch(out,self.p,self.b,.15,m,tasks,{},resume=True,progress_callback=pause)
            except Exception as e:result['error']=str(e)
        t=Thread(target=first);t.start()
        try:
            self.assertTrue(paused.wait(10));before=snapshot(out)
            with self.assertRaisesRegex(ValueError,'already in use'):run_batch(out,self.p,self.b,.15,m,tasks,{},resume=True)
            self.assertEqual(before,snapshot(out))
        finally:release.set();t.join(10)
        self.assertFalse(t.is_alive());self.assertNotIn('error',result);manifest(out,{},104,'sweep');self.assertTrue(verify_manifest(out,current_source_hashes())['valid'])
    def test_real_process_competitor_is_rejected(self):
        out=self.root/'process';m,t=self.interrupted(out)
        with self.owner(out):
            before=snapshot(out)
            with self.assertRaisesRegex(ValueError,'already in use'):run_batch(out,self.p,self.b,.15,m,t,{},resume=True)
            self.assertEqual(before,snapshot(out))
        self.assertEqual(run_batch(out,self.p,self.b,.15,m,t,{},resume=True)['run_status'],'complete')
    def test_cli_rejects_real_process_owner_without_writes(self):
        out=self.root/'cli';m,t=self.interrupted(out);c=self.root/'c.json';c.write_text(json.dumps({'axes':{'growth':[.1,.11,.12,.13]},'bounds':{'scouting_points':3},'batch':{'checkpoint_every':1}}))
        with self.owner(out):
            before=snapshot(out);p=subprocess.run([sys.executable,'-m','entrysignallab.cli','sweep','--config',str(c),'--out',str(out),'--resume'],capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,2);self.assertIn('already in use',p.stderr);self.assertNotIn('Traceback',p.stderr);self.assertEqual(snapshot(out),before)
    def test_cli_holds_ownership_through_plot_and_manifest(self):
        import entrysignallab.cli as cli
        out=self.root/'publish';c=self.root/'c.json';c.write_text(json.dumps({'axes':{'growth':[.1,.11]},'bounds':{'scouting_points':3}}));seen=[]
        def wrapper(name,real):
            def call(*args,**kwargs):
                code="from entrysignallab.locking import DirectoryLock\nimport sys\ntry:\n with DirectoryLock(sys.argv[1]):pass\nexcept ValueError:raise SystemExit(7)\n"
                p=subprocess.run([sys.executable,'-c',code,str(out)],capture_output=True,text=True,timeout=10);self.assertEqual(p.returncode,7,p.stderr);seen.append(name);return real(*args,**kwargs)
            return call
        with patch.object(cli,'sweep_plot',side_effect=wrapper('plot',cli.sweep_plot)),patch.object(cli,'manifest',side_effect=wrapper('manifest',cli.manifest)),redirect_stdout(io.StringIO()):self.assertEqual(main(['sweep','--config',str(c),'--out',str(out)]),0)
        self.assertEqual(seen,['plot','manifest']);self.assertTrue(verify_manifest(out,current_source_hashes())['valid'])
    def test_owner_termination_releases_lock(self):
        out=self.root/'killed'
        with self.owner(out) as p:p.kill();p.wait(timeout=10)
        with DirectoryLock(out):pass
    def test_exception_releases_persistent_lock(self):
        out=self.root/'exception'
        with self.assertRaises(RuntimeError):
            with DirectoryLock(out) as lock:
                sibling=lock.path;raise RuntimeError('interrupt')
        self.assertTrue(sibling.is_file())
        with DirectoryLock(out):pass
    def test_outer_lease_and_completed_manifest_stay_valid(self):
        out=self.root/'lease';m,t=self.prepared()
        with DirectoryLock(out) as lease:
            run_batch(out,self.p,self.b,.15,m,t,{},lock=lease);manifest(out,{},104,'sweep');before=snapshot(out)
            with self.assertRaises(ValueError):run_batch(out,self.p,self.b,.15,m,t,{},resume=True)
            self.assertEqual(snapshot(out),before)
        self.assertTrue(verify_manifest(out,current_source_hashes())['valid'])
    def test_unheld_or_wrong_directory_lease_is_rejected(self):
        m,t=self.prepared()
        with self.assertRaises(ValueError):run_batch(self.root/'out',self.p,self.b,.15,m,t,{},lock=DirectoryLock(self.root/'out'))
        with DirectoryLock(self.root/'other') as lease,self.assertRaises(ValueError):run_batch(self.root/'out',self.p,self.b,.15,m,t,{},lock=lease)

if __name__=='__main__':unittest.main()
