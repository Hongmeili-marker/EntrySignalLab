"""Independent numerical and behavioral acceptance for v0.14.0 audit repairs."""
from pathlib import Path
from dataclasses import replace,asdict
from decimal import Decimal,localcontext
from tempfile import TemporaryDirectory
import argparse,json,math,subprocess,sys
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,payoff,rescale_experiment
from entrysignallab.research import default_research_kernel,optimize_research
from entrysignallab.sampling import indexed_rng,SamplingPlan,SAMPLER_VERSION
from entrysignallab.workflow import record_validation

def D(x):return Decimal.from_float(float(x))

def envelope_decimal(p,t):
    H,T,r,k,m,s,c=map(D,[p.growth_end,p.horizon,p.discount,p.learning_rate,p.margin_x,p.growth,p.deployment_cost])
    if r==0:mass=(H-t)**2/2+(H-t)*(T-H)
    else:mass=((-r*t).exp()-(-r*H).exp()*(1+r*(H-t)))/(r*r)+(H-t)*((-r*H).exp()-(-r*T).exp())/r
    return m*s*mass-c*(-(k+r)*t).exp()

def independent_envelope(p):
    """120-digit direct formula, fixed mesh root isolation and bisection.

    This reference is restricted to the twelve moderate parameter cases below.
    It does not use the production log-ratio split or component comparison.
    """
    with localcontext() as ctx:
        ctx.prec=120
        H,T,r,k,m,s,c=map(D,[p.growth_end,p.horizon,p.discount,p.learning_rate,p.margin_x,p.growth,p.deployment_cost])
        def derivative(t):
            integral=T-t if r==0 else ((-r*t).exp()-(-r*T).exp())/r
            return -m*s*integral+(k+r)*c*(-(k+r)*t).exp()
        nodes=[H*i/128 for i in range(129)];points=[Decimal(0),H]
        for a,b in zip(nodes,nodes[1:]):
            fa,fb=derivative(a),derivative(b)
            if fa==0:points.append(a)
            if fb==0:points.append(b)
            if fa*fb<0:
                for _ in range(160):
                    mid=(a+b)/2;fm=derivative(mid)
                    if fa*fm<=0:b=mid
                    else:a=mid;fa=fm
                points.append((a+b)/2)
        best=max(points,key=lambda t:envelope_decimal(p,t))
        return best,envelope_decimal(p,best),best==H

