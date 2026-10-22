"""Independent fixed-control mesh-spread and API-documentation acceptance."""
from pathlib import Path
from dataclasses import asdict,replace
from decimal import Decimal,localcontext,MAX_EMAX,MIN_EMIN
from fractions import Fraction as F
from math import isfinite,ulp
import argparse,json,os,subprocess,sys
from entrysignallab import ModelParams,DecisionBounds,compare_stability
from entrysignallab.solver import NumericalError
from entrysignallab.workflow import (read_json,write_json,record_validation,
                                   verify_manifest,current_source_hashes)
from sync_api_docs import synchronize


def named_params(**changes):
    return ModelParams(**{'growth':1,'network':1,'growth_end':3,'horizon':3,
        'margin_x':.001,'deployment_cost':1e14,**changes})


def named_bounds(**changes):
    return DecisionBounds(**{'delay_lower':0,'delay_upper':3,'announcement_upper':100,
        'scouting_points':3,'tolerance':1,'payoff_atol':1e-8,'payoff_rtol':0,**changes})


def comparison_projection(value):
    """Retain every old field except the explicitly revised diagnostic schema.

    Version 0.23.0 changes the legacy residual and adds diagnostic metadata.
    Version 0.25.0 adds a separately validated actual-probe ledger.
    Frozen controls, payoffs, policies and scenario comparisons stay checked.
    """
    if isinstance(value,list):return [comparison_projection(x) for x in value]
    if isinstance(value,dict):return {k:comparison_projection(v) for k,v in value.items()
        if k not in {'announcement_stationarity_diagnostic','local_improvement_residual','local_improvement_residual_assessment','local_probe_diagnostics'}}
    return value


def rational_objective(p,row):
    """Exact original-input event integral with all decays equal to one."""
    assert p.discount==0 and p.learning_rate==0
    s,n,H,T,w,m,c,C,t,d=map(F,(p.growth,p.network,p.growth_end,p.horizon,
        p.quality_ratio,p.margin_x,p.announcement_cost,p.deployment_cost,row['delay'],row['announcement']))
    st=row['strategy']
    if st=='RF':a,b=1+n*(s+d)*t,w
    elif st=='DF':a,b=1+n*s*t,w
    elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
    else:a,b=F(1),w*(1+n*s*t)
    lead=t*(2*T-t)/2 if st.endswith('F') else F(0)
    response=(H-t)*(2*T-H-t)/2
    return m*s*(lead+response*a/(a+b))-c*d*d/2-C


