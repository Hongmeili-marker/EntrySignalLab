"""Independent v0.9 audit acceptance: Decimal oracles and real process races."""
from pathlib import Path
from decimal import Decimal,localcontext
from dataclasses import asdict
from statistics import NormalDist
import argparse,hashlib,json,math,os,subprocess,sys,time
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,demand,payoff
from entrysignallab.sampling import SamplingPlan,linear_quantiles,wilson_interval
from entrysignallab.workflow import (prepare_sweep,prepare_uncertainty,uncertainty,write_json,manifest,verify_manifest,record_validation)
from entrysignallab.batch import run_batch
from entrysignallab.locking import DirectoryLock


def inventory(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def wait_for(paths,processes):
    deadline=time.monotonic()+20
    while not all(p.exists() for p in paths) and time.monotonic()<deadline:
        if all(p.poll() is not None for p in processes):break
        time.sleep(.01)
    if not all(p.exists() for p in paths):raise RuntimeError('process coordination timed out')


HELPER='''from pathlib import Path
import json,sys,time
from entrysignallab.locking import DirectoryLock
p,ready,go,release=map(Path,sys.argv[1:])
while not go.exists():time.sleep(.005)
try:
 with DirectoryLock(p):
  ready.write_text(json.dumps({'granted':True}))
  while not release.exists():time.sleep(.005)
except ValueError as e:ready.write_text(json.dumps({'granted':False,'error':str(e)}))
'''


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);out=ap.parse_args().out.resolve()
    if out.exists():raise SystemExit('Choose a fresh directory')
    out.mkdir(parents=True);checks=[];p=ModelParams();b=DecisionBounds(scouting_points=3,announcement_upper=0)
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    for workers,config,vals in [(1,{},[.7,.8,.9]),(2,{},[.7,.8,.9]),(1,{'label':'partial'},[.12,.11,.1]),(1,{'axes':{'growth':[.1,.11,.12]}},[.7,.8,.9])]:
        directory=out/('resume_'+str(len(checks)));m,t=prepare_sweep(p,b,.15,{'growth':[.1,.11,.12]},batch={'workers':workers,'checkpoint_every':1})
        def stop(n):
            if n==1:raise RuntimeError('intentional interruption')
        try:run_batch(directory,p,b,.15,m,t,config,progress_callback=stop)
        except RuntimeError:pass
        before=inventory(directory);mm,tt=prepare_sweep(p,b,.15,{'growth':vals},batch={'workers':workers,'checkpoint_every':1});denied=False
        try:run_batch(directory,p,b,.15,mm,tt,config,resume=True)
        except ValueError:denied=True
        check('R01_changed_axes_'+str(len(checks)),denied and before==inventory(directory),{'workers':workers,'config':config,'replacement':vals})
        r=run_batch(directory,p,b,.15,m,t,config,resume=True)
        check('R01_original_resumes_'+str(len(checks)),r['batch_execution']['resume_prefix_cases']==1 and r['requested_cases']==3)
    quantile_rows=[]
    sets=[[-1.7e308,1.7e308],[-1.7e308,-1e307,0.,1e307,1.6e308],[1.6e308,1.7e308],[-1.7e308,-1.6e308],[1.7e308]*3,[-3.,4.,1.,4.,9.]]
    for values in sets:
        qs=[0.,.05,.25,.5,.75,.95,1.];observed=linear_quantiles(values,qs)
        with localcontext() as c:
            c.prec=1000;v=sorted(Decimal.from_float(x) for x in values)
            for q,value in zip(qs,observed):
                h=Decimal.from_float(q)*(len(v)-1);i=int(h);f=h-i;ref=float(v[i]*(1-f)+v[min(i+1,len(v)-1)]*f)
                quantile_rows.append({'values':values,'q':q,'value':value,'reference':ref,'scaled_error':abs(value-ref)/max(1.,abs(ref))})
        check('R02_decimal_quantiles_'+str(len(checks)),all(math.isfinite(x) for x in observed) and observed==sorted(observed) and max(x['scaled_error'] for x in quantile_rows)<5e-15)
    write_json(out/'quantile_decimal_reference.json',quantile_rows)
    extreme=ModelParams(growth=1,network=0,growth_end=1,horizon=3)
    ranges={'margin_x':[0,1e308],'deployment_cost':[0,1.7e308]};cor={'names':['margin_x','deployment_cost'],'matrix':[[1,-1],[-1,1]]}
    cfg={'params':asdict(extreme),'bounds':asdict(b),'rival_delay':0,'seed':2,'uncertainty':{'ranges':ranges,'samples':2,'correlation':cor},'batch':{'checkpoint_every':1}}
    config_path=out/'finite_extreme_payoffs.json';write_json(config_path,cfg)
    cli=subprocess.run([sys.executable,'-m','entrysignallab.cli','uncertainty','--config',str(config_path),'--out',str(out/'quantile_cli')],capture_output=True,text=True,timeout=60)
    (out/'quantile_cli.log').write_text(cli.stdout+cli.stderr)
    check('R02_real_cli_completes',cli.returncode==0 and verify_manifest(out/'quantile_cli')['valid'],{'exit':cli.returncode})
    r=uncertainty(extreme,b,0,ranges,n=2,seed=2,correlation=cor)
    check('R02_all_finite_cases_retained',r['failed_samples']==0 and all(x['finite_cases']==2 and all(math.isfinite(y) for y in x['quantiles_05_50_95']) for x in r['payoff_summaries'].values()),r['payoff_summaries'])
    m,t=prepare_uncertainty(extreme,b,0,ranges,n=2,seed=2,correlation=cor,batch=cfg['batch'])
    def stop_complete(n):
        if n==2:raise RuntimeError('stop before summary')
    try:run_batch(out/'quantile_resume',extreme,b,0,m,t,cfg,progress_callback=stop_complete)
    except RuntimeError:pass
    cli=subprocess.run([sys.executable,'-m','entrysignallab.cli','uncertainty','--config',str(config_path),'--out',str(out/'quantile_resume'),'--resume'],capture_output=True,text=True,timeout=60)
    (out/'quantile_resume.log').write_text(cli.stdout+cli.stderr)
    check('R02_complete_prefix_cli_resumes',cli.returncode==0 and verify_manifest(out/'quantile_resume')['valid'],{'exit':cli.returncode,'stderr':cli.stderr})
    demand_rows=[]
    q=ModelParams(growth=1,network=1e100,growth_end=1e100,horizon=1e100,quality_ratio=1e300,margin_x=1e300)
    for st in ['DL','RL']:
        for t in [1e90,1e100]:
            x,y=demand(q,st,t,1)
            with localcontext() as c:
                c.prec=200;D=lambda x:Decimal.from_float(float(x));g,n,H,w,m=[D(v) for v in [q.growth,q.network,q.growth_end,q.quality_ratio,q.margin_x]];share=1/(1+w*(1+n*g));ref=float(g*(D(t)-1)*share)
                revenue=float(g*(H-1)*(H-1)*share*m/2)
            err=abs(x-ref)/ref;demand_rows.append({'strategy':st,'time':t,'value':x,'reference':ref,'relative_error':err})
            check('R03_positive_stock_'+str(len(checks)),x>0 and err<3e-12 and math.isfinite(y))
        check('R03_integral_revenue_'+st,math.isclose((x*.5)*q.horizon*q.margin_x,revenue,rel_tol=3e-12) and math.isclose(payoff(q,st,1),revenue,rel_tol=3e-12))
    write_json(out/'demand_decimal_reference.json',demand_rows)
    for st in ['RF','RL','DF','DL']:
        ts=np.linspace(0,p.horizon,101);x,y=demand(p,st,ts,.15,.3 if st.startswith('R') else 0)
        check('R03_conservation_'+st,np.allclose(x+y,p.growth*np.minimum(ts,p.growth_end),rtol=5e-15,atol=1e-17))
    ranges={'growth_end':[.3,.6],'horizon':[.3,.6]};cor={'names':list(ranges),'matrix':[[1,1],[1,1]]}
    for relation in [None,'le','ge']:
        constraints=[] if relation is None else [{'left':'growth_end','relation':relation,'right':'horizon'}]
        r=uncertainty(p,b,.15,ranges,n=3,correlation=cor,constraints=constraints)
        check('R04_joint_support_'+str(relation),r['failed_samples']==0 and not r['domain_preflight_issues'])
    for correlation,rr in [(None,ranges),({'names':list(ranges),'matrix':[[1,.99999],[.99999,1]]},ranges),(cor,{'growth_end':[.3,.6],'horizon':[.4,.7]})]:
        denied=False
        try:prepare_uncertainty(p,b,.15,rr,correlation=correlation)
        except ValueError:denied=True
        check('R04_unproven_domain_rejected_'+str(len(checks)),denied)
    rr={**ranges,'margin_x':[.2,.5]};c={'names':list(rr),'matrix':[[1,1,.5],[1,1,.5],[.5,.5,1]]};plan=SamplingPlan(p,rr,correlation=c)
    draws=[plan.draw(i) for i in range(100)]
    check('R04_singular_exact_equality',all(d['growth_end']==d['horizon'] for d in draws))
    inv=list(reversed(c['names']));cc={'names':inv,'matrix':np.asarray(c['matrix'])[::-1,::-1].tolist()};replay=SamplingPlan(p,dict(reversed(list(rr.items()))),correlation=cc)
    check('R04_key_order_replay',draws==[replay.draw(i) for i in range(100)])
    # Each pair races from one start barrier and holds successful leases until
    # both decisions are recorded; outcomes cannot be explained by serial exit.
    process_rows=[]
    for mode in ['parent_first','child_first','simultaneous','siblings']:
        base=out/('race_'+mode);base.mkdir();parent=base/'experiment';child=parent/'child'
        dirs=[parent,child] if mode!='siblings' else [base/'a',base/'b']
        if mode=='child_first':dirs.reverse()
        go=[base/'go0',base/'go1'];ready=[base/'ready0',base/'ready1'];release=base/'release';processes=[]
        try:
            for i,directory in enumerate(dirs):
                processes.append(subprocess.Popen([sys.executable,'-c',HELPER,str(directory),str(ready[i]),str(go[i]),str(release)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
                if mode in ['parent_first','child_first']:
                    go[i].touch();wait_for([ready[i]],processes)
            if mode not in ['parent_first','child_first']:
                for g in go:g.touch()
            wait_for(ready,processes);outcomes=[json.loads(x.read_text()) for x in ready]
            check('R05_process_'+mode,sum(x['granted'] for x in outcomes)==(2 if mode=='siblings' else 1),outcomes)
            if mode in ['parent_first','child_first']:check('R05_first_owner_retained_'+mode,outcomes[0]['granted'] and not outcomes[1]['granted'])
            process_rows.append({'mode':mode,'outcomes':outcomes})
        finally:
            release.touch()
            for proc in processes:
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
    write_json(out/'process_races.json',process_rows)
    # Published ancestors and completed descendants stay disjoint after release.
    m,t=prepare_sweep(p,b,.15,{'growth':[.1]})
    for child_first in [False,True]:
        parent=out/('finished_'+str(child_first));first=parent/'child' if child_first else parent;second=parent if child_first else parent/'child'
        with DirectoryLock(first) as lease:
            run_batch(first,p,b,.15,m,t,{},lock=lease);manifest(first,{},104,'sweep')
        before=inventory(parent);denied=False
        try:
            with DirectoryLock(second):pass
        except ValueError:denied=True
        check('R05_finished_tree_'+str(child_first),denied and before==inventory(parent) and verify_manifest(first)['valid'])
    cli_parent=out/'cli_parent';cli_parent.mkdir();manifest(cli_parent,{},104,'audit')
    basic=out/'basic_cli.json';write_json(basic,{'bounds':{'scouting_points':3,'announcement_upper':0}})
    for command in ['audit','optimize','reproduce','benchmark']:
        before=inventory(cli_parent);argv=[sys.executable,'-m','entrysignallab.cli',command,'--out',str(cli_parent/'child')]
        if command!='benchmark':argv+=['--config',str(basic)]
        proc=subprocess.run(argv,capture_output=True,text=True,timeout=30)
        check('R05_all_cli_outputs_'+command,proc.returncode==2 and before==inventory(cli_parent),{'exit':proc.returncode,'stderr':proc.stderr})
    parent=out/'alias_target';parent.mkdir();alias=out/'alias'
    alias.symlink_to(parent,target_is_directory=True)
    with DirectoryLock(parent):
        before=inventory(parent);denied=False
        try:
            with DirectoryLock(alias/'child'):pass
        except ValueError:denied=True
        check('R05_symlink_no_mutation',denied and before==inventory(parent))
    confidence=float(np.nextafter(1.,0.));z=-NormalDist().inv_cdf((1-confidence)/2);half=z/(2*math.sqrt(2+z*z));observed=wilson_interval(1,2,confidence)
    check('R06_upper_confidence',np.allclose(observed,[.5-half,.5+half],rtol=1e-13),observed)
    check('R06_default_interval',np.allclose(wilson_interval(1,2),[.09453120573423074,.9054687942657693],rtol=1e-14))
    check('R06_tiny_confidence',wilson_interval(1,2,float(np.nextafter(0.,1.)))==[.5,.5])
    check('R06_empty_denominator',wilson_interval(0,0) is None)
    for total in [1,2,1000]:
        check('R06_boundary_counts_'+str(total),all(0<=(v:=wilson_interval(count,total,confidence))[0]<=count/total<=v[1]<=1 for count in [0,total]))
    write_json(out/'v0100_checks.json',checks)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'quantile_reference_values':len(quantile_rows),
             'max_quantile_scaled_error':max(x['scaled_error'] for x in quantile_rows),'demand_reference_values':len(demand_rows),
             'max_demand_relative_error':max(x['relative_error'] for x in demand_rows),'process_races':len(process_rows),
             'scope':'Locally executed Linux process races; Decimal reference arithmetic is independent of production log/quantile kernels.'}
    write_json(out/'v0100_summary.json',summary);record_validation(out,Path(__file__),20261018);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('Audit acceptance failed')

if __name__=='__main__':main()