def payoff_decimal(p,st,t,d):
    """Direct discounted stock integrals at 120 digits, independent of logs."""
    with localcontext() as ctx:
        ctx.prec=120
        s,phi,H,T,w,m,cA,cD,k,r=map(D,[p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.announcement_cost,p.deployment_cost,p.learning_rate,p.discount])
        t,d=D(t),D(d)
        if st.endswith('F'):x=1+phi*s*t+(phi*d*t if st=='RF' else 0);y=w
        else:x=1+(phi*d*t if st=='RL' else 0);y=w*(1+phi*s*t)
        if r==0:post=(H-t)**2/2+(H-t)*(T-H);lead=t*(T-t/2)
        else:
            j0=lambda a,b:((-r*a).exp()-(-r*b).exp())/r
            j1=lambda a,b:((1+r*a)*(-r*a).exp()-(1+r*b)*(-r*b).exp())/(r*r)
            post=j1(t,H)-t*j0(t,H)+(H-t)*j0(H,T);lead=j1(Decimal(0),t)+t*j0(t,T)
        entry=Decimal(0) if st.endswith('F') else t
        return m*s*((lead if st.endswith('F') else 0)+post*x/(x+y))-cA*d*d/2-cD*(-(k+r)*entry).exp()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    out=parser.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    checks=[];refs=[];envelope_errors=[];unit_errors=[]
    def check(name,condition,detail=None):
        checks.append({'name':name,'pass':bool(condition),'detail':detail})
        if not condition:raise AssertionError(name)
    def rejects(name,callback):
        try:callback()
        except ValueError as error:check(name,True,str(error))
        else:check(name,False)
    for margin in [1e-18,1e-20,1e-24]:
        for cost in [1.,2.,1e8,1e300]:
            for lo in [0.,.05]:
                p=ModelParams(margin_x=margin,deployment_cost=cost);b=DecisionBounds(delay_lower=lo,announcement_upper=None)
                r=optimize(p,'RL',b,0)
                with localcontext() as ctx:
                    ctx.prec=400
                    gap=D(margin)*D(p.growth)*((D(p.growth_end)-D(lo))**2/2+(D(p.growth_end)-D(lo))*(D(p.horizon)-D(p.growth_end)))
                    assert gap>0
                check(f'A01_constant_cost_{margin}_{cost}_{lo}',r['status']=='no_finite_joint_optimum' and r['supremum_delay']==lo and all(r[k] is None for k in ['payoff','delay','announcement']),{'positive_envelope_gap':str(gap),'payoff':r['payoff']})
    for discount in [0.,.4]:
        for learning in [0.,1.,12.]:
            for cost in [.01,.05]:
                p=ModelParams(discount=discount,learning_rate=learning,deployment_cost=cost)
                location,value,attained=independent_envelope(p)
                r=optimize(p,'RL',DecisionBounds(announcement_upper=None),0)
                actual=r['supremum'];reference=float(value);error=abs(actual-reference)/max(abs(reference),sys.float_info.min)
                envelope_errors.append(error)
                check(f'A01_decimal_envelope_{discount}_{learning}_{cost}',(r['status']=='attained_joint_optimum')==attained and error<1e-10,{'reference_value':str(value),'reference_location':str(location),'attained':attained,'relative_error':error})
                refs.append({'kind':'envelope','params':asdict(p),'reference_value':str(value),'reference_location':str(location),'precision':120})
    for direction in [0.,math.inf]:
        with localcontext() as ctx:
            ctx.prec=120
            a=1.;b=math.nextafter(a,2);p=ModelParams(growth_end=2,horizon=3,discount=.4,learning_rate=1)
            difference=envelope_decimal(p,D(a))-envelope_decimal(p,D(b))
            rate=D(p.learning_rate)+D(p.discount)
            coefficient=(-rate*D(a)).exp()-(-rate*D(b)).exp()
            c=math.nextafter(float(difference/coefficient),direction)
            p=replace(p,deployment_cost=c)
            left,right=envelope_decimal(p,D(a)),envelope_decimal(p,D(b));expected=a if left>right else b
        r=optimize(p,'RL',DecisionBounds(delay_lower=a,delay_upper=b,announcement_upper=None))
        check('A01_near_equal_component_order_'+str(direction),r['supremum_delay']==expected,{'expected_lag':expected,'actual_lag':r['supremum_delay'],'decimal_endpoint_gap':str(left-right)})
    fixture=out/'constant_cost_cli.json';fixture.write_text(json.dumps({'params':{'margin_x':1e-20,'deployment_cost':1},'bounds':{'announcement_upper':None},'rival_delay':0}))
    answer=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(fixture),'--out',str(out/'constant_cost_cli')],capture_output=True,text=True)
    (out/'cli_stdout.txt').write_text(answer.stdout);(out/'cli_stderr.txt').write_text(answer.stderr)
    r=json.loads((out/'constant_cost_cli/comparison.json').read_text()) if answer.returncode==0 else {}
    check('A01_actual_CLI_unrankable',answer.returncode==0 and r.get('all_rankable') is False and r['co_best']==r['preferred_with_outside_option']==[])

    minimum=float.fromhex('0x0.0000000000001p-1022');p=ModelParams(margin_x=minimum,deployment_cost=minimum)
    for label,b in [('null',DecisionBounds(delay_upper=.2,announcement_upper=None)),('finite',DecisionBounds(delay_lower=p.growth_end,delay_upper=p.growth_end,announcement_upper=None))]:
        original=optimize(p,'RL',b)
        for name,value in [('zero',0.),('sign',minimum)]:
            result={**original,'supremum':value};kernel=replace(default_research_kernel(),conditional_solver=lambda *a,r=result:r)
            rejects('A02_reject_'+label+'_'+name,lambda k=kernel,b=b:optimize_research(k,p,'RL',b))
        check('A02_correct_'+label,optimize_research(default_research_kernel(),p,'RL',b)['supremum']==-minimum)
    p=ModelParams();b=DecisionBounds(delay_lower=p.growth_end,announcement_upper=None);result=optimize(p,'RL',b);result['supremum']=-0.
    kernel=replace(default_research_kernel(),conditional_solver=lambda *a:result)
    check('A02_signed_zero',optimize_research(kernel,p,'RL',b)['supremum']==0.)

    tiny=ModelParams(growth=1e307,margin_x=1e307,margin_y=1e307,growth_end=minimum,horizon=2*minimum)
    for a in [.6,.75]:rejects('A03_reject_loss_'+str(a),lambda a=a:rescale_experiment(tiny,DecisionBounds(),0,time_factor=a))
    q,b,rival=rescale_experiment(tiny,DecisionBounds(),0,time_factor=2)
    for st in ['RF','RL','DF','DL']:
        ref=payoff_decimal(tiny,st,0,0);other=payoff_decimal(q,st,0,0)
        error=abs(payoff(q,st,0)/payoff(tiny,st,0)-1);unit_errors.append(error)
        check('A03_extreme_exact_'+st,error<1e-12 and abs(float(other/ref)-1)<1e-12,{'relative_payoff_change':error,'decimal_original':str(ref),'decimal_scaled':str(other)})
    p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12,discount=.4)
    for a,bfactor in [(2.,1.),(12.,1000.),(.5,2.)]:
        q,b,rival=rescale_experiment(p,DecisionBounds(),.15,a,bfactor)
        for st in ['RF','RL','DF','DL']:
            ann=.2 if st.startswith('R') else 0.;lag=.15*a;delta=ann*bfactor/a
            ref=payoff_decimal(p,st,.15,ann);scaled_ref=payoff_decimal(q,st,lag,delta)
            actual=payoff(q,st,lag,delta);error=abs(actual/float(ref)-1);unit_errors.append(error)
            check(f'A03_normal_{a}_{bfactor}_{st}',error<1e-12 and abs(float(scaled_ref/ref)-1)<1e-12,{'relative_error':error,'reference_payoff':str(ref),'scaled_reference':str(scaled_ref)})
            refs.append({'kind':'unit_payoff','strategy':st,'time_factor':a,'consumer_factor':bfactor,'reference_payoff':str(ref),'scaled_reference':str(scaled_ref),'precision':120})
    p=ModelParams(growth_end=1,horizon=math.nextafter(1,2))
    rejects('A03_maturity_tail_separation',lambda:rescale_experiment(p,DecisionBounds(announcement_upper=None,tolerance=1),.15,time_factor=1e-308))
    p=ModelParams(growth_end=1,horizon=1)
    rejects('A03_rival_separation',lambda:rescale_experiment(p,DecisionBounds(announcement_upper=None,tolerance=1),math.nextafter(1,0),time_factor=1e-308))
    bounds=DecisionBounds(delay_lower=.1,delay_upper=math.nextafter(.1,1),announcement_upper=None,tolerance=1)
    rejects('A03_delay_interval',lambda:rescale_experiment(p,bounds,.15,time_factor=1e-307))

    root=Path(__file__).resolve().parents[1];golden=json.loads((root/'tests/data/v0140_stream_golden.json').read_text())
    for i,row in enumerate(golden['rows']):
        actual=indexed_rng(row['seed'],row['index'],row['stream'],row['attempt']).bit_generator.random_raw(8).tolist()
        check('A04_frozen_stream_'+str(i),actual==row['raw'])
    for i,value in enumerate([2**32,12884901890,2**100,np.uint64(2**32)]):
        rejects('A04_large_index_'+str(i),lambda value=value:indexed_rng(104,value,'parameter:network'))
        rejects('A04_large_attempt_'+str(i),lambda value=value:indexed_rng(104,0,'parameter:network',value))
    plan=SamplingPlan(ModelParams(),{'growth':[.08,.12],'network':[.2,1.]},1)
    rejects('A04_plan_large_index',lambda:plan.draw(12884901890))
    rejects('A04_plan_large_attempt',lambda:plan.draw(0,2**32))
    check('A04_domain_recorded',plan.metadata()['sample_index_domain']==plan.metadata()['draw_attempt_domain']==[0,2**32-1])
    check('A04_algorithm_version_unchanged',SAMPLER_VERSION==golden['sampler_version']=='indexed-pcg64-v2')
    summary={'checks':len(checks),'all_pass':all(c['pass'] for c in checks),
             'constant_cost_envelope_cases':24,'independent_decimal_envelopes':12,'near_equal_component_cases':2,
             'independent_unit_payoffs':16,'decimal_precision':120,'unchanged_v2_streams':len(golden['rows']),
             'max_envelope_relative_error':max(envelope_errors),'max_unit_relative_error':max(unit_errors),
             'scope':'Installed-wheel acceptance for component envelope ordering, default metadata zero/sign protection, controlled unit-conversion precision and fixed-word index domains. Independent Decimal formulas cover sampled moderate envelopes and unit payoffs; no interval or global certification. Existing v2 raw streams are compared with frozen v0.14.0 bytes.'}
    (out/'v0150_checks.json').write_text(json.dumps(checks,indent=2,allow_nan=False)+'\n')
    (out/'v0150_references.json').write_text(json.dumps(refs,indent=2)+'\n')
    (out/'v0150_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    record_validation(out,Path(__file__),20261018)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
