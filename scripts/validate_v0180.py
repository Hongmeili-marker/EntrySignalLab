"""Independent cost-cancellation and source-bound acceptance of the installed wheel."""
from pathlib import Path
from dataclasses import asdict, replace
from fractions import Fraction as F
from decimal import Decimal as D, localcontext, MAX_EMAX, MIN_EMIN
import argparse, json, math, subprocess, sys
import numpy as np
from entrysignallab import ModelParams, DecisionBounds, payoff, payoff_grid, compare, rescale_experiment, optimize
from entrysignallab.research import default_research_kernel,optimize_research
from entrysignallab.audit import source_audit
from entrysignallab.workflow import write_json, read_json, verify_manifest, current_source_hashes, record_validation

STRATEGIES=['RF','RL','DF','DL']

def rational_reference(p,st,t,d):
    """Original-binary-input rational transcription, independent of model helpers."""
    assert p.discount==0 and (p.learning_rate==0 or p.deployment_cost==0 or st.endswith('F') or t==0)
    s,n,H,T,w,m,c,C,t,d=map(F,(p.growth,p.network,p.growth_end,p.horizon,
        p.quality_ratio,p.margin_x,p.announcement_cost,p.deployment_cost,t,d))
    if st=='RF':a,b=1+n*(s+d)*t,w
    elif st=='DF':a,b=1+n*s*t,w
    elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
    else:a,b=F(1),w*(1+n*s*t)
    following=(H-t)*(2*T-H-t)/2
    leader=t*(2*T-t)/2 if st.endswith('F') else 0
    return m*s*(leader+following*a/(a+b))-c*d*d/2-C

def primitive_reference(p,st,t,d,precision=400,envelope=False):
    """Independent global antiderivatives at events, not production segments/series."""
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,H,T,w,m,r,c,C,k,t,d=map(D.from_float,(p.growth,p.network,p.growth_end,
            p.horizon,p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,
            p.deployment_cost,p.learning_rate,float(t),float(d)))
        def decay(x):return D(0) if x>1000000 else (-x).exp()
        def J(u):
            if r==0:return u,u*u/2
            e=decay(r*u)
            return (1-e)/r,(1-(1+r*u)*e)/(r*r)
        at0,at1=J(t);h0,h1=J(H);T0,T1=J(T)
        follower=h1-at1-t*(h0-at0)+(H-t)*(T0-h0)
        leader=at1+t*(T0-at0) if st.endswith('F') else D(0)
        if st=='RF':a,b=1+n*(s+d)*t,w
        elif st=='DF':a,b=1+n*s*t,w
        elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
        else:a,b=D(1),w*(1+n*s*t)
        revenue=m*s*follower if envelope else m*s*(leader+follower*a/(a+b));ann=c*d*d/2
        entry=D(0) if st.endswith('F') else t
        deploy=C*decay((k+r)*entry)
        return revenue-ann-deploy,revenue,ann,decay((k+r)*entry)

def source_reference(p):
    S,N,H=map(F,(p.growth,p.network,p.growth_end));k=S*N
    P=(1+2*k+k*k*H*(2-H))/(8*S*N*N)
    B=S*H*(2-H)/8
    assert P-B==S*(1/k**2+2/k)/8>0
    return P,B

