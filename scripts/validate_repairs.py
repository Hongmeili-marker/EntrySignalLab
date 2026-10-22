"""Independent Decimal counterexamples, public API contracts and process ownership."""
from pathlib import Path
from decimal import Decimal,localcontext
from dataclasses import asdict,replace
from itertools import islice
from unittest.mock import patch
from contextlib import redirect_stdout
import argparse,hashlib,io,json,os,platform,subprocess,sys,time
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff_grid
from entrysignallab.solver import compare_results
from entrysignallab.workflow import (uncertainty,prepare_sweep,manifest,verify_manifest,current_source_hashes,write_json,record_validation)
from entrysignallab.batch import run_batch,runtime_fingerprint
from entrysignallab.locking import DirectoryLock


def decimal_value(p,strategy,tau):
    # Integrate independently: first entrant has stock s*t before tau;
    # thereafter the additional stock is s*(t-tau)/2, constant after H.
    with localcontext() as c:
        c.prec=100
        g,m,H,T,a=[Decimal.from_float(float(v)) for v in [p.growth,p.margin_x,p.growth_end,p.horizon,tau]]
        after=(H-a)*(T-H)+(H-a)*(H-a)/2
        return g*m*(after/2+(a*T-a*a/2 if strategy.endswith('F') else 0))


def inventory(directory):return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}


