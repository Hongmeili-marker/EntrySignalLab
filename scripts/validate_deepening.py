"""Independent indexed-draw transcription, vector quadrature and workflow probes."""
from pathlib import Path
from dataclasses import replace,asdict
import argparse,hashlib,json,math,sqlite3,subprocess,sys,contextlib
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff_grid,compare_stability
from entrysignallab.workflow import (uncertainty,sweep,summarize_sweep,configured_feasibility,prepare_uncertainty,prepare_sweep,
    write_json,record_validation)
from entrysignallab.batch import run_batch,CachedFirstOptimizer
from entrysignallab.benchmark import reference_revenues
from entrysignallab.sampling import SamplingPlan,wilson_interval
from entrysignallab.research import default_research_kernel,optimize_research,ResearchKernel,ModelCapabilities

def independent_uniform(seed,index,name,lo,hi):
    digest=hashlib.sha256(('parameter:'+name).encode()).digest();words=[int.from_bytes(digest[k:k+4],'little') for k in range(0,32,4)]
    u=float(np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed,index,0,*words]))).random())
    return (1-u)*lo+u*hi

def scientific_rows(path):
    with contextlib.closing(sqlite3.connect(path/'checkpoint.sqlite')) as db:cases=[json.loads(row[0]) for row in db.execute('SELECT payload FROM cases ORDER BY case_index')]
    return [{k:r.get(k) for k in ['sample','strategy','growth','network','payoff','delay','announcement','winner','participation']} for c in cases for r in c['rows']]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();out=args.out
    if out.exists():raise SystemExit('Choose a fresh validation directory')
    out.mkdir(parents=True);checks=[]
    def check(kind,name,passed,detail=None):checks.append({'kind':kind,'name':name,'pass':bool(passed),'detail':detail})
    p=ModelParams();b=DecisionBounds(scouting_points=21);ranges={'network':[.5,1.],'growth':[.1,.2]};plan=SamplingPlan(p,ranges,104)
    for index in range(20):
        expected={name:independent_uniform(104,index,name,*interval) for name,interval in ranges.items()};check('indexed_sampling','draw_'+str(index),plan.draw(index)==expected,{'reference':expected,'actual':plan.draw(index)})
    reordered=SamplingPlan(p,dict(reversed(list(ranges.items()))),104)
    check('indexed_sampling','key_order',all(plan.draw(i)==reordered.draw(i) for i in range(20)))
    a=uncertainty(p,b,.15,ranges,n=5);z=uncertainty(p,b,.15,ranges,n=10);check('indexed_sampling','prefix',a['rows']==z['rows'][:20])
    for name,cfg in [('original',{'params':asdict(p),'bounds':asdict(b),'seed':104,'uncertainty':{'ranges':ranges,'samples':5}}),('saved',None)]:
        path=out/(name+'.json')
        if cfg is not None:write_json(path,cfg)
        else:path=out/'original/config.json'
        proc=subprocess.run([sys.executable,'-m','entrysignallab.cli','uncertainty','--config',str(path),'--out',str(out/name)],capture_output=True,text=True)
        write_json(out/(name+'_execution.json'),{'exit_code':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr});check('indexed_sampling',name+'_cli',proc.returncode==0)
    check('indexed_sampling','archived_config_replay',scientific_rows(out/'original')==scientific_rows(out/'saved'))
    meta,tasks=prepare_uncertainty(p,b,.15,ranges,n=10,batch={'checkpoint_every':2})
    def stop(n):
        if n==4:raise RuntimeError('injected checkpoint interruption')
    try:run_batch(out/'resumed',p,b,.15,meta,tasks,{},progress_callback=stop)
    except RuntimeError:pass
    state=json.loads((out/'resumed/batch_progress.json').read_text());check('checkpoint','interrupted_prefix',state['state']=='interrupted' and state['processed_cases']==4)
    try:run_batch(out/'resumed',p,b,.15,meta,tasks,{'seed':105},resume=True);rejected=False
    except ValueError:rejected=True
    check('checkpoint','mismatched_resume_rejected',rejected)
    result=run_batch(out/'resumed',p,b,.15,meta,tasks,{},resume=True);run_batch(out/'serial',p,b,.15,meta,tasks,{})
    check('checkpoint','resume_scientific_equality',scientific_rows(out/'resumed')==scientific_rows(out/'serial'))
    check('checkpoint','prefix_count',result['batch_execution']['resume_prefix_cases']==4)
    meta2,tasks2=prepare_uncertainty(p,b,.15,ranges,n=10,batch={'workers':2,'checkpoint_every':2});run_batch(out/'parallel',p,b,.15,meta2,tasks2,{})
    check('checkpoint','parallel_scientific_equality',scientific_rows(out/'serial')==scientific_rows(out/'parallel'))
    try:prepare_sweep(p,b,.15,{'growth':[.1]*100,'network':[.5]*100,'learning_rate':[1.]*11});rejected=False
    except ValueError:rejected=True
    check('checkpoint','budget_preflight',rejected)
    edge=ModelParams(growth=1,network=0,growth_end=1,horizon=2,margin_x=1,deployment_cost=.01,learning_rate=1000)
    coarse=optimize(edge,'DL',DecisionBounds(scouting_points=3,tolerance=.1));t=coarse['delay'];reference=(1-t)*(3-t)/4-.01*math.exp(-1000*t)
    check('candidate_quality','coarse_promoted',coarse['payoff']>.740089501 and abs(coarse['payoff']-reference)<1e-13 and not coarse['local_quality_passed'],coarse)
    stability=compare_stability(edge,comparison={'tie_tolerance':1e-8,'outside_option':0});write_json(out/'stability.json',stability)
    check('candidate_quality','mesh_value_stable',stability['payoff_stable']);check('candidate_quality','mesh_rank_stable',stability['ranking_stable'])
    flat=optimize(ModelParams(growth=0),'RL');check('candidate_quality','flat_analytic',flat['evaluations']==1 and flat['delay_refinement_intervals']==0)
    rows=sweep(p,b,.15,{'growth_end':[.1,.2]},comparison={'tie_tolerance':0,'outside_option':1},on_error='record');summary=summarize_sweep(rows)
    check('api_contract','inherited_summary_policy',summary['comparison']=={'tie_tolerance':0.,'outside_option':1.} and summary['on_error']=='record')
    for value in [float('nan'),float('inf'),True,1.]:
        try:configured_feasibility(p,b,value,'DF',.15,0);rejected=False
        except ValueError:rejected=True
        check('api_contract','rival_'+str(value),rejected)
    correlated=SamplingPlan(p,ranges,104,correlation={'names':['network','growth'],'matrix':[[1,.6],[.6,1]]});reverse=SamplingPlan(p,ranges,104,correlation={'names':['growth','network'],'matrix':[[1,.6],[.6,1]]})
    check('sampling_extensions','copula_order',all(correlated.draw(i)==reverse.draw(i) for i in range(20)))
    # Independent uniforms specify the expected number of rejected model draws.
    failures=sum(independent_uniform(104,i,'growth_end',.1,.2)<.15 for i in range(20));u=uncertainty(p,b,.15,{'growth_end':[.1,.2]},n=20,on_error='record')
    check('sampling_extensions','recorded_failure_count',u['failed_samples']==failures,{'reference':failures,'actual':u['failed_samples']})
    u=uncertainty(p,b,.15,{'growth_end':[.1,.2]},n=20,constraint_mode='resample');check('sampling_extensions','feasible_conditional',u['failed_samples']==0 and u['rejected_draw_attempts']>0 and all(r['growth_end']>=.15 for r in u['rows']))
    for count,total in [(0,100),(29,100),(100,100),(5,11)]:
        z=1.959963984540054;prop=count/total;den=1+z*z/total;center=(prop+z*z/(2*total))/den;half=z*math.sqrt(prop*(1-prop)/total+z*z/(4*total*total))/den
        ref=[max(0.,center-half),min(1.,center+half)];actual=wilson_interval(count,total);check('sampling_extensions','wilson_'+str(count)+'_'+str(total),np.max(abs(np.array(actual)-ref))<1e-14,{'actual':actual,'reference':ref})
    vector_rows=[]
    for i in range(20):
        q=ModelParams(growth=.05+.05*i,network=.1+.1*i,growth_end=.2+.01*i,horizon=1+.1*i,quality_ratio=.5+.1*i,discount=0 if i%2==0 else .2,announcement_cost=.001,deployment_cost=.01,learning_rate=2)
        ts=[0,q.growth_end/2,q.growth_end]
        for st in ['RF','RL','DF','DL']:
            ds=[0,.3] if st.startswith('R') else [0];matrix=payoff_grid(q,st,ts,ds)
            for j,d in enumerate(ds):
                for k,t in enumerate(ts):
                    revenue=reference_revenues(q,st,t,d)[0];entry=0 if st.endswith('F') else t;reference=revenue-q.announcement_cost*d*d/2-q.deployment_cost*math.exp(-(q.learning_rate+q.discount)*entry);actual=float(matrix[j,k]);error=abs(actual-reference)
                    vector_rows.append({'case':i,'strategy':st,'delay':t,'announcement':d,'discount':q.discount,'actual':actual,'quadrature_reference':reference,'absolute_error':error})
    max_error=max(r['absolute_error'] for r in vector_rows);check('vector_quadrature','all_grid_values',max_error<1e-10,{'comparisons':len(vector_rows),'max_absolute_error':max_error});write_json(out/'vector_quadrature.json',vector_rows)
    runner=CachedFirstOptimizer();q=ModelParams(announcement_cost=.0002);first=runner(q,'RF',b,.15)
    for cost in [.002,.01,.1]:
        changed=replace(q,deployment_cost=cost,learning_rate=100);cached=runner(changed,'RF',b,.15);ordinary=optimize(changed,'RF',b,.15);check('performance_correspondence','cache_'+str(cost),cached['payoff']==ordinary['payoff'] and cached['announcement']==ordinary['announcement'])
    kernel=default_research_kernel();result=optimize_research(kernel,p,'DL',b);check('research_contract','default_adapter',result['payoff']==optimize(p,'DL',b)['payoff'])
    custom=ResearchKernel(ModelCapabilities('unvalidated-toy','1',False,False),lambda p,s,t,d:t,lambda p:None,lambda p,s,t,d:None)
    try:optimize_research(custom,{},'DL');rejected=False
    except ValueError:rejected=True
    check('research_contract','no_implicit_solver',rejected)
    report={'checks':len(checks),'all_pass':all(c['pass'] for c in checks),'by_kind':{kind:sum(x['kind']==kind for x in checks) for kind in sorted({x['kind'] for x in checks})},'vector_quadrature_comparisons':len(vector_rows),'vector_max_absolute_error':max_error,'scope':'Independent counter/name SeedSequence transcription and quadrature reference; installed CLI replay, interruption/resume and paired process equality. Local checks, not global optimization proof, calibrated probabilities, remote CI execution or authentication.'}
    write_json(out/'deepening_results.json',checks);write_json(out/'deepening_summary.json',report);record_validation(out,Path(__file__),104);print(report)
    if not report['all_pass']:raise SystemExit('Deepening validation failed')
if __name__=='__main__':main()
