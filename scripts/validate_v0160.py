"""Independent installed-wheel acceptance for follow-up audit A05 and A06."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal,localcontext,MAX_EMAX,MIN_EMIN
from functools import lru_cache
from fractions import Fraction
import argparse,json,math,subprocess,sys
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff,compare
from entrysignallab.sampling import wilson_interval
from entrysignallab.solver import _envelope_root_candidates,NumericalError
from entrysignallab.workflow import write_json,record_validation,verify_manifest,current_source_hashes
from validation_portability import frozen_matches, validation_policy_record

PI=Decimal('3.14159265358979323846264338327950288419716939937510582097494459230781640628620899862803482534211706798214808651328230664709384460955058223172535940812848111745028410270193852110555964462294895493038196')
D=Decimal.from_float

def envelope_reference(p,lower):
    """120-digit piecewise integrals and derivative bisection, no production moments."""
    with localcontext() as c:
        c.prec=120;c.Emax=MAX_EMAX;c.Emin=MIN_EMIN
        s,m,H,T,C,k,r,lo=map(D,[p.growth,p.margin_x,p.growth_end,p.horizon,p.deployment_cost,p.learning_rate,p.discount,lower])
        def j0(length):return length if r==0 else (1-(-r*length).exp())/r
        def j1(length):return length*length/2 if r==0 else (1-(1+r*length)*(-r*length).exp())/(r*r)
        derivative=lambda t:-m*s*j0(T-t)+C*(k+r)*(-k*t).exp()
        hi=H
        assert k*(T-H)>1
        attained=False
        if derivative(lo)<=0:t=lo
        elif derivative(hi)>=0:t=hi;attained=True
        else:
            for _ in range(160):
                mid=(lo+hi)/2
                if derivative(mid)>0:lo=mid
                else:hi=mid
            t=(lo+hi)/2
        mass=(-r*t).exp()*j1(H-t)+(H-t)*(-r*H).exp()*j0(T-H)
        value=m*s*mass-C*(-(k+r)*t).exp()
        return {'delay':str(t),'supremum':str(value),'precision':120,'attained':attained}

@lru_cache(None)
def central_normal_reference(confidence):
    # Invert c=sqrt(2/pi)*integral_0^z exp(-x*x/2) dx directly.
    # High-confidence cases use enough alternating terms and precision to
    # retain their small tail; the production inverse routines are not used.
    with localcontext() as context:
        context.prec=400
        c=D(confidence);normalizer=(Decimal(2)/PI).sqrt();z=c/normalizer
        for _ in range(80):
            term=z;integral=term
            for j in range(1,650):
                term*=-z*z/(2*j);part=term/(2*j+1);integral+=part
                if abs(part)<abs(integral)*Decimal('1e-350'):break
            else:raise AssertionError('reference normal integral series did not converge')
            step=(normalizer*integral-c)/(normalizer*(-z*z/2).exp());z-=step
            if abs(step)<=abs(z)*Decimal('1e-180'):return +z
        raise AssertionError('reference central normal inversion did not converge')

def wilson_reference(count,total,confidence):
    with localcontext() as context:
        context.prec=400;context.Emax=MAX_EMAX;context.Emin=MIN_EMIN
        z=central_normal_reference(confidence);n=Decimal(total);k=Decimal(count);z2=z*z
        if count==0:lo,hi=Decimal(0),z2/(n+z2)
        elif count==total:lo,hi=n/(n+z2),Decimal(1)
        else:
            center=(k+z2/2)/(n+z2);half=z*(k*(n-k)/n+z2/4).sqrt()/(n+z2)
            lo,hi=center-half,center+half
        return [max(0.,float(lo)),min(1.,float(hi))]

def ordinary_interval_matches(actual, frozen, reference):
    """Retain exact locked replay; independently check portable endpoints."""
    return (len(actual)==len(frozen)==len(reference)==2
        and frozen_matches(actual,frozen)
        and 0<=actual[0]<=actual[1]<=1
        and all(math.isfinite(a) and math.isfinite(r)
                and (a==0)==(r==0)
                and abs(a-r)<=max(abs(r)*5e-12,8*math.ulp(r))
                for a,r in zip(actual,reference)))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);out=ap.parse_args().out.resolve()
    out.mkdir(parents=True,exist_ok=False);root=Path(__file__).resolve().parents[1]
    checks=[];envelopes=[];intervals=[]
    def check(name,condition,detail=None):checks.append({'name':name,'pass':bool(condition),'detail':detail})
    def rejects(name,operation):
        try:operation()
        except NumericalError as error:check(name,True,str(error))
        else:check(name,False,'Expected controlled NumericalError')
    original=json.loads((root/'tests/data/v0150_followup_observations.json').read_text())
    assert original['version']=='0.15.0' and original['checks']==60
    for row in original['rows']:
        if row['issue']!='A05' or row['kind']!='confirmed_counterexample' or 'params' not in row['detail']:continue
        d=row['detail'];p=ModelParams(**d['params']);b=DecisionBounds(**d['bounds']);r=optimize(p,'RL',b,0.)
        ref=envelope_reference(p,b.delay_lower)
        check('A05_original_status_'+row['name'],r['status']=='no_finite_joint_optimum' and r['payoff'] is None)
        check('A05_original_supremum_'+row['name'],math.isclose(r['supremum'],float(ref['supremum']),rel_tol=1e-10))
        check('A05_original_location_'+row['name'],math.isclose(r['supremum_delay'],float(ref['delay']),rel_tol=1e-10))
        envelopes.append({'label':row['name'],'params':asdict(p),'bounds':asdict(b),'actual':r,'reference':ref})
    for scale in [1e-250,1e-150,1e-50,1e-12,1.,1e12,1e50,1e150,1e250]:
        for lower in [0.,.1]:
            p=ModelParams(growth=.1/scale,margin_x=.25/scale,margin_y=.25/scale,growth_end=.3*scale,
                horizon=scale,learning_rate=10/scale,deployment_cost=.01)
            ref=envelope_reference(p,lower*scale)
            for tolerance in [1e-10,1.]:
                b=DecisionBounds(delay_lower=lower*scale,announcement_upper=None,tolerance=tolerance)
                r=optimize(p,'RL',b,0.);label=str(scale)+'_'+str(lower)+'_'+str(tolerance)
                check('A05_scale_status_'+label,r['status']=='no_finite_joint_optimum')
                check('A05_scale_value_'+label,math.isclose(r['supremum'],float(ref['supremum']),rel_tol=1e-10))
                check('A05_scale_lag_'+label,math.isclose(r['supremum_delay'],float(ref['delay']),rel_tol=1e-10))
                check('A05_finite_witness_'+label,r['supremum']>=payoff(p,'RL',.15*scale,1000/scale))
                envelopes.append({'label':label,'params':asdict(p),'bounds':asdict(b),'actual':r,'reference':ref})
    for scale in [1e-12,1.,1e12]:
        for discount in [.1,1.,10.]:
            p=ModelParams(growth=.1/scale,margin_x=.25/scale,margin_y=.25/scale,growth_end=.3*scale,
                horizon=scale,learning_rate=10/scale,discount=discount/scale,deployment_cost=.01)
            ref=envelope_reference(p,0.);b=DecisionBounds(announcement_upper=None,tolerance=1.);r=optimize(p,'RL',b,0.)
            label=str(scale)+'_'+str(discount)
            check('A05_discounted_status_'+label,r['status']==('attained_joint_optimum' if ref['attained'] else 'no_finite_joint_optimum'))
            check('A05_discounted_value_'+label,math.isclose(r['supremum'],float(ref['supremum']),rel_tol=1e-10))
            check('A05_discounted_lag_'+label,math.isclose(r.get('supremum_delay',r['delay']),float(ref['delay']),rel_tol=1e-10))
            envelopes.append({'label':'discounted_'+label,'params':asdict(p),'bounds':asdict(b),'actual':r,'reference':ref})
    p=ModelParams(growth=1e11,margin_x=2.5e11,margin_y=2.5e11,growth_end=3e-13,horizon=1e-12,learning_rate=1e13,deployment_cost=.01)
    b=DecisionBounds(announcement_upper=None)
    comparison=compare(p,b,0.,tie_tolerance=0.)
    check('A05_original_comparison',not comparison['all_rankable'] and comparison['co_best']==[] and comparison['preferred_with_outside_option']==[])
    config={'params':asdict(p),'bounds':{'announcement_upper':None},'rival_delay':0.,'comparison':{'tie_tolerance':0.}}
    write_json(out/'cli_config.json',config)
    process=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(out/'cli_config.json'),'--out',str(out/'cli')],capture_output=True,text=True)
    (out/'cli_stdout.txt').write_text(process.stdout);(out/'cli_stderr.txt').write_text(process.stderr)
    result=json.loads((out/'cli/comparison.json').read_text()) if process.returncode==0 else {}
    check('A05_real_CLI',process.returncode==0 and result.get('all_rankable') is False and result.get('co_best')==[] and result.get('preferred_with_outside_option')==[])
    check('A05_CLI_integrity',process.returncode==0 and verify_manifest(out/'cli',current_source_hashes())['valid'])
    for label,p,t in [('maturity',ModelParams(deployment_cost=.05,learning_rate=1.),.3),('zero_singleton',ModelParams(),0.),('maturity_singleton',ModelParams(),.3)]:
        b=DecisionBounds(announcement_upper=None) if label=='maturity' else DecisionBounds(delay_lower=t,delay_upper=t,announcement_upper=None)
        r=optimize(p,'RL',b,0.)
        check('A05_true_boundary_'+label,r['payoff'] is not None and r['delay']==t)
    a=1.;b=float(np.nextafter(a,2.));exact=(Fraction(a)+Fraction(b))/2
    rejects('A05_unresolved_float_boundary',lambda:_envelope_root_candidates(lambda t:Fraction(t)-exact,a,b,1.))
    rejects('A05_nonbracket_reject',lambda:_envelope_root_candidates(lambda t:t+1,0.,1.,1.))
    def nonfinite(t):return -1. if t==0 else 1. if t==1 else float('nan')
    rejects('A05_nonfinite_balance_reject',lambda:_envelope_root_candidates(nonfinite,0.,1.,1.))

    confidences=[math.ulp(0.),1e-162,1e-160,1e-50,1e-20,1e-17,1e-16,1e-8,.1,.25,float(np.nextafter(.5,0.)),.5,.95,1-1e-12,float(np.nextafter(1.,0.))]
    cases=[(0,n,c) for n in [1,10,100,10**290,10**320,10**325] for c in confidences]
    cases += [(k,n,c) for n in [100,10**320] for k in [1,n//2,n-1] for c in [1e-16,.25,.95,float(np.nextafter(1.,0.))]]
    # Include every original wrong interval verbatim, alongside broader controls.
    cases += [(r['detail']['count'],r['detail']['total'],r['detail']['confidence']) for r in original['rows']
              if r['issue']=='A06' and r['kind']=='confirmed_counterexample']
    for index,(k,n,c) in enumerate(cases):
        reference=wilson_reference(k,n,c);actual=wilson_interval(k,n,c)
        equivalent=all((a==0)==(r==0) and abs(a-r)<=max(abs(r)*5e-12,8*math.ulp(r)) for a,r in zip(actual,reference))
        check('A06_independent_Wilson_'+str(index),equivalent,{'count':k,'total':n,'confidence':c,'actual':actual,'reference':reference})
        intervals.append({'count':k,'total':n,'confidence':c,'actual':actual,'reference':reference})
    old=json.loads((root/'tests/data/v0150_wilson_ordinary_golden.json').read_text())
    for index,row in enumerate(old):
        actual=wilson_interval(row['count'],row['total'],row['confidence'])
        reference=wilson_reference(row['count'],row['total'],row['confidence'])
        check('A06_unchanged_ordinary_'+str(index),ordinary_interval_matches(actual,row['interval'],reference),
              {'actual':actual,'frozen':row['interval'],'independent_reference':reference})
    write_json(out/'v0160_checks.json',checks);write_json(out/'independent_envelopes.json',envelopes);write_json(out/'independent_wilson.json',intervals)
    summary={'validation_policy':validation_policy_record(),'all_pass':all(c['pass'] for c in checks),'checks':len(checks),'original_A05_API_cases':10,'original_A06_intervals':15,
        'independent_decimal_envelope_cases':len(envelopes),'independent_wilson_cases':len(intervals),
        'unchanged_ordinary_intervals':len(old),'envelope_precision':120,'wilson_arithmetic_precision':400,
        'max_envelope_relative_error':max(abs(row['actual']['supremum']/float(row['reference']['supremum'])-1.) for row in envelopes),
        'max_envelope_location_relative_error':max(abs(row['actual'].get('supremum_delay',row['actual']['delay'])/float(row['reference']['delay'])-1.) for row in envelopes),
        'scope':'Installed current wheel; independent piecewise Decimal envelope integrals and bisection, central-normal integral-series inversion for Wilson intervals, real CLI, unresolved-boundary rejection and independently checked ordinary intervals (exact frozen equality in strict replay). Sampled numerical evidence, not interval/global certification.'}
    write_json(out/'v0160_summary.json',summary);record_validation(out,Path(__file__),seed=20261018)
    print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('v0.16.0 acceptance failed')

if __name__=='__main__':main()
