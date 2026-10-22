"""Independent A15 evaluated-control ordering and complete workflow acceptance."""
from pathlib import Path
from dataclasses import asdict,replace
from decimal import Decimal,localcontext,MAX_EMAX,MIN_EMIN
from unittest.mock import patch
import argparse,csv,json,os,subprocess,sys
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,compare_stability
from entrysignallab import solver
from entrysignallab.solver import NumericalError
from entrysignallab.workflow import read_json,write_json,record_validation,verify_manifest,current_source_hashes,prepare_sweep
from entrysignallab.batch import run_batch

def named_params(**changes):
    return ModelParams(**{'growth':1,'network':0,'growth_end':3,'horizon':3,'margin_x':1,
        'discount':1000,'learning_rate':100,'deployment_cost':1e45,**changes})

def independent_value(p,t,d=0.,precision=200):
    """Direct integral of follower demand; no production numerical helpers.

    H=T is the deliberately scoped reference family. Form its positive scale
    before the final float conversion; keep the full Decimal value for order.
    """
    assert p.horizon==p.growth_end
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,H,w,m,r,c,C,k,t,d=map(Decimal.from_float,(p.growth,p.network,p.growth_end,
            p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,p.deployment_cost,
            p.learning_rate,float(t),float(d)))
        length=H-t
        mass=length*length/2 if r==0 else (1-(1+r*length)*(-r*length).exp())/(r*r)
        share=(1+n*d*t)/(1+n*d*t+w*(1+n*s*t))
        return (-r*t).exp()*(m*s*share*mass-C*(-k*t).exp())-c*d*d/2

def independent_stationary(p,d=0.,precision=200):
    """Bisection of an independently differentiated event integral on [1,2].

    It checks this strict stationary bracket; it is not a general global oracle.
    """
    assert p.announcement_cost==0 and p.discount>0
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,H,w,m,r,C,k,d=map(Decimal.from_float,(p.growth,p.network,p.growth_end,
            p.quality_ratio,p.margin_x,p.discount,p.deployment_cost,p.learning_rate,float(d)))
        def balance(t):
            length=H-t;e=(-r*length).exp();mass=(1-(1+r*length)*e)/(r*r)
            a=1+n*d*t;b=w*(1+n*s*t);den=a+b
            share=a/den;derivative=(n*d*den-a*(n*d+w*n*s))/(den*den)
            return m*s*(derivative*mass-share*(1-e)/r)+C*(r+k)*(-k*t).exp()
        lo=Decimal(1);hi=Decimal(2)
        assert balance(lo)>0>balance(hi)
        for _ in range(180):
            middle=(lo+hi)/2
            if balance(middle)>0:lo=middle
            else:hi=middle
        return float((lo+hi)/2)

