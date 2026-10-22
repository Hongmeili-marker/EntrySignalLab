"""Independent A20 cancellation and A19 endpoint-root acceptance."""
from pathlib import Path
from fractions import Fraction as F
from decimal import Decimal as D,localcontext
from dataclasses import asdict,replace
from unittest.mock import patch
import argparse,csv,json,subprocess,sys
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,compare_stability,__version__
import entrysignallab.solver as solver
from entrysignallab.workflow import read_json,write_json,record_validation,sha256


def rational_payoff(p,row):
    """Original event integral, independent of production objective helpers."""
    assert p.discount==0 and p.learning_rate==0
    s,n,H,T,w,m,c,C,t,d=map(F,(p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.announcement_cost,p.deployment_cost,row['delay'],row['announcement']))
    st=row['strategy']
    if st=='RF':a,b=1+n*(s+d)*t,w
    elif st=='DF':a,b=1+n*s*t,w
    elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
    else:a,b=F(1),w*(1+n*s*t)
    leader=t*(2*T-t)/2 if st.endswith('F') else 0
    return m*s*(leader+(H-t)*(2*T-H-t)*a/(2*(a+b)))-c*d*d/2-C


def rational_gradient(p,st,t,d):
    s,n,H,T,w,m,c,t,d=map(F,(p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.announcement_cost,t,d))
    a=1+n*((s+d) if st=='RF' else d)*t;b=w if st=='RF' else w*(1+n*s*t)
    return m*s*(H-t)*(2*T-H-t)*n*t*b/(2*(a+b)**2)-c*d


def policy_reference(p,report,tolerance,outside=0.):
    values=[rational_payoff(p,row) for row in report['results']];best=max(values)
    names=[row['strategy'] for row,value in zip(report['results'],values) if best-value<=F(tolerance)]
    gap=best-F(outside)
    return names,names if gap>F(tolerance) else ['no_entry'] if gap < -F(tolerance) else names+['no_entry']


def node_reference(p,t,digits):
    """Independent DL event integral for the zero-network cancellation corpus."""
    assert p.network==p.discount==0 and p.growth==1 and p.growth_end==p.horizon==3
    with localcontext() as ctx:
        ctx.prec=digits;t=D.from_float(t)
        return D.from_float(p.margin_x)*(3-t)**2/4-D.from_float(p.deployment_cost)*(-D.from_float(p.learning_rate)*t).exp()