def close_reference(actual,reference):
    reference=float(reference)
    return ((actual==0)==(reference==0) and (actual<0)==(reference<0)
            and abs(actual-reference)<=2*math.ulp(reference))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];payoffs=[];sources=[];cli=[]
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    def value_case(name,p,st,t,d,ref,exact=False):
        v=payoff(p,st,t,d);g=float(payoff_grid(p,st,[t],[d])[0,0]);expected=float(ref)
        check(name+'_scalar',v==expected if exact else close_reference(v,ref),{'actual':v,'reference':expected})
        check(name+'_grid',g==expected if exact else close_reference(g,ref),{'actual':g,'reference':expected})
        check(name+'_common_value',v==g)
        payoffs.append({'case':name,'strategy':st,'params':asdict(p),'delay':t,'announcement':d,
                        'reference':expected,'scalar':v,'grid':g,'exact_rational':exact})
    bounds=DecisionBounds(delay_lower=0,delay_upper=0,announcement_upper=0)
    frozen=read_json(root/'tests/data/v0170_observations.json')
    check('frozen_observations',len(frozen)==9 and all(x['defect_reproduced'] for x in frozen))
    for item in frozen:
        if item['finding']!='A09':continue
        if 'params' in item:
            p=ModelParams(**item['params']);ref=rational_reference(p,'DL',0,0)
            for st in STRATEGIES:value_case(item['case']+st,p,st,0.,0.,ref,True)
            report=compare(p,bounds,0)
            check(item['case']+'_preference',report['preferred_with_outside_option']==item['expected_preference'])
        else:
            p=ModelParams(**item['original_params'])
            q,b,r=rescale_experiment(p,bounds,0,time_factor=item['time_factor'],consumer_factor=item['consumer_factor'])
            ref=rational_reference(p,'DL',0,0)
            for st in STRATEGIES:
                check(item['case']+st+'_units',rational_reference(q,st,0,0)==ref==F(1,4))
                value_case(item['case']+st,q,st,0.,0.,ref,True)
            check(item['case']+'_preference',compare(q,b,r)['preferred_with_outside_option']==STRATEGIES)
    corpus=read_json(root/'tests/data/v0170_cancellation_corpus.json')
    for i,row in enumerate(corpus):
        p=ModelParams(growth=4*row['scale'],network=0,growth_end=1,horizon=1,margin_x=1,deployment_cost=row['cost'])
        for st in STRATEGIES:value_case('original_corpus_'+str(i)+st,p,st,0.,0.,rational_reference(p,st,0,0),True)
        check('corpus_preference_'+str(i),compare(p,bounds,0)['preferred_with_outside_option']==row['expected_preference'])
    # Nonzero announcement costs and active network effects near break-even.
    rational_cases=0
    for scale in [1e-100,1.,1e8,1e14,1e100]:
        for network in [0.,.7,1e12]:
            for t in [0.,.125]:
                for st in STRATEGIES:
                    d=.2 if st.startswith('R') else 0.
                    p=ModelParams(growth=4.,network=network,margin_x=scale,quality_ratio=1.3,
                                  announcement_cost=.01*scale)
                    gross=rational_reference(p,st,t,d)
                    if gross<=0:continue
                    p=replace(p,deployment_cost=float(gross))
                    value_case('rational_cost_'+str(rational_cases),p,st,t,d,rational_reference(p,st,t,d),True)
                    rational_cases+=1
    # Reference C chosen using global antiderivatives; then original rounded C
    # is independently reevaluated at two higher precisions.
    decimal_cases=0
    for scale in [1e-100,1.,1e14,1e100]:
        for rate in [0.,.05,.5,5.,100.]:
            for learning in [0.,.7]:
                if rate==learning==0:continue
                for st in STRATEGIES:
                    t=.125;d=.2 if st.startswith('R') else 0.
                    p=ModelParams(growth=4,network=.7,quality_ratio=1.3,margin_x=scale,
                                  discount=rate,learning_rate=learning)
                    _,rev,_,decay=primitive_reference(p,st,t,d)
                    p=replace(p,announcement_cost=float(rev/10))
                    _,rev,ann,decay=primitive_reference(p,st,t,d)
                    with localcontext() as ctx:
                        ctx.prec=400;C=float((rev-ann)/decay)
                    p=replace(p,deployment_cost=C)
                    ref=primitive_reference(p,st,t,d,400)[0];ref2=primitive_reference(p,st,t,d,800)[0]
                    check('decimal_oracle_'+str(decimal_cases),float(ref)==float(ref2))
                    value_case('decimal_cost_'+str(decimal_cases),p,st,t,d,ref2)
                    decimal_cases+=1
    tiny_cases=0
    for rate in [1e-20,1e-80,1e-100,1e-200,1e-300,float.fromhex('0x0.0000000000001p-1022')]:
        for H,s in [(1.,4.),(.5,16.)]:
            p=ModelParams(growth=s,network=0,growth_end=H,horizon=H,margin_x=1,discount=rate,deployment_cost=1)
            for st in STRATEGIES:
                ref=primitive_reference(p,st,0,0,1600)[0]
                value_case('tiny_rate_'+str(tiny_cases),p,st,0.,0.,ref)
                tiny_cases+=1
    envelope_cases=0
    for scale in [1.,1e14,1e100]:
        for rate,learning in [(0.,0.),(.5,.7)]:
            p=ModelParams(growth=4,network=.7,margin_x=scale,discount=rate,learning_rate=learning)
            _,rev,ann,decay=primitive_reference(p,'RL',.125,0,envelope=True)
            with localcontext() as ctx:
                ctx.prec=400;C=float(rev/decay)
            p=replace(p,deployment_cost=C);b=DecisionBounds(delay_lower=.125,announcement_upper=None)
            if rate==learning==0:
                H,T,t=map(F,(p.growth_end,p.horizon,.125))
                ref=F(p.margin_x)*F(p.growth)*(H-t)*(2*T-H-t)/2-F(C)
            else:ref=primitive_reference(p,'RL',.125,0,800,envelope=True)[0]
            actual=optimize(p,'RL',b);research=optimize_research(default_research_kernel(),p,'RL',b)
            check('envelope_state_'+str(envelope_cases),actual['attainment']=='not_attained' and actual['payoff'] is None)
            check('envelope_value_'+str(envelope_cases),close_reference(actual['supremum'],ref))
            check('envelope_research_'+str(envelope_cases),research['supremum']==actual['supremum'])
            envelope_cases+=1
    # Source boundary, large-k equal rounding, and intermediate-overflow cases.
    source_params=[ModelParams(**x['params']) for x in frozen if x['finding']=='A10']
    for s in [.1,1e-100,1e-150,1e150]:
        for n in [.85,1e20,1e150,1e300]:
            for h in [.3,1.]:source_params.append(ModelParams(growth=s,network=n,growth_end=h))
    source_params.extend([ModelParams(growth=1e16,network=1e308,growth_end=5e-324),
                          ModelParams(growth=1e-308,network=1e308,growth_end=5e-324)])
    accepted=refused=0
    for i,p in enumerate(source_params):
        P,B=source_reference(p);S,N,H=map(F,(p.growth,p.network,p.growth_end));k=S*N
        rational_values=[(4+k*H*(2-H))/(N*H*(H-2)),1/k,S*(3+k*k*H*(2-H)+4*k)/(2*(1+k)),P,-1/(S*S*N)]
        try:expected=[float(x) for x in rational_values];representable=all(math.isfinite(x) for x in expected)
        except OverflowError:representable=False
        try:a=source_audit(p)
        except ValueError as error:
            check('source_reject_'+str(i),not representable,str(error));refused+=1;continue
        check('source_admitted_'+str(i),representable)
        item=next(x for x in a['checks'] if x['id']=='RL_REVENUE_BOUND')
        check('source_basis_'+str(i),item['pass'] is False and item['decision_basis']=='analytic_positive_excess' and item['numerical_values_are_descriptive'] is True)
        check('source_value_'+str(i),item['observed']==float(P) and item['market_revenue_bound']==float(B))
        check('source_representation_'+str(i),item['observed_representation']==('underflow' if P and float(P)==0 else 'finite') and item['bound_representation']==('underflow' if B and float(B)==0 else 'finite'))
        check('source_ID_inventory_'+str(i),len(a['checks'])==6)
        with localcontext() as ctx:
            ctx.prec=800
            cv=lambda x:D(x.numerator)/D(x.denominator)
            delay=float((cv(4+4*k+k*k*H*(2-H)).sqrt()-2)/cv(k))
        candidates=a['printed_candidates']
        check('source_all_candidates_'+str(i),all(candidates[name]==value for name,value in zip(
            ['announcement_RF','delay_RL','announcement_RL','payoff_RL'],expected[:4]))
            and candidates['delay_DF_DL']==delay and a['checks'][3]['observed']==expected[4])
        sources.append({'case':i,'params':asdict(p),'actual':a,'reference_payoff':float(P),'reference_bound':float(B),'strict_excess_positive':P>B})
        accepted+=1
    # Actual JSON/HTML, serial/process CSV, uncertainty and source diagnostic paths.
    def invoke(name,command,config,extra=None):
        path=out/(name+'_config.json');write_json(path,config);folder=out/name
        args=[sys.executable,'-m','entrysignallab.cli',command,'--config',str(path)]
        args+=extra if command=='evaluate' else ['--out',str(folder)]
        process=subprocess.run(args,text=True,capture_output=True,timeout=180)
        (out/(name+'_stdout.txt')).write_text(process.stdout);(out/(name+'_stderr.txt')).write_text(process.stderr)
        check(name+'_exit',process.returncode==0,process.stderr)
        if process.returncode:raise RuntimeError(process.stderr)
        if command=='evaluate':
            record=json.loads(process.stdout);check(name+'_value',record['payoff_x']==.25)
        else:
            receipt=verify_manifest(folder,current_source_hashes());check(name+'_receipt',receipt['valid'],receipt)
            if command in ['optimize','reproduce']:
                record=read_json(folder/'comparison.json');check(name+'_value',all(x['payoff']==.25 for x in record['results']))
                check(name+'_preference',record['preferred_with_outside_option']==STRATEGIES)
                if command=='reproduce':check(name+'_html','-0.328125' not in (folder/'report.html').read_text())
            elif command=='audit':
                record=read_json(folder/'source_audit.json');item=record['checks'][-1]
                check(name+'_source',item['pass'] is False and item['observed']>0)
            else:
                import csv
                rows=list(csv.DictReader((folder/(command+'.csv')).open()))
                check(name+'_CSV_values',all(float(x['payoff'])==.25 for x in rows))
                if command=='uncertainty':check(name+'_frequency',read_json(folder/'uncertainty_summary.json')['outside_option_summary']['entry_preferred']==4)
        cli.append({'case':name,'command':command,'exit':process.returncode});return folder
    p=ModelParams(growth=4e14,network=0,growth_end=1,horizon=1,margin_x=1,margin_y=1,deployment_cost=1e14-.25)
    config={'params':asdict(p),'bounds':asdict(bounds),'rival_delay':0}
    for command in ['evaluate','optimize','reproduce']:
        invoke('cli_'+command,command,({**config,'bounds':{**config['bounds'],'announcement_upper':2}} if command=='reproduce' else config),['--strategy','DL','--delay','0'] if command=='evaluate' else None)
    for workers in [1,2]:
        invoke('cli_sweep_'+str(workers),'sweep',{**config,'axes':{'network':[0.,1.]},'batch':{'workers':workers}})
    invoke('cli_uncertainty','uncertainty',{**config,'uncertainty':{'samples':4,'ranges':{'network':[0.,1.]}}})
    for i,p in enumerate(source_params[:3]):invoke('cli_source_'+str(i),'audit',{'params':asdict(p)})
    write_json(out/'payoff_checks.json',payoffs);write_json(out/'source_checks.json',sources);write_json(out/'CLI_checks.json',cli)
    relative=[abs(x['scalar']/x['reference']-1) for x in payoffs if x['reference']]
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),
        'frozen_observations':len(frozen),'frozen_cancellation_cases':len(corpus),
        'payoff_cases':len(payoffs),'rational_cost_cases':rational_cases,'decimal_cost_cases':decimal_cases,
        'tiny_rate_payoffs':tiny_cases,'source_cases':len(source_params),'accepted_source_cases':accepted,
        'guarded_envelope_cases':envelope_cases,
        'controlled_source_refusals':refused,'CLI_processes':len(cli),
        'max_payoff_relative_error':max(relative,default=0.),
        'scope':'Exact rational costs and independent global Decimal antiderivatives; original signs/preferences and exact unit transforms. Adaptive numerical guarding is not interval/global certification.'}
    write_json(out/'checks.json',checks);write_json(out/'v0180_summary.json',summary);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('v0.18.0 acceptance failed')
    record_validation(out,Path(__file__),20261019)

if __name__=='__main__':main()
