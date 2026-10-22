"""Independent v0.10 audit acceptance: Decimal references, API and real CLI."""
from pathlib import Path
from dataclasses import asdict,replace
from decimal import Decimal,localcontext
from statistics import NormalDist
import argparse,json,math,subprocess,sys,warnings
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,demand,payoff,rescale_experiment
from entrysignallab.sampling import wilson_interval,linear_quantiles
from entrysignallab.research import ResearchKernel,ModelCapabilities,default_research_kernel,optimize_research
from entrysignallab.solver import optimize,compare_results
from entrysignallab.workflow import sweep,summarize_sweep,uncertainty,prepare_uncertainty,execute_case,summarize_uncertainty,write_json,read_json,verify_manifest,record_validation
from entrysignallab.batch import run_batch

def quantile_reference(values,qs):
    with localcontext() as c:
        c.prec=1200;v=sorted(Decimal.from_float(float(x)) for x in values);result=[]
        for q in qs:
            # Retain the public helper's binary64 order index h; only endpoint
            # interpolation is evaluated independently with 1200-digit Decimal.
            h=(len(v)-1)*q;i=int(h);f=Decimal.from_float(h-i)
            result.append(float(v[i]*(1-f)+v[min(i+1,len(v)-1)]*f))
        return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True,type=Path);out=ap.parse_args().out.resolve()
    if out.exists():raise SystemExit('Choose a fresh directory')
    out.mkdir(parents=True);checks=[];p=ModelParams();b=DecisionBounds(scouting_points=3,announcement_upper=0)
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    def rejects(name,call):
        try:call();denied=False
        except ValueError:denied=True
        check(name,denied)
    intervals=[]
    for dtype,n in [(np.int32,32768),(np.int32,65536),(np.int64,2**31),(np.uint64,2**64-1),(int,32768)]:
        for k in [0,1,n//2,n-1,n]:
            with warnings.catch_warnings():
                warnings.simplefilter('error');got=wilson_interval(dtype(k),dtype(n))
            with localcontext() as c:
                c.prec=120;nn=Decimal(n);pp=Decimal(k)/nn;z=Decimal.from_float(-NormalDist().inv_cdf(.025));den=1+z*z/nn
                center=(pp+z*z/(2*nn))/den;half=z*(pp*(1-pp)/nn+z*z/(4*nn*nn)).sqrt()/den
                ref=[max(0.,float(center-half)),min(1.,float(center+half))]
            error=max(abs(a-r) for a,r in zip(got,ref));intervals.append({'dtype':dtype.__name__,'count':k,'total':n,'observed':got,'reference':ref,'absolute_error':error})
            check('A01_'+dtype.__name__+'_'+str(n)+'_'+str(k),all(math.isclose(a,r,rel_tol=8e-14,abs_tol=1e-17) for a,r in zip(got,ref)))
    check('A01_extreme_python_integer',wilson_interval(0,10**10000)==[0.,0.])
    check('A01_empty_numpy',wilson_interval(np.int64(0),np.int64(0)) is None)
    for confidence in [.95,float(np.nextafter(1.,0.)),float(np.nextafter(0.,1.))]:
        v=wilson_interval(1,2,confidence);check('A01_confidence_'+str(confidence),0<=v[0]<=.5<=v[1]<=1)
    write_json(out/'wilson_decimal_reference.json',intervals)
    k=default_research_kernel();bounds=replace(b,delay_lower=.2,delay_upper=.25)
    for st,t,d in [('RL',.1,0),('RL',.26,0),('RL',.2,1),('DF',.2,0)]:
        bad=replace(k,conditional_solver=lambda p,s,b,r,t=t,d=d:{'strategy':s,'delay':t,'announcement':d,'payoff':payoff(p,s,t,d)})
        rejects('A02_configured_'+st+'_'+str(t)+'_'+str(d),lambda:optimize_research(bad,p,st,bounds,.15))
    for st in ['RF','RL','DF','DL']:
        v=optimize_research(k,p,st,bounds,.15);check('A02_default_'+st,v['payoff']==optimize(p,st,bounds,.15)['payoff'])
    rejects('A02_missing_validator',lambda:optimize_research(replace(k,validate_solution=None),p,'RL',b,.15))
    rejects('A02_validator_cannot_abstain',lambda:optimize_research(replace(k,validate_solution=lambda *a:None),p,'DL',b,.15))
    bad=replace(k,conditional_solver=lambda p,s,b,r:{'strategy':s,'delay':.2,'announcement':0,'payoff':5})
    rejects('A02_objective_correspondence',lambda:optimize_research(bad,p,'DL',b,.15))
    seen=[]
    def custom_check(p,s,b,r,v):seen.append((b,r));return v['delay']<=b['limit'] and v['announcement']==r
    toy=ResearchKernel(ModelCapabilities('independent-toy','1',False,False),lambda p,s,t,d:t+p['offset'],lambda p:None,lambda *a:None,
        lambda p,s,b,r:{'strategy':s,'delay':3,'announcement':r,'payoff':5},custom_check)
    cb={'limit':3};v=optimize_research(toy,{'offset':2},'toy',cb,7)
    check('A02_model_owned_bounds',v['payoff']==5 and seen[0][0] is cb and seen[0][1]==7)
    rejects('A02_custom_violation',lambda:optimize_research(toy,{'offset':2},'toy',{'limit':2},7))
    unit_rows=[]
    for factor in [.125,12,1000]:
        for upper in [None,.2]:
            bb=replace(b,delay_upper=upper);q,qb,r=rescale_experiment(p,bb,.15,factor,1000)
            check('A03_preserved_upper_'+str((factor,upper)),qb.delay_upper is None if upper is None else math.isclose(qb.delay_upper,upper*factor))
            pp,pb,rr=rescale_experiment(q,qb,r,1/factor,.001)
            check('A03_roundtrip_'+str((factor,upper)),(pb.delay_upper is None)==(upper is None) and math.isclose(pp.growth_end,p.growth_end,rel_tol=3e-15))
            for st in ['RF','RL','DF','DL']:
                v=payoff(q,st,.15*factor);ref=payoff(p,st,.15);unit_rows.append(abs(v-ref))
            if upper is None:
                rows=sweep(q,qb,r,{'growth_end':[.2*factor,.3*factor]})
                check('A03_adaptive_sweep_'+str(factor),summarize_sweep(rows)['completed_cases']==2)
                v=uncertainty(q,qb,r,{'growth_end':[.2*factor,.3*factor]},n=2)
                check('A03_adaptive_uncertainty_'+str(factor),v['completed_samples']==2)
    check('A03_payoff_invariance',max(unit_rows)<1e-14,{'max_error':max(unit_rows)})
    for name,t in [('scalar',.2+2j),('numpy_scalar',np.complex128(.2)),('vector',np.array([.2+2j,.4+7j])),('matrix',[[.2,.3],[.4+1j,.5]]),('object',np.array([.2+0j],dtype=object))]:
        with warnings.catch_warnings():
            warnings.simplefilter('error');rejects('A04_complex_'+name,lambda:demand(p,'DL',t,.15))
    t=np.array([[0.,.2],[.4,1.]]);x,y=demand(p,'DL',t,.15)
    check('A04_real_shape',all((x[i],y[i])==demand(p,'DL',float(t[i]),.15) for i in np.ndindex(t.shape)))
    for t in [-1,float('nan'),float('inf'),p.horizon+1]:rejects('A04_invalid_'+str(t),lambda:demand(p,'DL',t,.15))
    quantiles=[];u=float(np.nextafter(0.,1.));qs=[0.,.05,.25,.5,.75,.95,1.]
    sets=[[a*u,b*u] for a,b in [(-1,2),(3,-2),(1,2),(-2,-1),(-1,1),(0,1),(-1,0)]]+[[i*u for i in [-10,2,3,7]],[-1.7e308,1.7e308],[1.6e308,1.7e308],[-3.,2.,4.,10.]]
    for values in sets:
        got=linear_quantiles(values,qs);ref=quantile_reference(values,qs)
        quantiles.extend({'values':values,'q':q,'observed':a,'reference':r,'exact_match':a==r} for q,a,r in zip(qs,got,ref))
        check('A05_quantile_set_'+str(len(checks)),got==ref)
    write_json(out/'quantile_decimal_reference.json',quantiles)
    small=ModelParams(growth=1,network=0,growth_end=1,horizon=3);ranges={'margin_x':[0,4*u],'deployment_cost':[0,4*u]};cor={'names':list(ranges),'matrix':[[1,-1],[-1,1]]}
    cfg={'params':asdict(small),'bounds':asdict(b),'rival_delay':0,'seed':2,'uncertainty':{'ranges':ranges,'samples':2,'correlation':cor},'batch':{'checkpoint_every':1}}
    path=out/'subnormal_config.json';write_json(path,cfg);api=uncertainty(small,b,0,ranges,n=2,seed=2,correlation=cor);write_json(out/'subnormal_api.json',api)
    for st in ['RF','RL','DF','DL']:
        values=[x['payoff'] for x in api['rows'] if x['strategy']==st]
        check('A05_actual_'+st,api['payoff_summaries'][st]['quantiles_05_50_95']==quantile_reference(values,[.05,.5,.95]) and api['payoff_summaries'][st]['quantiles_05_50_95'][1]==0,values)
    def cli(directory,resume=False):
        command=[sys.executable,'-m','entrysignallab.cli','uncertainty','--config',str(path),'--out',str(directory)]+(['--resume'] if resume else [])
        proc=subprocess.run(command,capture_output=True,text=True,timeout=60);(out/(directory.name+'.log')).write_text(proc.stdout+proc.stderr)
        summary=read_json(directory/'uncertainty_summary.json') if proc.returncode==0 else {}
        check('A05_cli_'+directory.name,proc.returncode==0 and verify_manifest(directory)['valid'] and summary['payoff_summaries']==api['payoff_summaries'])
    cli(out/'subnormal_cli')
    m,t=prepare_uncertainty(small,b,0,ranges,n=2,seed=2,correlation=cor,batch=cfg['batch'])
    def stop(n):
        if n==1:raise RuntimeError('intentional interruption')
    try:run_batch(out/'subnormal_resume',small,b,0,m,t,cfg,progress_callback=stop)
    except RuntimeError:pass
    cli(out/'subnormal_resume',True)
    cases=[]
    for label,bb,rr,policy in [('unattained',replace(b,announcement_upper=None),{'growth':[.1,.11]},'raise'),('bounded',b,{'growth':[.1,.11]},'raise'),('invalid',b,{'growth_end':[.1,.1]},'record')]:
        v=uncertainty(p,bb,.15,rr,n=2,on_error=policy);write_json(out/(label+'_quality.json'),v);cases.append(v)
        expected={'pass':2 if label=='bounded' else 0,'fail':0,'not_assessed':2 if label=='unattained' else 0}
        check('A06_'+label+'_counts',v['quality_status_counts']==expected and v['quality_warning_samples']==0 and sum(expected.values())==v['completed_samples'])
    check('A06_unrankable_preserved',cases[0]['summary']['unrankable']['count']==2 and cases[0]['failed_samples']==0)
    check('A06_failed_excluded',cases[2]['quality_excluded_failed_samples']==2)
    m,t=prepare_uncertainty(p,b,.15,{'growth':[.1,.11]},n=2)
    def failed_check(*a):return {**optimize(*a),'local_quality_passed':False}
    v=summarize_uncertainty((execute_case(p,b,.15,x,m,failed_check) for x in t()),m)
    check('A06_actual_failed_check',v['quality_warning_samples']==2 and v['quality_status_counts']['fail']==2)
    rows=sweep(p,replace(b,announcement_upper=None),.15,{'growth':[.1,.11]});v=summarize_sweep(rows)
    check('A06_sweep_counts',v['quality_warning_cases']==0 and v['quality_status_counts']['not_assessed']==2)
    minimal=[{'strategy':st,'payoff':1.} for st in ['RF','RL','DF','DL']];v=compare_results(minimal)
    check('A06_missing_quality_not_pass',v['all_rankable'] and v['all_local_quality_passed'] is None and v['local_quality_status']=='not_assessed')
    minimal[0]['payoff']=None;minimal[1]['local_quality_passed']=False;v=compare_results(minimal)
    check('A06_fail_precedes_incomplete',v['local_quality_status']=='fail' and not v['local_quality_assessment_complete'])
    write_json(out/'v0110_checks.json',checks)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'wilson_reference_values':len(intervals),
        'max_wilson_absolute_error':max(x['absolute_error'] for x in intervals),'quantile_reference_values':len(quantiles),
        'quantile_exact_matches':sum(x['exact_match'] for x in quantiles),'max_unit_payoff_error':max(unit_rows),
        'scope':'Local Linux installed-wheel acceptance. Decimal references are independent of production interval and rational interpolation kernels. Deliberately defective extension callbacks test the adapter; they are not default solver failures.'}
    write_json(out/'v0110_summary.json',summary);record_validation(out,Path(__file__),20261018);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('Audit acceptance failed')

if __name__=='__main__':main()