def captured_node_case(p,b):
    points=[];original=solver.payoff
    def observe(q,st,t,d):
        value=original(q,st,t,d);points.append(t);return value
    with patch.object(solver,'payoff',observe):result=optimize(p,'DL',b,0)
    refs=[]
    for digits in (200,400):
        values={t:node_reference(p,t,digits) for t in points}
        with localcontext() as ctx:
            ctx.prec=digits
            best=max(values,key=values.get);gap=values[best]-node_reference(p,result['delay'],digits)
        refs.append({'best_delay':best,'gap':float(gap)})
    return result,points,refs


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];data=root/'tests/data';checks=[];cases=[];cli=[]
    def check(name,passed,detail=None):
        checks.append({'name':name,'pass':bool(passed),'detail':detail})
        if not passed:raise AssertionError((name,detail))
    for name,digest in read_json(data/'v0230_corpus_identity.json').items():
        check('frozen_'+name,sha256(data/name)==digest)
    corpus=read_json(data/'v0230_cancellation_comparisons.json')
    for i,x in enumerate(corpus):
        p=ModelParams(**x['params']);b=DecisionBounds(**x['bounds']);tol=x['tie_tolerance']
        report=compare(p,b,x['rival_delay'],tie_tolerance=tol);names,preferred=policy_reference(p,report,tol)
        check('cancellation_'+str(i),report['co_best']==names and report['preferred_with_outside_option']==preferred)
        cases.append({'group':'cancellation','index':i,'co_best':report['co_best'],'reference':names,'preferred':preferred})
    ordinary=0
    for scale in [1.,1e8,1e16,1e24]:
      for ratio in [1e12,1e13,3e13,1e14,3e14,1e15,1e16]:
       for fraction in [0.,.1,.5]:
        for tol in [0.,1e-8]:
         p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=scale,announcement_cost=scale*ratio,deployment_cost=(23/6)*scale*fraction)
         report=compare(p,DecisionBounds(delay_lower=1,delay_upper=1),1,tie_tolerance=tol)
         names,preferred=policy_reference(p,report,tol)
         check('ordinary_'+str(ordinary),report['co_best']==names and report['preferred_with_outside_option']==preferred);ordinary+=1
    nodes=read_json(data/'v0230_evaluated_node_observations.json');node_records=[]
    for i,x in enumerate(nodes):
        p=ModelParams(**x['params']);b=DecisionBounds(**x['bounds'])
        result,points,refs=captured_node_case(p,b)
        check('node_'+str(i)+'_two_independent_precisions',refs[0]==refs[1])
        check('node_'+str(i)+'_best_evaluated',refs[-1]['gap']==0,refs[-1])
        check('node_'+str(i)+'_all_candidate_checks',result['search_precision']['evaluated_candidate_consistency_checks']==len(points)-1)
        check('node_'+str(i)+'_uninstrumented',result==optimize(p,'DL',b,0))
        node_records.append({'params':asdict(p),'bounds':asdict(b),'result':result,'evaluated_delays':points,'reference_200_400':refs})
    roots=read_json(data/'v0230_representable_root_edges.json');root_records=[]
    for i,x in enumerate(roots):
        p=ModelParams(**x['params']);b=replace(DecisionBounds(**x['bounds']),delay_lower=x['rival_delay'],delay_upper=x['rival_delay'])
        r=optimize(p,x['strategy'],b,x['rival_delay'])
        check('root_'+str(i)+'_exact_reference',rational_gradient(p,x['strategy'],x['rival_delay'],x['reference_root'])==0)
        check('root_'+str(i)+'_finite_positive',r['announcement']>0 and r['payoff'] is not None and r['status']=='profile_optimum')
        if x['group']=='minimum':check('root_'+str(i)+'_minimum_exact',r['announcement']==x['reference_root'])
        root_records.append({'case':x,'fixed_profile_bounds':asdict(b),'result':r})
    for i,factor in enumerate([.5,1.,2.]):
        p=ModelParams(growth=1,network=1,growth_end=2,horizon=2,margin_x=1,announcement_cost=.03125*factor)
        check('ordinary_root_'+str(i),optimize(p,'RF',DecisionBounds(announcement_upper=None),1)['announcement']>0)
    for i,x in enumerate(read_json(data/'v0220_A18_roots.json')):
        try:optimize(ModelParams(**x['params']),x['result']['strategy'],DecisionBounds(**x['bounds']),2)
        except solver.NumericalError:check('true_below_range_'+str(i),True)
        else:check('true_below_range_'+str(i),False)

    named=next(x for x in corpus if x['params']['margin_x']==1e16 and x['params']['announcement_cost']==1e29 and x['tie_tolerance']==1e-8 and x['params']['deployment_cost']==3.8333332949616664e16)
    config={'params':named['params'],'bounds':named['bounds'],'rival_delay':1}
    p=ModelParams(**named['params']);b=DecisionBounds(**named['bounds']);report=compare(p,b,1)
    check('named_RF_wins',report['co_best']==['RF'])
    check('named_original_gap',abs(report['entry_payoff_gap']-24.691358024690995)<1e-12)
    for offset in [-1.,0.,1.]:
        outside=float(rational_payoff(p,report['results'][0]))+offset
        r=compare(p,b,1,outside_option=outside);_,preferred=policy_reference(p,r,1e-8,outside)
        check('outside_'+str(offset),r['preferred_with_outside_option']==preferred)
    stability=compare_stability(p,b,1,factors=(1,2))
    check('mesh_RF_wins',all(x['co_best']==['RF'] for x in stability['reports']))
    def supplied(p,st,b,r):return {'strategy':st,'payoff':1.}
    extension=compare(p,b,1,optimizer=supplied,outside_option=1.)
    check('extension_values_retained',extension['co_best']==['RF','RL','DF','DL'] and 'comparison_precision' not in extension)
    def invoke(name,operation,config,expected=0):
        cfg=out/(name+'_config.json');write_json(cfg,config);dest=out/name
        run=subprocess.run([sys.executable,'-m','entrysignallab.cli',operation,'--config',str(cfg),'--out',str(dest)],capture_output=True,text=True)
        (out/(name+'_stdout.log')).write_text(run.stdout);(out/(name+'_stderr.log')).write_text(run.stderr)
        cli.append({'name':name,'operation':operation,'exit':run.returncode,'expected_exit':expected})
        check('CLI_'+name,run.returncode==expected,run.stderr[-1500:])
        if expected:check('CLI_'+name+'_controlled_refusal',not dest.exists() and 'floating-point range' in run.stderr)
        return dest
    dest=invoke('cancellation','optimize',config);check('CLI_RF',read_json(dest/'comparison.json')['co_best']==['RF'])
    dest=invoke('report','reproduce',{**config,'stability':{'factors':[1,2]}})
    check('CLI_report_RF',read_json(dest/'comparison.json')['co_best']==['RF'])
    check('CLI_report_links','comparison.json' in (dest/'report.html').read_text())
    batches=[];batch_rows=[]
    for workers in [1,2]:
        dest=invoke('batch_'+str(workers),'uncertainty',{**config,'uncertainty':{'ranges':{'growth':[1,1]},'samples':2},'batch':{'workers':workers,'checkpoint_every':1}})
        summary=read_json(dest/'uncertainty_summary.json');check('batch_RF_'+str(workers),summary['summary']['RF']['count']==2)
        batches.append({k:v for k,v in summary.items() if k!='batch_execution'})
        # Serial first-control reuse has different work counters from process
        # execution. Compare every scientific field, including diagnostics.
        execution_fields={'evaluations','reused_search','cache_source_evaluations'}
        with (dest/'uncertainty.csv').open() as stream:
            batch_rows.append([{k:v for k,v in row.items() if k not in execution_fields} for row in csv.DictReader(stream)])
    check('serial_process_correspondence',batches[0]==batches[1])
    check('serial_process_scientific_CSV_fields',batch_rows[0]==batch_rows[1])
    for name,x in [('minimum',next(x for x in roots if x['group']=='minimum' and x['exponent']==537 and x['strategy']=='RF' and x['bounds']['announcement_upper'] is None)),
                   ('maximum',next(x for x in roots if x['group']=='maximum' and x['j']==2 and x['bounds']['announcement_upper'] is None))]:
        config={'params':x['params'],'bounds':x['bounds'],'rival_delay':x['rival_delay']}
        if name=='maximum':
            # RF fixes rival delay at one; the full RL delay domain contains
            # genuinely unrepresentable roots, independently proved at .5.
            check('unrestricted_RL_root_really_above_max',rational_gradient(ModelParams(**x['params']),'RL',.5,sys.float_info.max)>0)
            invoke('maximum_unrestricted_RL_refusal','optimize',config,2)
            config={**config,'bounds':{**x['bounds'],'delay_lower':0.,'delay_upper':0.}}
        dest=invoke(name,'optimize',config)
        check('CLI_'+name+'_positive',read_json(dest/'comparison.json')['results'][0]['announcement']>0)
    node=next(x for x in nodes if x['scale']==1e8 and x['scouting_points']==65 and x['params']['deployment_cost']==271828180.1249044)
    dest=invoke('node','optimize',{'params':node['params'],'bounds':node['bounds'],'rival_delay':0})
    check('CLI_node_matches_API',read_json(dest/'comparison.json')['results'][3]==optimize(ModelParams(**node['params']),'DL',DecisionBounds(**node['bounds']),0))
    write_json(out/'checks.json',checks);write_json(out/'policy_cases.json',cases);write_json(out/'node_cases.json',node_records);write_json(out/'root_cases.json',root_records);write_json(out/'CLI_processes.json',cli)
    summary={'version':__version__,'all_pass':all(x['pass'] for x in checks),'checks':len(checks),
             'cancellation_comparisons':len(corpus),'ordinary_comparisons':ordinary,
             'evaluated_node_cases':len(nodes),'representable_root_cases':len(roots),
             'retained_true_range_refusals':6,'CLI_processes':len(cli),
             'named_corrected_co_best':report['co_best'],'named_exact_gap':report['entry_payoff_gap'],
             'scope':'Exact original-binary64 rational values and independent 200/400-digit evaluated-node references. Targeted cases; no statistical failure-rate, interval or continuous global-optimality claim.'}
    write_json(out/'v0240_summary.json',summary);record_validation(out,Path(__file__),seed=20261020)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