def decimal_objective(p,row,precision=400):
    """Independent unrestricted-decay event integral at a recorded control.

    Integrate the pre-entry leader stock, then the growing follower stock and
    its mature tail. No production payoff/integral/signature/guard is called.
    """
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,H,T,w,m,r,c,C,k,t,d=map(Decimal.from_float,(p.growth,p.network,p.growth_end,
            p.horizon,p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,
            p.deployment_cost,p.learning_rate,row['delay'],row['announcement']))
        def moments(L):
            if r==0:return L,L*L/2
            e=(-r*L).exp()
            return (1-e)/r,(1-(1+r*L)*e)/(r*r)
        st=row['strategy']
        if st=='RF':a,b=1+n*(s+d)*t,w
        elif st=='DF':a,b=1+n*s*t,w
        elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
        else:a,b=Decimal(1),w*(1+n*s*t)
        response=(-r*t).exp()*moments(H-t)[1]+(H-t)*(-r*H).exp()*moments(T-H)[0]
        lead=moments(t)[1]+t*(-r*t).exp()*moments(T-t)[0] if st.endswith('F') else Decimal(0)
        entry=Decimal(0) if st.endswith('F') else t
        return m*s*(lead+response*a/(a+b))-c*d*d/2-C*(-(k+r)*entry).exp()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];cases=[];cli=[]
    def check(name,passed,detail=None):
        checks.append({'name':name,'pass':bool(passed),'detail':detail})
        if not passed:raise AssertionError((name,detail))
    frozen=read_json(root/'tests/data/v0210_A16_rational_corpus.json')
    check('frozen_rational_inventory',len(frozen)==18)
    total_references=0;false_passes=0;unchanged_reports=0
    for old in frozen:
        name=old['name'];p=ModelParams(**old['params']);b=DecisionBounds(**old['bounds'])
        report=compare_stability(p,b,0,{'tie_tolerance':0},(1,2,4));refs=[]
        check(name+'_unchanged_controls_and_comparison',comparison_projection(report['reports'])==comparison_projection(old['report']['reports']))
        unchanged_reports+=len(report['reports'])
        check(name+'_new_policy',report['payoff_stability_precision']['policy']=='original_input_mesh_spread_v1')
        for i,st in enumerate(('RF','RL','DF','DL')):
            controls=[r['results'][i] for r in report['reports']]
            values=[rational_objective(p,x) for x in controls];spread=max(values)-min(values)
            row=report['strategies'][i];diagnostic=row['observed_payoff_spread_diagnostic']
            threshold=F(row['quality_threshold']);expected=spread<=threshold
            check(name+'_'+st+'_amount',row['observed_payoff_spread']==float(spread))
            check(name+'_'+st+'_sign',diagnostic['sign']==int(spread>0))
            check(name+'_'+st+'_band',diagnostic['tolerance_relation']==int(spread>threshold))
            check(name+'_'+st+'_flag',row['within_quality_tolerance']==expected)
            maximum=report['factors'].index(row['maximum_payoff_factor']);minimum=report['factors'].index(row['minimum_payoff_factor'])
            check(name+'_'+st+'_selected_controls',values[maximum]==max(values) and values[minimum]==min(values))
            refs.append({'strategy':st,'exact_spread_numerator':str(spread.numerator),
                         'exact_spread_denominator':str(spread.denominator),'spread_float':float(spread),
                         'threshold_float':float(threshold),'expected_within_tolerance':expected})
            total_references+=len(values)
        expected_stable=all(x['expected_within_tolerance'] for x in refs)
        check(name+'_aggregate',report['payoff_stable']==expected_stable)
        if old['name'] not in ('identical_fixed_control','positive_absolute_band'):
            check(name+'_false_pass_repaired',old['report']['payoff_stable'] and not report['payoff_stable'])
            false_passes+=1
        cases.append({'name':name,'params':asdict(p),'bounds':asdict(b),'report':report,'references':refs})
    check('sixteen_original_false_passes_repaired',false_passes==16)
    write_json(out/'rational_spread_cases.json',cases)
    named=next(x for x in cases if x['params']==asdict(named_params()) and x['bounds']==asdict(named_bounds()))
    check('named_ranking_still_agrees',named['report']['ranking_stable'])
    check('named_local_quality_remains_separate',named['report']['reports'][0]['local_quality_status']=='fail' and named['report']['reports'][-1]['local_quality_status']=='pass')
    write_json(out/'named.json',named)
    relative_cases=[]
    for rtol in (1e-19,1e-16):
        p=named_params();b=named_bounds(payoff_atol=0.,payoff_rtol=rtol)
        report=compare_stability(p,b,0,{'tie_tolerance':0});row=report['strategies'][1]
        values=[rational_objective(p,x['results'][1]) for x in report['reports']]
        spread=max(values)-min(values);threshold=F(row['quality_threshold'])
        check('relative_'+str(rtol)+'_amount',row['observed_payoff_spread']==float(spread))
        check('relative_'+str(rtol)+'_flag',row['within_quality_tolerance']==(spread<=threshold))
        check('relative_'+str(rtol)+'_threshold',row['quality_threshold']==rtol*max(abs(x) for x in row['payoffs']))
        relative_cases.append({'params':asdict(p),'bounds':asdict(b),'report':report,'reference_spread':float(spread),'threshold':float(threshold)})
        total_references+=len(values)
    write_json(out/'relative_bands.json',relative_cases)

    old_under=read_json(root/'tests/data/v0210_A16_underflow.json')
    decimals=[];max_relative_error=0.;max_log_error=0.;underflow_results=0
    params=ModelParams(**old_under['params']);bounds=DecisionBounds(**old_under['bounds'])
    same_control=compare_stability(params,bounds,0,{'tie_tolerance':0},(1,2))
    check('mesh_agreement_can_coexist_with_failed_local_checks',same_control['payoff_stable'] and all(x['local_quality_status']=='fail' for x in same_control['reports']))
    check('matching_controls_explain_zero_mesh_spread',all(
        same_control['reports'][0]['results'][i][key]==same_control['reports'][1]['results'][i][key]
        for i in range(4) for key in ('strategy','delay','announcement','payoff')))
    write_json(out/'same_controls_failed_local_quality.json',same_control)
    decimal_cases=[('underflow_zero',params,bounds),
        ('underflow_positive_band',params,replace(bounds,payoff_atol=float.fromhex('0x0.0000000000001p-1022')))]
    for discount in (0.,1e-12,.4,100.):
        p=ModelParams(growth=.1,network=.85,growth_end=.3,horizon=1,quality_ratio=1.8,
                      margin_x=.25,announcement_cost=.0002,deployment_cost=.012,
                      learning_rate=12,discount=discount)
        decimal_cases.append(('discount_'+str(discount),p,DecisionBounds(announcement_upper=2,
            scouting_points=3,tolerance=.1,payoff_atol=1e-10,payoff_rtol=1e-8)))
    for name,p,b in decimal_cases:
        report=compare_stability(p,b,0,{'tie_tolerance':0},(1,2,4));refs=[]
        for i,st in enumerate(('RF','RL','DF','DL')):
            controls=[r['results'][i] for r in report['reports']]
            a=[decimal_objective(p,x,200) for x in controls];values=[decimal_objective(p,x,400) for x in controls]
            with localcontext() as ctx:
                ctx.prec=450
                spread200=max(a)-min(a);spread=max(values)-min(values)
                row=report['strategies'][i];threshold=Decimal.from_float(row['quality_threshold'])
                diagnostic=row['observed_payoff_spread_diagnostic']
                check(name+'_'+st+'_two_precisions',int(spread200>threshold)==int(spread>threshold) and float(spread200)==float(spread))
                check(name+'_'+st+'_sign',diagnostic['sign']==int(spread>0))
                check(name+'_'+st+'_band',diagnostic['tolerance_relation']==int(spread>threshold))
                check(name+'_'+st+'_flag',row['within_quality_tolerance']==(spread<=threshold))
                maximum=report['factors'].index(row['maximum_payoff_factor']);minimum=report['factors'].index(row['minimum_payoff_factor'])
                check(name+'_'+st+'_selected_controls',values[maximum]==max(values) and values[minimum]==min(values))
                if spread and float(spread):
                    relative=float(abs(Decimal.from_float(row['observed_payoff_spread'])-spread)/abs(spread))
                    max_relative_error=max(max_relative_error,relative)
                    check(name+'_'+st+'_amount_accuracy',relative<1e-8,relative)
                else:check(name+'_'+st+'_zero_amount',row['observed_payoff_spread']==0.)
                log_abs=float(spread.ln()) if spread else None
                if spread:
                    log_error=abs(diagnostic['log_abs']-log_abs);max_log_error=max(max_log_error,log_error)
                    # Ordinary far differences retain the rounded fast path;
                    # they do not promise correctly rounded logarithms.
                    tolerance=8*ulp(log_abs) if name.startswith('underflow') else 1e-8
                    check(name+'_'+st+'_log_accuracy',log_error<=tolerance,log_error)
                if name.startswith('underflow') and st.endswith('L'):
                    check(name+'_'+st+'_underflow_representation',diagnostic['representation']=='underflow' and diagnostic['sign']==1)
                    underflow_results+=1
                refs.append({'strategy':st,'reference_spread_400':str(spread),'log_abs':log_abs,
                             'reference_threshold':str(threshold),'expected_stable':bool(spread<=threshold)})
            total_references+=2*len(controls)
        check(name+'_aggregate',report['payoff_stable']==all(x['expected_stable'] for x in refs))
        decimals.append({'name':name,'params':asdict(p),'bounds':asdict(b),'report':report,'references':refs})
    write_json(out/'decimal_spread_cases.json',decimals)
    null=compare_stability(ModelParams(),DecisionBounds(announcement_upper=None),.15,factors=(1,2))
    check('null_candidate_withholds_stability',not null['payoff_stable'] and not null['ranking_stable'])
    check('null_candidate_diagnostic_missing',all(x['observed_payoff_spread_diagnostic'] is None and x['maximum_payoff_factor'] is None for x in null['strategies'][:2]))
    write_json(out/'null_optima.json',null)
    overflow_p=ModelParams(growth=0,margin_x=0,deployment_cost=1e308)
    overflow_b=DecisionBounds(announcement_upper=0,payoff_rtol=1e308)
    try:compare_stability(overflow_p,overflow_b,0,factors=(1,2));refused=False
    except NumericalError as e:refused='mesh stability quality threshold' in str(e)
    check('unrepresentable_threshold_refused',refused)
    synchronize(root,check=True);check('generated_api_contract_current',True)
    frozen_identity=read_json(root/'tests/data/v0210_A16_corpus_identity.json')['files_sha256']
    import hashlib
    for name,digest in frozen_identity.items():
        check('frozen_corpus_'+name,hashlib.sha256((root/'tests/data'/name).read_bytes()).hexdigest()==digest)

    def cfg(p=named_params(),b=named_bounds()):
        return {'params':asdict(p),'bounds':asdict(b),'rival_delay':0.,'comparison':{'tie_tolerance':0.},'stability':{'factors':[1,2,4]}}
    def invoke(name,operation,config,expected_exit=0,error_text=None):
        path=out/'configs'/(name+'.json');path.parent.mkdir(exist_ok=True);write_json(path,config);destination=out/'cli'/name
        command=[sys.executable,'-m','entrysignallab.cli',operation,'--config',str(path),'--out',str(destination)]
        process=subprocess.run(command,capture_output=True,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        record={'case':name,'command':command,'returncode':process.returncode,'stdout':process.stdout,'stderr':process.stderr}
        check(name+'_CLI_exit',process.returncode==expected_exit,record)
        if expected_exit==0:
            verification=verify_manifest(destination,current_source_hashes());check(name+'_CLI_manifest',verification['valid'],verification)
        else:
            check(name+'_no_output',not destination.exists())
            if error_text:check(name+'_error_message',error_text in process.stderr)
        cli.append(record);return destination
    dest=invoke('named','optimize',cfg());r=read_json(dest/'stability.json')
    check('named_CLI_repaired',not r['payoff_stable'] and r['strategies'][1]['observed_payoff_spread']>1e-8)
    for name,pp,bb in decimal_cases[:2]:
        dest=invoke(name,'optimize',cfg(pp,bb));r=read_json(dest/'stability.json')
        check(name+'_CLI_relation',r['payoff_stable']==(name=='underflow_positive_band'))
    dest=invoke('fixed','optimize',cfg(b=replace(named_bounds(),delay_lower=.25,delay_upper=.25)))
    check('fixed_CLI_stable',read_json(dest/'stability.json')['payoff_stable'])
    dest=invoke('null','optimize',cfg(ModelParams(),DecisionBounds(announcement_upper=None)))
    check('null_CLI_withheld',not read_json(dest/'stability.json')['payoff_stable'])
    invoke('threshold_refusal','optimize',cfg(overflow_p,overflow_b),2,'mesh stability quality threshold')
    doc_config=read_json(root/'examples/documented_uncertainty_batch.json');summaries=[]
    for workers in (1,2):
        config={**doc_config,'batch':{'workers':workers,'checkpoint_every':1}}
        dest=invoke('documented_options_'+str(workers),'uncertainty',config)
        summary=read_json(dest/'uncertainty_summary.json');summaries.append({key:summary[key] for key in ('summary','outside_option_summary','payoff_summaries','quality_status_counts')})
        check('documented_options_'+str(workers)+'_completed',summary['samples']==2 and not summary['failed_samples'])
    check('documented_serial_process_correspondence',summaries[0]==summaries[1])
    invalid={**doc_config,'uncertainty':{**doc_config['uncertainty'],'batch':{'workers':1}}};invalid.pop('batch')
    invoke('nested_batch_rejected','uncertainty',invalid,2,'unknown uncertainty keys')
    ordinary=cfg(ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12),DecisionBounds(announcement_upper=2))
    dest=invoke('ordinary_reproduce','reproduce',ordinary)
    check('reproduce_emits_spread_policy',read_json(dest/'stability.json')['payoff_stability_precision']['policy']=='original_input_mesh_spread_v1')
    write_json(out/'CLI_processes.json',cli);write_json(out/'checks.json',checks)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),
        'frozen_rational_cases':len(frozen),'rational_false_passes_repaired':false_passes,
        'rational_relative_cases':len(relative_cases),
        'normal_controls':2,'unchanged_original_mesh_reports':unchanged_reports,
        'decimal_cases':len(decimals),'underflow_strategy_results':underflow_results,
        'independent_control_references':total_references,'max_decimal_spread_relative_error':max_relative_error,
        'independent_recorded_control_observations':sum(len(x['report']['reports'])*len(x['references']) for x in cases+decimals)+sum(len(x['report']['reports']) for x in relative_cases),
        'reference_count_rule':'One exact-rational evaluation per rational control observation; two independent precision evaluations per Decimal control observation.',
        'max_decimal_spread_log_error':max_log_error,
        'named_spread':named['report']['strategies'][1]['observed_payoff_spread'],
        'CLI_processes':len(cli),'frozen_corpus_files':len(frozen_identity),
        'scope':'Independent rational and 200/400-digit event integrals at returned controls, tolerance semantics, nulls, controlled refusal, documentation and actual CLI. No continuous global, interval, empirical or external-CI certification.'}
    write_json(out/'v0220_summary.json',summary);record_validation(out,Path(__file__),seed=20261019)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
