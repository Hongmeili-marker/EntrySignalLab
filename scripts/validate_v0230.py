"""Independent A17/A18 derivatives, D02 schema and U01 report acceptance."""
from pathlib import Path
from fractions import Fraction as F
from decimal import Decimal as D,localcontext,MAX_EMAX,MIN_EMIN
from dataclasses import asdict
from math import isclose,log
import argparse,ast,csv,json,subprocess,sys
from entrysignallab import ModelParams,DecisionBounds,optimize
from entrysignallab.model import announcement_gradient
from entrysignallab.solver import announcement_stationarity,NumericalError
from entrysignallab.workflow import write_json,read_json,record_validation,verify_manifest,current_source_hashes,sha256


def rational_derivative(p,st,tau,delta):
    """Differentiate the source event integral without production helpers."""
    assert p.discount==0
    s,n,H,T,w,m,c,t,d=map(F,(p.growth,p.network,p.growth_end,p.horizon,
        p.quality_ratio,p.margin_x,p.announcement_cost,tau,delta))
    mass=(H-t)*(2*T-H-t)/2
    a=1+n*((s+d) if st=='RF' else d)*t
    b=w if st=='RF' else w*(1+n*s*t)
    benefit=m*s*mass*n*t*b/(a+b)**2;cost=c*d
    return benefit-cost,max(benefit,cost)


def decimal_derivative(p,st,tau,delta,digits):
    """Unrestricted event antiderivatives at independently selected precision."""
    with localcontext() as ctx:
        ctx.prec=digits;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,H,T,w,m,r,c,t,d=map(D.from_float,(p.growth,p.network,p.growth_end,p.horizon,
            p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,tau,delta))
        def moments(L):
            if not r:return L,L*L/2
            e=(-r*L).exp()
            return (1-e)/r,(1-(1+r*L)*e)/(r*r)
        mass=(-r*t).exp()*moments(H-t)[1]+(H-t)*(-r*H).exp()*moments(T-H)[0]
        a=1+n*((s+d) if st=='RF' else d)*t
        b=w if st=='RF' else w*(1+n*s*t)
        benefit=m*s*mass*n*t*b/(a+b)**2;cost=c*d
        return benefit-cost,max(benefit,cost)


def independent_payoff(p,row,tau,digits):
    """Follower event integral with zero discount and an independent decay."""
    assert p.discount==0
    with localcontext() as ctx:
        ctx.prec=digits
        s,n,H,T,w,m,c,C,k,t,d=map(D.from_float,(p.growth,p.network,p.growth_end,p.horizon,
            p.quality_ratio,p.margin_x,p.announcement_cost,p.deployment_cost,p.learning_rate,tau,row['announcement']))
        a=1+n*d*t if row['strategy']=='RL' else D(1);b=w*(1+n*s*t)
        return m*s*(H-t)*(2*T-H-t)*a/(2*(a+b))-c*d*d/2-C*(-k*t).exp()


