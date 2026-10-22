"""Independent edge optima, large unit scales and validation-receipt regressions."""
from pathlib import Path
from dataclasses import asdict
from math import exp
import argparse,json,csv,tempfile
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff,rescale_experiment
from entrysignallab.workflow import write_json,record_validation,verify_validation,read_json

ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
out=Path(args.out)
if out.exists() and any(out.iterdir()):raise SystemExit('Choose a fresh output directory')
out.mkdir(parents=True,exist_ok=True)
rows=[]
# With network=0 and c_A=0, RF/RL intensity is irrelevant. For DL/RL:
# V(t)=A (H-t)(2T-H-t)/2-c_D exp(-k t), A=m_x s/(1+w).
# Its derivative has a unique zero here because k > 1/(T-H).
for case in range(24):
    H,T=1.,2.;s=.2+.03*case;w=.5+.1*(case%5);margin=.25+.02*(case%7)
    A=margin*s/(1+w)
    k=[100.,1000.,10000.][case%3] if case<12 else 3.+case%7
    target=[1e-5,1e-4,1e-3,2e-3][case%4] if case<12 else 1.-[1e-5,1e-4,1e-3,2e-3][case%4]
    c=A*(T-target)*exp(k*target)/k
    p=ModelParams(growth=s,network=0,growth_end=H,horizon=T,quality_ratio=w,
        margin_x=margin,deployment_cost=c,learning_rate=k)
    lo,hi=0.,H
    for _ in range(100):
        t=(lo+hi)/2
        if k*c*exp(-k*t)>A*(T-t):lo=t
        else:hi=t
    ref_t=(lo+hi)/2;ref=A*(H-ref_t)*(2*T-H-ref_t)/2-c*exp(-k*ref_t)
    for st in ['RL','DL']:
        for factor in [1e-120,1.,1e120]:
            q,b,r=rescale_experiment(p,DecisionBounds(),.15,factor,1)
            ans=optimize(q,st,b,r)
            error=abs(ans['payoff']-ref)
            rows.append({'case':case,'strategy':st,'time_factor':factor,'edge':'lower' if case<12 else 'upper',
                'reference_delay':ref_t,'normalized_actual_delay':ans['delay']/factor,'reference_payoff':ref,
                'actual_payoff':ans['payoff'],'absolute_error':error,'pass':error<1e-10,
                'params':json.dumps(asdict(p),sort_keys=True)})
with (out/'edge_followers.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

nodes,weights=np.polynomial.legendre.leggauss(64);units=[]
def reference(p,st,tau,delta):
    # Separate stock transcription and quadrature in unscaled physical units.
    k=p.network*p.growth*tau;b=p.network*delta*tau
    x,y=(1+k+(b if st=='RF' else 0),p.quality_ratio) if st.endswith('F') else (1+(b if st=='RL' else 0),p.quality_ratio*(1+k))
    share=x/(x+y);total=0.
    for a,c in zip([0.,tau,p.growth_end],[tau,p.growth_end,p.horizon]):
        time=a+(c-a)*(nodes+1)/2;u=np.minimum(time,p.growth_end)
        stock=p.growth*(np.minimum(u,tau)+np.maximum(u-tau,0)*share) if st.endswith('F') else p.growth*np.maximum(u-tau,0)*share
        total+=(c-a)/2*np.sum(weights*stock*np.exp(-p.discount*time))
    entry=0. if st.endswith('F') else tau
    return p.margin_x*total-p.deployment_cost*exp(-(p.learning_rate+p.discount)*entry)
for discount in [0.,.4]:
    p=ModelParams(discount=discount,deployment_cost=.01,learning_rate=12)
    for factor in [1e-240,1e-200,1e-120,1.,1e120,1e200,1e240]:
        q,b,r=rescale_experiment(p,DecisionBounds(),.15,factor,1)
        for st in ['RF','RL','DF','DL']:
            d=.4 if st.startswith('R') else 0.
            ref=reference(p,st,.15,d);actual=payoff(q,st,.15*factor,d/factor)
            units.append({'discount':discount,'strategy':st,'time_factor':factor,'reference_payoff':ref,
                'actual_payoff':actual,'absolute_error':abs(actual-ref),'pass':abs(actual-ref)<1e-11})
with (out/'extreme_time_units.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(units[0]));w.writeheader();w.writerows(units)

with tempfile.TemporaryDirectory() as td:
    d=Path(td);write_json(d/'summary.json',{'all_pass':True});record_validation(d,Path(__file__))
    valid=verify_validation(d,Path(__file__))['valid']
    m=read_json(d/'manifest.json');m['config']['validator_sha256']='0'*64
    from entrysignallab.workflow import canonical_hash
    m['config_sha256']=canonical_hash(m['config']);write_json(d/'manifest.json',m)
    wrong_validator=not verify_validation(d,Path(__file__))['valid']
    (d/'manifest.json').unlink();missing=not verify_validation(d,Path(__file__))['valid']
summary={'edge_parameter_sets':24,'edge_follower_results':len(rows),'max_edge_payoff_error':max(x['absolute_error'] for x in rows),
    'extreme_unit_payoff_checks':len(units),'max_extreme_unit_error':max(x['absolute_error'] for x in units),
    'receipt_checks':{'valid_receipt_accepted':valid,'wrong_validator_rejected':wrong_validator,'missing_receipt_rejected':missing},
    'all_pass':all(x['pass'] for x in rows+units) and valid and wrong_validator and missing,
    'scope':'24 independently solved edge-peak parameter sets at three time scales, plus 56 independently integrated payoff checks. Network-zero follower optima have a unique derivative root in these domains. Sampled evidence, not arbitrary-model global certification.'}
write_json(out/'adversarial_summary.json',summary)
if not summary['all_pass']:raise SystemExit('Adversarial validation failed')
record_validation(out,Path(__file__));print(json.dumps(summary,indent=2))
