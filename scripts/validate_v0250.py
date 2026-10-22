"""Independent typed-control and recorded-probe acceptance for A21/U03."""
from pathlib import Path
from fractions import Fraction as F
from decimal import Decimal as D,localcontext
from dataclasses import asdict
from math import isclose,ulp
from unittest.mock import patch
import argparse,csv,json,sys,subprocess
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,__version__
import entrysignallab.solver as solver
from entrysignallab.workflow import read_json,write_json,sha256,record_validation,prepare_uncertainty,current_source_hashes,verify_manifest
from entrysignallab.batch import run_batch


def typed_delay(row):
    H=row['params']['growth_end'];kind=row['input_type']
    if kind.startswith('Fraction'):return F(row['raw_delay'])
    if kind=='longdouble_below':return np.nextafter(np.longdouble(H),np.longdouble(0))
    return float(H)


def rational_gradient(p,st,t,d):
    s,n,H,T,w,m,c,t,d=map(F,(p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.announcement_cost,t,d))
    a=1+n*((s+d) if st=='RF' else d)*t;b=w if st=='RF' else w*(1+n*s*t)
    return m*s*(H-t)*(2*T-H-t)*n*t*b/(2*(a+b)**2)-c*d


def reference_value(p,row,digits=200):
    """Independent global antiderivatives, without operational integration helpers."""
    rational=p.discount==0 and (p.learning_rate==0 or p.deployment_cost==0 or row['strategy'].endswith('F'))
    def evaluate(convert):
        s,n,H,T,w,m,r,c,C,k,t,d=map(convert,(p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,p.deployment_cost,p.learning_rate,row['delay'],row['announcement']))
        st=row['strategy']
        if st=='RF':a,b=1+n*(s+d)*t,w
        elif st=='DF':a,b=1+n*s*t,w
        elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
        else:a,b=convert(1.),w*(1+n*s*t)
        if rational:
            mass=(H-t)*(2*T-H-t)/2;lead=t*(2*T-t)/2 if st.endswith('F') else 0;deployment=C
        else:
            def j0(x):return x if r==0 else (1-(-r*x).exp())/r
            def j1(x):return x*x/2 if r==0 else (1-(1+r*x)*(-r*x).exp())/(r*r)
            mass=j1(H)-j1(t)-t*(j0(H)-j0(t))+(H-t)*(j0(T)-j0(H))
            lead=j1(t)+t*(j0(T)-j0(t)) if st.endswith('F') else 0
            deployment=C if st.endswith('F') else C*(-(k+r)*t).exp()
        return m*s*(lead+mass*a/(a+b))-c*d*d/2-deployment
    if rational:return evaluate(F)
    with localcontext() as context:
        context.prec=digits
        return evaluate(D.from_float)