def coarse_case():
    return ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12),DecisionBounds(scouting_points=3,tolerance=1,payoff_atol=0,payoff_rtol=0)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];cases=[];cli=[]
    def check(name,passed,detail=None):
        checks.append({'name':name,'pass':bool(passed),'detail':detail})
        if not passed:raise AssertionError((name,detail))
    for name,h in read_json(root/'tests/data/v0220_corpus_identity.json').items():
        check('frozen_'+name,sha256(root/'tests/data'/name)==h)
    frozen=read_json(root/'tests/data/v0220_A17_stationarity.json');repaired=0
    for i,old in enumerate(frozen):
        p=ModelParams(**old['params']);st=old['strategy'];b=DecisionBounds(**old['bounds']);r=optimize(p,st,b,1)
        g,scale=rational_derivative(p,st,r['delay'],r['announcement']);diagnostic=r['announcement_stationarity_diagnostic']
        check('rational_control_'+str(i),(r['delay'],r['announcement'],r['payoff'])==(old['result']['delay'],old['result']['announcement'],old['result']['payoff']))
        check('rational_raw_'+str(i),r['announcement_stationarity_residual']==float(abs(g)))
        check('rational_scalar_'+str(i),announcement_gradient(p,st,r['delay'],r['announcement'])==float(g))
        check('rational_scaled_'+str(i),r['announcement_stationarity_scaled_residual']==float(abs(g)/scale))
        check('rational_sign_'+str(i),diagnostic['gradient_sign']==(g>0)-(g<0))
        check('rational_basis_'+str(i),diagnostic['decision_basis']=='exact_original_input_announcement_difference')
        check('rational_log_'+str(i),r['announcement_stationarity_log_residual'] is not None)
        if old['reported_false_zero']:check('false_zero_repaired_'+str(i),r['announcement_stationarity_residual']>0);repaired+=1
        cases.append({'group':'rational','params':asdict(p),'result':r,'reference_numerator':str(g.numerator),'reference_denominator':str(g.denominator)})
    check('ten_original_false_zero_diagnostics',repaired==10)
    max_raw_error=max_scaled_error=max_log_error=0.;decimal_cases=0
    for st in ['RF','RL']:
        for discount in [1e-12,.4,100.]:
            for scale in [1e-300,1.,1e100,1e300]:
                p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=scale,
                    announcement_cost=scale,discount=discount)
                r=optimize(p,st,DecisionBounds(delay_lower=1,delay_upper=1,announcement_upper=2),1)
                refs=[]
                for digits in [200,400]:
                    with localcontext() as ctx:
                        ctx.prec=digits
                        g,largest=decimal_derivative(p,st,r['delay'],r['announcement'],digits)
                        refs.append({'value':float(g),'sign':(g>0)-(g<0),'scaled':float(abs(g)/largest),'log_abs':float(abs(g).ln())})
                name='decimal_'+str(decimal_cases);decimal_cases+=1
                check(name+'_reference_stability',refs[0]==refs[1])
                ref=refs[-1];d=r['announcement_stationarity_diagnostic'];actual=r['announcement_stationarity_residual'];expected=abs(ref['value'])
                check(name+'_sign',d['gradient_sign']==ref['sign'])
                check(name+'_raw',isclose(actual,expected,rel_tol=1e-12,abs_tol=0))
                check(name+'_scalar',isclose(announcement_gradient(p,st,1,r['announcement']),ref['value'],rel_tol=1e-12,abs_tol=0))
                check(name+'_scaled',isclose(d['scaled'],ref['scaled'],rel_tol=1e-12,abs_tol=0))
                check(name+'_log',abs(d['log']-ref['log_abs'])<1e-10)
                check(name+'_basis',d['decision_basis']=='adaptive_original_input_announcement_difference' and d['precision_digits']>=160)
                check(name+'_representation',d['representation']==('underflow' if expected==0 and ref['sign'] else 'finite'))
                if expected:max_raw_error=max(max_raw_error,abs(actual-expected)/expected)
                max_scaled_error=max(max_scaled_error,abs(d['scaled']-ref['scaled'])/ref['scaled'])
                max_log_error=max(max_log_error,abs(d['log']-ref['log_abs']))
                cases.append({'group':'decimal','params':asdict(p),'result':r,'independent_200_400_digit_references':refs})
    true_zero=[]
    p=ModelParams(growth=1,network=1,growth_end=2,horizon=2,margin_x=1,announcement_cost=.03125)
    g,_=rational_derivative(p,'RF',1,1)
    d=announcement_stationarity(p,'RF',1,1,'interior');check('exact_zero_reference',g==0);check('exact_zero_diagnostic',d['raw']==0)
    true_zero.append(d)
    for name,p,st,t,d,active in [
        ('fixed_zero',ModelParams(),'RF',.15,0,'fixed'),('silent',ModelParams(),'DF',.15,0,'not_applicable'),
        ('zero_growth',ModelParams(growth=0,announcement_cost=1),'RF',.15,0,'lower'),
        ('free_upper',ModelParams(),'RF',.15,2,'upper')]:
        r=announcement_stationarity(p,st,t,d,active);check(name+'_zero',r['raw']==r['scaled']==0 and r['log'] is None);true_zero.append(r)
    write_json(out/'derivative_cases.json',cases);write_json(out/'true_zero_controls.json',true_zero)
    effects=[];roots=[];controls=[]
    for i,old in enumerate(read_json(root/'tests/data/v0220_A18_effect.json')):
        p=ModelParams(**old['params']);b=DecisionBounds(**old['bounds']);r=optimize(p,old['result']['strategy'],b,2)
        # Analytic reference: a positive response integral and share derivative,
        # zero intensity cost and a finite cap imply a strictly increasing profile.
        check('positive_effect_domain_'+str(i),p.growth>0 and p.network>0 and p.margin_x>0 and 0<2<p.growth_end and p.announcement_cost==0)
        check('positive_effect_cap_'+str(i),r['announcement']==b.announcement_upper)
        check('positive_effect_unique_'+str(i),r['announcement_nonunique'] is False)
        check('positive_effect_projection_'+str(i),r['announcement_stationarity_residual']==0 and r['announcement_stationarity_diagnostic']['decision_basis']=='analytic_cost_free_upper_projection')
        effects.append({'params':asdict(p),'result':r,'reference':'strict positive-effect monotonicity'})
    for i,old in enumerate(read_json(root/'tests/data/v0220_A18_roots.json')):
        p=ModelParams(**old['params']);error=None
        try:optimize(p,old['result']['strategy'],DecisionBounds(**old['bounds']),2)
        except NumericalError as e:error=str(e)
        # The independent frozen argument brackets the strictly concave root
        # between zero and min_subnormal, since benefit <= exp(-2*r).
        check('positive_root_below_range_'+str(i),2*F(p.discount)>1000 and error is not None)
        roots.append({'params':asdict(p),'controlled_refusal':error,'reference':old['reference_basis']})
    for i,old in enumerate(read_json(root/'tests/data/v0220_A18_controls.json')):
        oldr=old['result'];st=oldr['strategy'];mature='maturity' in old['case'];fixed='fixed_zero' in old['case']
        discount=float(old['case'].rsplit('_',1)[-1]) if not mature and not fixed else 0.
        p=ModelParams(growth=1,network=1,growth_end=3,horizon=3,margin_x=1,discount=discount)
        t=3 if mature else 2;b=DecisionBounds(delay_lower=t,delay_upper=t,announcement_upper=0 if fixed else 2)
        r=optimize(p,st,b,t)
        check('ordinary_effect_control_'+str(i),(r['announcement'],r['announcement_nonunique'])==(oldr['announcement'],oldr['announcement_nonunique']))
        controls.append(r)
    write_json(out/'effect_cases.json',effects);write_json(out/'positive_root_refusals.json',roots);write_json(out/'effect_controls.json',controls)
    p,b=coarse_case();legacy=[]
    for st in ['RL','DL']:
        r=optimize(p,st,b,0);a=r['local_improvement_residual_assessment'];gains=[]
        for digits in [200,400]:
            with localcontext() as ctx:
                ctx.prec=digits
                gains.append(float(independent_payoff(p,r,r['delay']+3e-6,digits)-independent_payoff(p,r,r['delay'],digits)))
        check('legacy_'+st+'_reference',gains[0]==gains[1] and gains[-1]>0)
        check('legacy_'+st+'_null',r['local_improvement_residual'] is None)
        check('legacy_'+st+'_assessment',a['status']=='not_assessed' and not a['final_control_neighborhood_assessed'] and a['deprecated'])
        check('legacy_'+st+'_failure_preserved',r['local_quality_passed'] is False and a['last_probe_quality_status']=='fail')
        legacy.append({'result':r,'independent_next_fixed_control_gains':gains})
    flat=optimize(ModelParams(growth=0),'DL');check('legacy_analytic_zero',flat['local_improvement_residual']==0 and flat['local_improvement_residual_assessment']['status']=='analytic_zero')
    fixed=optimize(ModelParams(),'RF');check('legacy_fixed_not_applicable',fixed['local_improvement_residual'] is None and fixed['local_improvement_residual_assessment']['status']=='not_applicable')
    narrow=optimize(p,'DL',DecisionBounds(delay_lower=.1,delay_upper=.10000000000001,scouting_points=3,tolerance=1),0)
    check('legacy_collapsed_probe_not_assessed',narrow['local_improvement_residual'] is None
          and not narrow['local_improvement_residual_assessment']['final_control_neighborhood_assessed'])
    write_json(out/'legacy_schema.json',legacy)
    def invoke(name,command,config,expected=0):
        path=out/(name+'_config.json');write_json(path,config);folder=out/name
        r=subprocess.run([sys.executable,'-m','entrysignallab.cli',command,'--config',str(path),'--out',str(folder)],capture_output=True,text=True)
        (out/(name+'_stdout.log')).write_text(r.stdout);(out/(name+'_stderr.log')).write_text(r.stderr)
        check(name+'_exit',r.returncode==expected,r.stderr)
        check(name+'_no_traceback','Traceback' not in r.stderr)
        if expected==0:check(name+'_manifest',verify_manifest(folder,current_source_hashes())['valid'])
        else:check(name+'_no_success_directory',not folder.exists())
        cli.append({'name':name,'command':command,'returncode':r.returncode});return folder
    warning={'params':asdict(p),'bounds':asdict(b),'rival_delay':0,'stability':{'factors':[1,2,4]}}
    folder=invoke('html_warning','reproduce',warning);html=(folder/'report.html').read_text()
    check('html_local_failure','id="numerical-quality" data-status="fail"' in html)
    check('html_mesh_failure','id="mesh-stability" data-status="fail"' in html)
    check('html_separate_ranking','Payoff agreement: unstable.' in html and 'Ranking agreement: stable.' in html)
    check('html_links','href="comparison.json"' in html and 'href="stability.json"' in html)
    rows=list(csv.DictReader((folder/'optima.csv').open()))
    check('csv_legacy_null',all(row['local_improvement_residual']=='' for row in rows))
    check('csv_assessment_preserved',all(ast.literal_eval(row['local_improvement_residual_assessment'])['status']=='not_assessed' for row in rows if row['strategy'] in ('RL','DL')))
    passed={'params':{},'bounds':{'delay_lower':.1,'delay_upper':.1,'announcement_upper':0},'rival_delay':0,'stability':{'factors':[1,2]}}
    folder=invoke('html_pass','reproduce',passed);html=(folder/'report.html').read_text()
    check('html_pass_states','id="numerical-quality" data-status="pass"' in html and 'id="mesh-stability" data-status="pass"' in html)
    unassessed={'params':{},'bounds':{'announcement_upper':None},'stability':{'factors':[1,2]}}
    folder=invoke('html_unassessed','reproduce',unassessed);html=(folder/'report.html').read_text()
    check('html_unassessed_states','id="numerical-quality" data-status="not_assessed"' in html and 'id="mesh-stability" data-status="not_assessed"' in html)
    disabled={k:v for k,v in passed.items() if k!='stability'}
    folder=invoke('html_disabled','reproduce',disabled);check('html_disabled_state','id="mesh-stability" data-status="not_checked"' in (folder/'report.html').read_text())
    named=frozen[2];folder=invoke('named_gradient','optimize',{'params':named['params'],'bounds':named['bounds'],'rival_delay':1})
    r=read_json(folder/'comparison.json')['results'][0];check('cli_named_positive_residual',r['announcement_stationarity_residual']>0)
    extreme={'params':{'growth':1,'network':1,'growth_end':3,'horizon':3,'margin_x':1,'discount':1e308,'announcement_cost':1},'bounds':{'delay_lower':2,'delay_upper':2,'announcement_upper':2},'rival_delay':2}
    invoke('positive_root_refused','optimize',extreme,2)
    invoke('extreme_comparison_refused','optimize',{**extreme,'params':{**extreme['params'],'announcement_cost':0}},2)
    batches=[]
    for workers in [1,2]:
        config={'params':asdict(p),'bounds':asdict(b),'rival_delay':0,'uncertainty':{'ranges':{'growth':[.1,.1]},'samples':2},'batch':{'workers':workers,'checkpoint_every':1}}
        folder=invoke('batch_'+str(workers),'uncertainty',config)
        records=list(csv.DictReader((folder/'uncertainty.csv').open()))
        columns=['case_index','strategy','delay','announcement','payoff','local_improvement_residual','local_improvement_residual_assessment','announcement_stationarity_diagnostic']
        batches.append([{k:row[k] for k in columns} for row in records])
    check('serial_parallel_new_fields_correspond',batches[0]==batches[1])
    config={**extreme,'on_error':'record','uncertainty':{'ranges':{'discount':[1e308,1e308]},'samples':1}}
    folder=invoke('root_record_mode','uncertainty',config);q=read_json(folder/'uncertainty_summary.json')
    check('range_error_recorded_as_numerical',q['run_status']=='all_failed' and q['failed_samples']==1 and q['summary']['numerical_error']['count']==1)
    api=(root/'docs/api.md').read_text()
    for word in ['local_improvement_residual_assessment','announcement_stationarity_diagnostic','not_checked','assessed_zero']:
        check('documented_'+word,word in api)
    summary={'version':'0.23.0','all_pass':all(x['pass'] for x in checks),'checks':len(checks),
        'frozen_rational_derivative_cases':len(frozen),'false_zero_diagnostics_repaired':repaired,
        'unchanged_positive_cost_controls':len(frozen),'discounted_derivative_cases':decimal_cases,
        'discounted_reference_evaluations':2*decimal_cases,'true_zero_controls':len(true_zero),
        'positive_effect_cap_cases':len(effects),'positive_root_refusals':len(roots),'effect_controls':len(controls),
        'legacy_failed_probe_cases':len(legacy),'independent_legacy_control_evaluations':8,
        'CLI_processes':len(cli),'HTML_states':['pass','fail','not_assessed','not_checked'],
        'max_discounted_raw_relative_error':max_raw_error,'max_discounted_scaled_relative_error':max_scaled_error,'max_discounted_log_error':max_log_error,
        'scope':'Original-input rational derivatives, independent 200/400-digit event integrals, analytic positive-effect and below-range-root proofs, installed-wheel CLI, CSV and local report states. No global, interval, empirical or external-CI certificate.'}
    write_json(out/'v0230_summary.json',summary);write_json(out/'checks.json',checks);write_json(out/'cli_runs.json',cli)
    record_validation(out,Path(__file__),seed=20261020);print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