def wait_ready(proc,path):
    deadline=time.monotonic()+10
    while not path.exists() and proc.poll() is None and time.monotonic()<deadline:time.sleep(.01)
    if not path.exists():raise RuntimeError('ownership helper did not become ready')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();out=args.out
    if out.exists():raise SystemExit('Choose a fresh validation directory')
    out.mkdir(parents=True);checks=[];grid=[];p=ModelParams();b=DecisionBounds(scouting_points=3)
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    a=optimize(p,'DL',replace(b,delay_lower=-0.,max_evaluations=100));z=optimize(p,'DL',replace(b,max_evaluations=100))
    check('R01_signed_zero_equivalence',a==z and a['evaluations']<=100,{'negative':a,'positive':z})
    cfg=out/'negative_zero.json';write_json(cfg,{'bounds':{'delay_lower':-0.,'scouting_points':3,'max_evaluations':1000}})
    proc=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(cfg),'--out',str(out/'zero_cli')],capture_output=True,text=True,timeout=15)
    check('R01_installed_cli_finishes',proc.returncode==0,{'exit':proc.returncode,'stderr':proc.stderr})
    tiny=float(np.nextafter(0.,1.))
    for count in [1,2,3,7,31,1024]:
        H=tiny*count
        for multiple in [1,3]:
            q=ModelParams(growth=1e308,margin_x=1e308,network=0,growth_end=H,horizon=H*multiple)
            ts=[0,H/2,H]
            for st in ['RF','RL','DF','DL']:
                vals=payoff_grid(q,st,ts,[0])[0]
                for tau,value in zip(ts,vals):
                    reference=float(decimal_value(q,st,tau));relative=abs(float(value)-reference)/reference if reference else 0. if value==0 else None
                    grid.append({'H':H,'T':q.horizon,'tau':tau,'strategy':st,'value':float(value),'decimal_reference':reference,'relative_error':relative})
    check('R03_144_extreme_values',all(x['relative_error'] is not None and x['relative_error']<2e-11 for x in grid))
    max_relative=max(x['relative_error'] for x in grid if x['relative_error'] is not None)
    for outside in [1.,-1.,1e-300,-1e-300,1e308,-1e308]:
        for direction in [-np.inf,np.inf]:
            best=float(np.nextafter(outside,direction));step=abs(best-outside)
            for factor in [0.,.75,1.5]:
                tol=step*factor;r=compare_results([{'strategy':s,'payoff':best} for s in ['RF','RL','DF','DL']],tol,outside)
                with localcontext() as c:
                    c.prec=1000;d=Decimal.from_float(best)-Decimal.from_float(outside);t=Decimal.from_float(tol)
                expected=['RF','RL','DF','DL'] if d>t else ['no_entry'] if d<t.copy_negate() else ['RF','RL','DF','DL','no_entry']
                check('R04_decimal_comparison_'+str(len(checks)),r['preferred_with_outside_option']==expected,{'best':best,'outside':outside,'tolerance':tol,'expected':expected,'actual':r['preferred_with_outside_option']})
    kw={'constraints':[{'left':'growth','relation':'le','value':1e-15}],'constraint_mode':'resample','max_draw_attempts':3}
    r=uncertainty(p,b,.15,{'growth':[0,1]},n=1,on_error='record',**kw)
    check('R05_exhausted_count',r['draw_attempts']==r['rejected_draw_attempts']==3 and r['accepted_draws']==0 and r['exhausted_samples']==1,r)
    a=uncertainty(p,b,.15,{'growth':[.1,.2]},n=3)
    for relation in ['le','ge']:
        r=uncertainty(p,b,.15,{'growth':[.1,.2]},n=3,constraints=[{'left':'growth','relation':relation,'right':'growth'}])
        check('R07_self_constraint_'+relation,r['rows']==a['rows'] and r['summary']==a['summary'])
    meta,tasks=prepare_sweep(p,b,.15,{'growth':[.1,.11,.12,.13]},batch={'checkpoint_every':1})
    short=out/'short';caught=False
    try:run_batch(short,p,b,.15,meta,lambda:islice(tasks(),2),{})
    except ValueError:caught=True
    state=json.loads((short/'batch_progress.json').read_text())
    check('R06_short_factory_rejected',caught and state['state']=='interrupted' and state['requested_cases']==4 and state['processed_cases']==2 and not (short/'sweep_summary.json').exists(),state)
    r=run_batch(short,p,b,.15,meta,tasks,{},resume=True)
    check('R06_prefix_resumes_to_original_total',r['requested_cases']==4 and r['batch_execution']['resume_prefix_cases']==2)
    empty=out/'empty';caught=False
    try:run_batch(empty,p,b,.15,meta,lambda:iter([]),{})
    except ValueError:caught=True
    check('R06_empty_factory_rejected',caught and json.loads((empty/'batch_progress.json').read_text())['state']=='interrupted')
    def extra():
        yield from tasks();yield {'case_index':4,'changes':{'growth':.2},'sampling_attempts':1}
    extra_path=out/'extra';caught=False
    try:run_batch(extra_path,p,b,.15,meta,extra,{})
    except ValueError:caught=True
    check('R06_extra_factory_rejected',caught and json.loads((extra_path/'batch_progress.json').read_text())['processed_cases']==4)
    # A real external process owns the incomplete checkpoint while another
    # process tries CLI resume; the installed code and SQLite remain unmodified.
    work=out/'owned'
    def stop(n):
        if n==1:raise RuntimeError('controlled interruption')
    try:run_batch(work,p,b,.15,meta,tasks,{},progress_callback=stop)
    except RuntimeError:pass
    ready=out/'owner_ready';code="from pathlib import Path\nfrom entrysignallab.locking import DirectoryLock\nimport sys\nwith DirectoryLock(sys.argv[1]):\n Path(sys.argv[2]).write_text('ready')\n sys.stdin.read(1)\n"
    owner=subprocess.Popen([sys.executable,'-u','-c',code,str(work),str(ready)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        wait_ready(owner,ready);before=inventory(work);caught=False
        try:run_batch(work,p,b,.15,meta,tasks,{},resume=True)
        except ValueError as e:caught='already in use' in str(e)
        check('R02_external_owner_rejects_api',caught and inventory(work)==before)
        cfg=out/'owner_cli.json';write_json(cfg,{'axes':{'growth':[.1,.11,.12,.13]},'bounds':asdict(b),'batch':{'checkpoint_every':1}})
        proc=subprocess.run([sys.executable,'-m','entrysignallab.cli','sweep','--config',str(cfg),'--out',str(work),'--resume'],capture_output=True,text=True,timeout=15)
        check('R02_external_owner_rejects_cli',proc.returncode==2 and 'already in use' in proc.stderr and 'Traceback' not in proc.stderr and inventory(work)==before,{'exit':proc.returncode,'stderr':proc.stderr})
        owner.kill();owner.wait(timeout=10)
    finally:
        if owner.poll() is None:owner.kill();owner.wait(timeout=10)
        owner.communicate(timeout=10)
    r=run_batch(work,p,b,.15,meta,tasks,{},resume=True)
    check('R02_terminated_owner_releases',r['run_status']=='complete')
    # Verify ownership at actual plot and manifest call sites using a separate
    # competing process. Hooks observe scope; they still call the real functions.
    import entrysignallab.cli as cli
    publication=out/'publication';cfg=out/'publish.json';write_json(cfg,{'bounds':asdict(b),'axes':{'growth':[.1,.11]}});phases=[]
    def observe(name,real):
        def wrapped(*args,**kwargs):
            child="from entrysignallab.locking import DirectoryLock\nimport sys\ntry:\n with DirectoryLock(sys.argv[1]):pass\nexcept ValueError:raise SystemExit(7)\n"
            proc=subprocess.run([sys.executable,'-c',child,str(publication)],capture_output=True,text=True,timeout=15);phases.append({'phase':name,'competitor_exit':proc.returncode});return real(*args,**kwargs)
        return wrapped
    with patch.object(cli,'sweep_plot',side_effect=observe('plot',cli.sweep_plot)),patch.object(cli,'manifest',side_effect=observe('manifest',cli.manifest)),redirect_stdout(io.StringIO()):exitcode=cli.main(['sweep','--config',str(cfg),'--out',str(publication)])
    check('R02_cli_owns_publication_phases',exitcode==0 and len(phases)==2 and all(x['competitor_exit']==7 for x in phases),phases)
    check('R02_final_manifest_valid',verify_manifest(publication,current_source_hashes())['valid'])
    # Runtime identity is bound to the stored recipe and checked before writes.
    runtime=out/'runtime'
    try:run_batch(runtime,p,b,.15,meta,tasks,{},progress_callback=stop)
    except RuntimeError:pass
    before=inventory(runtime);caught=False
    with patch('entrysignallab.batch.runtime_fingerprint',return_value={**runtime_fingerprint(),'scipy':'mismatch'}):
        try:run_batch(runtime,p,b,.15,meta,tasks,{},resume=True)
        except ValueError as e:caught='mismatch' in str(e)
    check('environment_mismatch_rejected',caught and inventory(runtime)==before)
    r=run_batch(runtime,p,b,.15,meta,tasks,{},resume=True)
    check('environment_match_resumes',r['run_status']=='complete')
    features={'fork_inherited_descriptor':'not_applicable'}
    if hasattr(os,'fork'):
        path=out/'fork_owner';ready=out/'fork_ready';stopfile=out/'fork_stop'
        code="""from pathlib import Path
from entrysignallab.locking import DirectoryLock
import os,sys,time
with DirectoryLock(sys.argv[1]):
 child=os.fork()
 if child==0:
  Path(sys.argv[2]).write_text(str(os.getpid()))
  end=time.monotonic()+15
  while not Path(sys.argv[3]).exists() and time.monotonic()<end:time.sleep(.02)
  os._exit(0)
 sys.stdin.read(1)
"""
        owner=subprocess.Popen([sys.executable,'-u','-c',code,str(path),str(ready),str(stopfile)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            wait_ready(owner,ready);owner.kill();owner.wait(timeout=10)
            with DirectoryLock(path):pass
            features['fork_inherited_descriptor']='executed_pass';check('R02_fork_worker_does_not_retain_owner_lock',True)
        finally:
            stopfile.touch()
            if owner.poll() is None:owner.kill();owner.wait(timeout=10)
            owner.communicate(timeout=20)
    write_json(out/'repair_checks.json',checks);write_json(out/'extreme_grid_reference.json',grid)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'extreme_grid_comparisons':len(grid),'max_extreme_grid_relative_error':max_relative,'features':features,
             'scope':'Independent 100-digit Decimal demand integration and 1000-digit comparison labels; installed CLI/API and real local processes. Publication hooks observe lock scope while invoking the real functions. Linux execution is not remote/cross-platform evidence, arbitrary-parameter certification, or a global optimization proof.'}
    write_json(out/'repairs_summary.json',summary);record_validation(out,Path(__file__),seed=20261018);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit(1)

if __name__=='__main__':main()