def check_probe_result(p,b,result):
    """Return independently evaluated checks; no optimizing oracle is assumed."""
    ledger=result['local_probe_diagnostics'];checks=[]
    def add(name,passed):checks.append({'name':name,'pass':bool(passed)})
    rounds=ledger['rounds'];lo,hi=b.validate(p)
    add('bounded_rounds',len(rounds)<=4)
    add('round_count',len(rounds)==result.get('probe_rounds',0))
    if not rounds:return checks
    for i,record in enumerate(rounds):
        start=record['starting_control'];selected=record['selected_control'];probes=record['probes'];threshold=record['quality_threshold'];gap=record['improvement_diagnostic']
        add('round_sequence_'+str(i),record['round']==i+1)
        add('two_sided_probes_'+str(i),[x['side'] for x in probes]==['lower','upper'])
        add('control_chain_'+str(i),i==0 or start==rounds[i-1]['selected_control'])
        add('threshold_'+str(i),threshold==b.payoff_atol+b.payoff_rtol*abs(selected['payoff']))
        for item in [start,selected,*[x['control'] for x in probes]]:
            add('configured_control_'+str(i),lo<=item['delay']<=hi and (b.announcement_upper is None or item['announcement']<=b.announcement_upper))
        for item in probes:
            add('coincidence_flag_'+str(i),item['distinct_from_start']==(item['control']['delay']!=start['delay']))
        independent=[]
        for digits in (200,400):
            with localcontext() as context:
                context.prec=digits
                difference=reference_value(p,selected,digits)-reference_value(p,start,digits)
                tol=F(threshold) if isinstance(difference,F) else D.from_float(threshold)
                independent.append((float(difference),(difference>0)-(difference<0),1 if difference>tol else -1 if difference < -tol else 0))
        add('two_independent_precisions_'+str(i),independent[0]==independent[1])
        amount,sign,relation=independent[-1]
        add('reference_sign_'+str(i),gap['sign']==sign)
        add('reference_tolerance_'+str(i),gap['tolerance_relation']==relation)
        if gap['decision_basis']=='rounded_payoff_difference':
            scale=max(abs(start['payoff']),abs(selected['payoff']),threshold,1e-300)
            add('reference_amount_'+str(i),abs(gap['value']-amount)<=1e-10*scale)
        else:add('reference_amount_'+str(i),isclose(gap['value'],amount,rel_tol=1e-12,abs_tol=2*ulp(amount)))
        add('quality_flag_'+str(i),record['passed']==(relation<=0))
        add('promotion_flag_'+str(i),record['control_promoted']==(selected['delay']!=start['delay']))
        add('termination_'+str(i),record['termination']==('within_quality_tolerance' if record['passed'] else 'round_limit' if i==3 else 'continue'))
    last=rounds[-1]
    add('returned_control',last['selected_control']=={k:result[k] for k in ['strategy','delay','announcement','payoff']})
    add('last_gap_correspondence',last['improvement_diagnostic']==result['last_probe_improvement_diagnostic'])
    add('last_quality_correspondence',last['passed']==result['local_quality_passed'])
    add('final_neighborhood_correspondence',ledger['final_control_neighborhood_assessed']==result['local_improvement_residual_assessment']['final_control_neighborhood_assessed']==last['selected_control_neighborhood_assessed'])
    return checks


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];data=root/'tests/data';checks=[];ingress=[];profiles=[];probe_cases=[];cli=[]
    def check(name,passed,detail=None):
        checks.append({'name':name,'pass':bool(passed),'detail':detail})
        if not passed:raise AssertionError((name,detail))
    for name,digest in read_json(data/'v0240_corpus_identity.json').items():check('frozen_'+name,sha256(data/name)==digest)
    wide=np.finfo(np.longdouble).nmant>np.finfo(float).nmant;skipped=0
    for i,x in enumerate(read_json(data/'v0240_ingress_observations.json')):
        if x['input_type']=='longdouble_below' and not wide:skipped+=1;continue
        p=ModelParams(**x['params']);t=typed_delay(x);actual=solver.profile_announcement(p,x['strategy'],t,x['cap'])
        check('typed_binary64_'+str(i),actual==tuple(x['canonical_reference']),actual)
        ingress.append({'case_index':i,'actual':actual,'input_type':x['input_type']})
    corpus=read_json(data/'v0240_profile_cases.json')
    for i,x in enumerate(corpus):
        p=ModelParams(**x['params']);st=x['strategy'];t=x['delay'];cap=x['cap'];actual=solver.profile_announcement(p,st,t,cap)[0]
        if x['check_kind']=='finite_cap':
            check('root_cap_sign_'+str(i),rational_gradient(p,st,t,cap)>=0)
            check('root_cap_'+str(i),actual==cap)
        else:
            lo,hi=x['reference_adjacent_lower'],x['reference_adjacent_upper']
            check('root_bracket_sign_'+str(i),rational_gradient(p,st,t,lo)>=0 and rational_gradient(p,st,t,hi)<=0)
            check('root_accuracy_'+str(i),lo<=actual<=hi or abs(actual-lo)/lo<=1e-9)
        check('root_native_control_preserved_'+str(i),actual==x['actual'])
        profiles.append({'case_index':i,'actual':actual})
    for x in read_json(data/'v0240_probe_baselines.json'):
        c=x['config'];p=ModelParams(**c.get('params',{}));b=DecisionBounds(**c.get('bounds',{}));rival=c.get('rival_delay',min(.15,p.growth_end));report=compare(p,b,rival,**c.get('comparison',{}))
        for key,value in x['original_comparison'].items():
            if key!='results':check('scientific_comparison_'+x['name']+'_'+key,report[key]==value)
        for old,result in zip(x['original_comparison']['results'],report['results']):
            check('scientific_result_'+x['name']+'_'+old['strategy'],all(result[key]==value for key,value in old.items()))
            for row in check_probe_result(p,b,result):check(x['name']+'_'+old['strategy']+'_'+row['name'],row['pass'])
            captured={};fn=solver.payoff
            def observed(q,st,t,d):
                v=fn(q,st,t,d);captured[(st,t,d)]=v;return v
            with patch.object(solver,'payoff',observed):wrapped=optimize(p,old['strategy'],b,rival)
            check('recording_does_not_change_result_'+x['name']+'_'+old['strategy'],wrapped==result)
            if result['payoff'] is not None:
                check('no_extra_objective_evaluations_'+x['name']+'_'+old['strategy'],len(captured)==result['evaluations'])
                for record in result['local_probe_diagnostics']['rounds']:
                    for control in [record['starting_control'],record['selected_control'],*[v['control'] for v in record['probes']]]:
                        check('actually_evaluated_'+x['name']+'_'+old['strategy'],captured[(control['strategy'],control['delay'],control['announcement'])]==control['payoff'])
            probe_cases.append({'name':x['name'],'result':result})
    def invoke(name,operation,c):
        cfg=out/(name+'_config.json');write_json(cfg,c);dest=out/name
        run=subprocess.run([sys.executable,'-m','entrysignallab.cli',operation,'--config',str(cfg),'--out',str(dest)],capture_output=True,text=True)
        (out/(name+'_stdout.log')).write_text(run.stdout);(out/(name+'_stderr.log')).write_text(run.stderr)
        check('CLI_'+name,run.returncode==0,run.stderr[-1200:]);check('manifest_'+name,verify_manifest(dest,current_source_hashes())['valid'])
        cli.append({'name':name,'operation':operation,'exit':run.returncode});return dest
    cases={x['name']:x for x in read_json(data/'v0240_probe_baselines.json')}
    for name in ['quality_warning_html','recorded_probe_promoted','gross_cancellation_ranking','product_launch']:
        dest=invoke(name,'reproduce',cases[name]['config']);c=read_json(dest/'comparison.json');html=(dest/'report.html').read_text()
        check('HTML_record_link_'+name,'local_probe_diagnostics' in html and 'href="config.json"' in html)
        check('HTML_actual_round_count_'+name,html.count('data-probe-round=')==sum(len(r['local_probe_diagnostics']['rounds']) for r in c['results'] if r['strategy'].endswith('L')))
        check('HTML_warning_'+name,('id="payoff-display-warning"' in html)==(name=='gross_cancellation_ranking'))
        with (dest/'optima.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        check('CSV_json_roundtrip_'+name,all(json.loads(row['local_probe_diagnostics'])==r['local_probe_diagnostics'] for row,r in zip(rows,c['results'])))
    cfg=cases['recorded_probe_promoted']['config'];summaries=[]
    for workers in [1,2]:
        c={k:v for k,v in cfg.items() if k!='stability'};c.update(uncertainty={'ranges':{'deployment_cost':[.012,.012]},'samples':3},batch={'workers':workers,'checkpoint_every':1})
        dest=invoke('batch_'+str(workers),'uncertainty',c);summary=read_json(dest/'uncertainty_summary.json');summary.pop('batch_execution');summaries.append(summary)
        with (dest/'uncertainty.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        check('batch_json_probe_records_'+str(workers),all(json.loads(row['local_probe_diagnostics'])['policy']=='recorded_local_probes_v1' for row in rows))
    check('serial_process_scientific_summary',summaries[0]==summaries[1])
    p=ModelParams(**cfg['params']);b=DecisionBounds(**cfg['bounds']);meta,tasks=prepare_uncertainty(p,b,0,{'deployment_cost':[.012,.012]},n=3,batch={'checkpoint_every':1})
    def stop(n):
        if n==1:raise RuntimeError('intentional prefix stop')
    try:run_batch(out/'resume',p,b,0,meta,tasks,{'test':'v0250'},progress_callback=stop)
    except RuntimeError:check('intentional_prefix_stop',True)
    else:check('intentional_prefix_stop',False)
    resumed=run_batch(out/'resume',p,b,0,meta,tasks,{'test':'v0250'},resume=True)
    check('resume_completed',resumed['completed_samples']==3 and resumed['batch_execution']['resume_prefix_cases']==1)
    with (out/'resume/uncertainty.csv').open(newline='') as f:rows=list(csv.DictReader(f))
    check('resume_probe_roundtrip',all(json.loads(row['local_probe_diagnostics'])['policy']=='recorded_local_probes_v1' for row in rows))
    write_json(out/'ingress.json',ingress);write_json(out/'profiles.json',profiles);write_json(out/'probe_cases.json',probe_cases);write_json(out/'CLI_observations.json',cli);write_json(out/'checks.json',checks)
    summary={'version':__version__,'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'typed_ingress_cases':len(ingress),'wide_longdouble_supported':bool(wide),'wide_cases_skipped':skipped,'profile_cases':len(profiles),'unchanged_native_controls':len(profiles),'baseline_parameter_sets':len(cases),'probe_results':len(probe_cases),'CLI_processes':len(cli),'scope':'Original binary64 rational derivatives and independent global antiderivatives at recorded controls, with 200/400-digit agreement. Existing scientific fields preserved on frozen native-control baselines. Bounded records do not certify continuous or global optimality.'}
    write_json(out/'v0250_summary.json',summary);record_validation(out,Path(__file__),20261020);print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
