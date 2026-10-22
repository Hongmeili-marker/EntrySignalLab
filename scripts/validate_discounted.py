"""Independent discounted follower oracle using Gauss integration and vector bisection."""
from pathlib import Path
from dataclasses import asdict
from math import exp
import argparse,json,csv
import numpy as np
from scipy.optimize import minimize_scalar
from entrysignallab import ModelParams,DecisionBounds,optimize
from entrysignallab.workflow import write_json
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
out=Path(args.out)
if out.exists() and any(out.iterdir()):raise SystemExit('Choose a fresh output directory')
out.mkdir(parents=True,exist_ok=True)
rng=np.random.default_rng(20261011);nodes,weights=np.polynomial.legendre.leggauss(64);rows=[]
for case in range(60):
    T=float(rng.uniform(.3,3));H=float(rng.uniform(.02,T));r=[1e-12,1e-5,.1,.5,2,20][case%6]
    p=ModelParams(horizon=T,growth_end=H,growth=float(10**rng.uniform(-2,.3)),network=float(10**rng.uniform(-2,1)),
        quality_ratio=float(10**rng.uniform(-1,1)),margin_x=float(rng.uniform(.05,1)),discount=r,
        announcement_cost=0 if case%7==0 else float(10**rng.uniform(-6,-1)),
        deployment_cost=float(10**rng.uniform(-4,-.3)),learning_rate=float(rng.uniform(0,30)))
    cap=float(rng.uniform(.1,3));lo=.1*H if case%4==0 else 0.;hi=.8*H if case%5==0 else H
    bounds=DecisionBounds(delay_lower=lo,delay_upper=hi,announcement_upper=cap)
    def reference(t,st):
        tau=np.atleast_1d(t).astype(float);length=H-tau
        # Distinct quadrature formulation of post-entry linear stock and mature stock.
        x=tau[:,None]+length[:,None]*(nodes[None,:]+1)/2
        mass=length/2*np.sum(weights[None,:]*(x-tau[:,None])*np.exp(-r*x),axis=1)
        x2=H+(T-H)*(nodes+1)/2
        mass+=length*(T-H)/2*np.sum(weights*np.exp(-r*x2))
        benefit=p.margin_x*p.growth*mass;alpha=p.network*tau;beta=p.quality_ratio*(1+p.network*p.growth*tau)
        if st=='DL':delta=np.zeros_like(tau)
        elif p.announcement_cost==0:delta=np.where(benefit*alpha>0,cap,0.)
        else:
            lower=np.zeros_like(tau);upper=np.full_like(tau,cap)
            for _ in range(55):
                mid=(lower+upper)/2;gradient=benefit*alpha*beta/(1+alpha*mid+beta)**2-p.announcement_cost*mid
                lower=np.where(gradient>0,mid,lower);upper=np.where(gradient>0,upper,mid)
            delta=(lower+upper)/2
        share=(1+alpha*delta)/(1+alpha*delta+beta)
        value=benefit*share-p.announcement_cost*delta**2/2-p.deployment_cost*np.exp(-p.learning_rate*tau-r*tau)
        return value if np.ndim(t)>0 else float(value[0])
    for st in ['RL','DL']:
        mesh=np.linspace(lo,hi,4097);vv=reference(mesh,st);candidates=[(lo,float(vv[0])),(hi,float(vv[-1]))]
        intervals={(mesh[0],mesh[1]),(mesh[-2],mesh[-1])}
        for i in range(1,len(mesh)-1):
            if vv[i]>vv[i-1] and vv[i]>=vv[i+1]:intervals.add((mesh[i-1],mesh[i+1]))
        for a,b in sorted(intervals):
            sol=minimize_scalar(lambda u:-reference(a+(b-a)*u,st),bounds=(0,1),method='bounded',options={'xatol':1e-12})
            if not sol.success:raise RuntimeError('Independent refinement did not converge')
            candidates.append((float(a+(b-a)*sol.x),float(-sol.fun)))
        ref_t,ref=max(candidates,key=lambda x:x[1]);actual=optimize(p,st,bounds,rival_delay=min(.15,H));gap=ref-actual['payoff']
        rows.append({'case':case,'strategy':st,'discount':r,'actual_payoff':actual['payoff'],'reference_payoff':ref,'payoff_deficit':gap,
            'actual_delay':actual['delay'],'reference_delay':ref_t,'pass':abs(gap)<1e-9,'params':json.dumps(asdict(p),sort_keys=True),
            'cap':cap,'delay_lower':lo,'delay_upper':hi})
with (out/'discounted_followers.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary={'seed':20261011,'parameter_sets':60,'follower_results':len(rows),'max_absolute_difference':max(abs(x['payoff_deficit']) for x in rows),
    'max_payoff_deficit':max(x['payoff_deficit'] for x in rows),'all_pass':all(x['pass'] for x in rows),
    'scope':'Independent 64-node Gauss integration, vectorized intensity bisection and 4097-delay grid/local refinement. Sampled discounted domain, not a global certificate.'}
write_json(out/'discounted_summary.json',summary);print(json.dumps(summary,indent=2))
if not summary['all_pass']:raise SystemExit('Discounted follower oracle failed')

from entrysignallab.workflow import record_validation
record_validation(out,Path(__file__),seed=20261011)