def snapshot_optimize(p,st,b):
    observed=[];original=solver.payoff
    def observe(params,strategy,delay,announcement=0.):
        value=original(params,strategy,delay,announcement)
        observed.append({'delay':float(delay),'announcement':float(announcement),'payoff':value})
        return value
    with patch.object(solver,'payoff',observe):result=optimize(p,st,b,0)
    assert len(observed)==result['evaluations']
    return result,observed

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];observations=[];cli=[]
    def check(name,passed,detail=None):
        checks.append({'name':name,'pass':bool(passed),'detail':detail})
        if not passed:raise AssertionError((name,detail))
    b=DecisionBounds(delay_lower=1,delay_upper=2,announcement_upper=0)
    corpus=read_json(root/'tests/data/v0200_A15_boundary_corpus.json')
    check('frozen_corpus',len(corpus)==24 and all(row['actual_preference']==['no_entry'] for row in corpus))
    evaluated=0;max_delay_error=0.;all_points=[]
    cases=[('frozen_'+str(i),ModelParams(**row['params']),b) for i,row in enumerate(corpus)]
    cases += [('announcing_cap',named_params(network=.85),replace(b,announcement_upper=1.))]
    cases += [('money_'+str(scale),named_params(margin_x=scale,deployment_cost=1e45*scale),b) for scale in (1e-80,1e80)]
    for name,p,bounds in cases:
        for st in ('RL','DL'):
            result,points=snapshot_optimize(p,st,bounds)
            selected_low=independent_value(p,result['delay'],result['announcement'],200)
            selected=independent_value(p,result['delay'],result['announcement'],400)
            check(name+'_'+st+'_reference_sign',selected>0 and selected_low>0)
            check(name+'_'+st+'_two_precision_value',float(selected)==float(selected_low))
            oracle_200=independent_stationary(p,result['announcement'],200)
            oracle_400=independent_stationary(p,result['announcement'],400)
            check(name+'_'+st+'_stationary_reference_stable',oracle_200==oracle_400)
            error=abs(result['delay']-oracle_400);max_delay_error=max(max_delay_error,error)
            check(name+'_'+st+'_stationary_delay',error<2e-8,error)
            check(name+'_'+st+'_budget',len(points)==result['evaluations']<=bounds.max_evaluations)
            check(name+'_'+st+'_consistency_diagnostic',result['search_precision']['evaluated_candidate_consistency_checks']==len(points)-1)
            refs=[]
            for i,row in enumerate(points):
                value_200=independent_value(p,row['delay'],row['announcement'],200)
                value=independent_value(p,row['delay'],row['announcement'],400)
                check(name+'_'+st+'_node_'+str(i),selected>=value,{'selected_delay':result['delay'],'node':row})
                check(name+'_'+st+'_node_reference_'+str(i),(value_200>selected_low)==(value>selected))
                with localcontext() as ctx:
                    ctx.prec=450;log_abs=str(abs(value).ln()) if value else None
                refs.append({**row,'reference_sign':int(value>0)-int(value<0),'reference_log_abs':log_abs})
            evaluated+=len(points)
            observations.append({'case':name,'params':asdict(p),'strategy':st,'bounds':asdict(bounds),'result':result,
                'stationary_reference':oracle_400,'delay_error':error,'evaluated_control_references':refs})
    write_json(out/'evaluated_controls.json',observations)
    p=named_params();r=compare(p,b,0,tie_tolerance=0)
    check('named_positive_preference',r['preferred_with_outside_option']==['RL','DL'])
    check('named_positive_underflow',r['outside_option_gap_diagnostic']['sign']==1 and r['outside_option_gap_diagnostic']['representation']=='underflow')
    for tol in (1e-8,float.fromhex('0x0.0000000000001p-1022')):
        check('positive_tolerance_'+str(tol),compare(p,b,0,tie_tolerance=tol)['preferred_with_outside_option']==['RL','DL','no_entry'])
    stability=compare_stability(p,b,0,{'tie_tolerance':0},(1,2,4))
    check('stability_correct_candidates',stability['ranking_stable'] and stability['payoff_stable'] and all(x['preferred_with_outside_option']==['RL','DL'] for x in stability['reports']))
    write_json(out/'stability.json',stability)
    controls=[]
    for name,q,bounds,expected in [
        ('same_sign_positive',named_params(deployment_cost=0),b,1.),
        ('same_sign_negative',named_params(growth=0,deployment_cost=1),b,2.),
        ('true_zero',named_params(growth=0,deployment_cost=0),b,1.)]:
        result,points=snapshot_optimize(q,'DL',bounds)
        check(name+'_endpoint',result['delay']==expected,result)
        selected=independent_value(q,result['delay'],0,400)
        check(name+'_evaluated_order',all(selected>=independent_value(q,x['delay'],0,400) for x in points))
        controls.append({'case':name,'params':asdict(q),'result':result})
    strict=optimize(p,'DL',replace(b,scouting_points=3,tolerance=1.,payoff_atol=0,payoff_rtol=0),0)
    check('positive_underflow_probe_not_false_pass',not strict['local_quality_passed'] and strict['last_probe_improvement_diagnostic']['sign']==1 and strict['last_probe_improvement_diagnostic']['representation']=='underflow')
    write_json(out/'strict_quality.json',strict)
    try:optimize(p,'DL',replace(b,max_evaluations=65),0);budget=False
    except NumericalError as e:budget='budget' in str(e)
    check('guarded_search_budget_enforced',budget)
    try:
        optimize(named_params(discount=0,growth_end=1,horizon=1,margin_x=1e308,deployment_cost=0),
            'DL',DecisionBounds(delay_upper=1,announcement_upper=0,payoff_rtol=1e308))
        threshold_refused=False
    except NumericalError as e:threshold_refused='quality threshold' in str(e)
    check('unrepresentable_derived_quality_threshold_refused',threshold_refused)
    write_json(out/'controls.json',controls)
    def config(params=p,bounds=b,tolerance=0.):
        return {'params':asdict(params),'bounds':asdict(bounds),'rival_delay':0.,'comparison':{'tie_tolerance':tolerance}}
    def invoke(name,operation,cfg,expected_exit=0,resume=False):
        path=out/'configs'/(name+'.json');path.parent.mkdir(exist_ok=True);write_json(path,cfg)
        destination=out/'cli'/name
        command=[sys.executable,'-m','entrysignallab.cli',operation,'--config',str(path),'--out',str(destination)]+(['--resume'] if resume else [])
        result=subprocess.run(command,capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        item={'case':name,'command':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        check(name+'_exit',result.returncode==expected_exit,item)
        if expected_exit==0:
            item['manifest_verification']=verify_manifest(destination,current_source_hashes())
            check(name+'_manifest',item['manifest_verification']['valid'],item)
        cli.append(item);return destination
    for name,cfg,expected in [('named',config(),['RL','DL']),('default_tolerance',config(tolerance=1e-8),['RL','DL','no_entry']),
            ('fixed_negative',config(bounds=replace(b,delay_upper=1)),['no_entry']),('fixed_positive',config(bounds=replace(b,delay_lower=2)),['RL','DL'])]:
        dest=invoke(name,'optimize',cfg)
        check(name+'_preference',read_json(dest/'comparison.json')['preferred_with_outside_option']==expected)
    scientific=[]
    for workers in (1,2):
        cfg={**config(),'axes':{'deployment_cost':[1e45,1e45]},'batch':{'workers':workers,'checkpoint_every':1}}
        dest=invoke('sweep_'+str(workers),'sweep',cfg)
        with (dest/'sweep.csv').open() as f:rows=list(csv.DictReader(f))
        check('sweep_'+str(workers)+'_positive',len(rows)==8 and all(x['outside_option_preferred']=='RL|DL' for x in rows))
        scientific.append([{k:x[k] for k in ('case_index','strategy','delay','announcement','payoff','co_best','outside_option_preferred','outside_option_gap_sign')} for x in rows])
        cfg={**config(),'uncertainty':{'ranges':{'deployment_cost':[1e45,1e45]},'samples':2},'batch':{'workers':workers}}
        dest=invoke('uncertainty_'+str(workers),'uncertainty',cfg)
        check('uncertainty_'+str(workers)+'_positive',read_json(dest/'uncertainty_summary.json')['outside_option_summary']['entry_preferred']==2)
    check('serial_process_correspondence',scientific[0]==scientific[1])
    invoke('stability','optimize',{**config(),'stability':{'factors':[1,2,4]}})
    q=named_params(growth=0,discount=1e308,growth_end=1e308,horizon=1e308,deployment_cost=1)
    qb=DecisionBounds(delay_lower=5e307,delay_upper=1e308,announcement_upper=0)
    cfg=config(q,qb)
    dest=invoke('unresolved_strict','optimize',cfg,2)
    check('unresolved_before_output',not dest.exists())
    cfg.update(axes={'deployment_cost':[1,1]},on_error='record')
    dest=invoke('unresolved_record','sweep',cfg)
    check('unresolved_records_two_errors',read_json(dest/'sweep_summary.json')['failure_counts']['numerical_error']==2)
    cfg=config();cfg.update(axes={'deployment_cost':[1e45,1e45]},batch={'checkpoint_every':1})
    meta,tasks=prepare_sweep(p,b,0,cfg['axes'],cfg['comparison'],batch=cfg['batch'])
    dest=out/'cli/resume';dest.parent.mkdir(exist_ok=True)
    def interrupt(n):
        if n==1:raise RuntimeError('intentional acceptance interruption after committed case')
    try:run_batch(dest,p,b,0,meta,tasks,cfg,progress_callback=interrupt)
    except RuntimeError as e:check('resume_interrupted',str(e).startswith('intentional'))
    dest=invoke('resume','sweep',cfg,resume=True)
    check('resume_keeps_prefix',read_json(dest/'sweep_summary.json')['batch_execution']['resume_prefix_cases']==1)
    invoke('reproduce','reproduce',config())
    write_json(out/'CLI_observations.json',cli);write_json(out/'checks.json',checks)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'frozen_boundary_cases':len(corpus),
        'independent_optimized_results':len(observations),'evaluated_control_references':evaluated,
        'max_stationary_delay_error':max_delay_error,'CLI_processes':len(cli),
        'scope':'Independent 200/400-digit event integrals compare every recorded follower node in the scoped corpus; stationary brackets, exact-zero/monotone controls, strict quality, failure, cache/process and checkpoint replay. Local candidates and adaptive guards are not interval or global certificates.'}
    write_json(out/'v0210_summary.json',summary);record_validation(out,Path(__file__),seed=20261019)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
