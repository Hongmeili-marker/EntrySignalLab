"""Independent dense/refined check of zero-cost joint envelope classifications."""
from dataclasses import asdict
from pathlib import Path
from math import exp
import argparse,json,csv
import numpy as np
from scipy.optimize import minimize_scalar
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff
from entrysignallab.workflow import write_json

ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
out=Path(args.out)
if out.exists() and any(out.iterdir()):raise SystemExit('Choose a fresh output directory')
out.mkdir(parents=True,exist_ok=True)
rng=np.random.default_rng(20261010);rows=[]
for case in range(80):
    T=float(rng.uniform(.4,4));H=float(rng.uniform(.01,T));r=[0,.1,.5,2][case%4]
    p=ModelParams(horizon=T,growth_end=H,growth=float(10**rng.uniform(-3,0)),margin_x=float(rng.uniform(.05,1)),
                  deployment_cost=float(10**rng.uniform(-4,0)),learning_rate=float(rng.uniform(0,25)),discount=r)
    lo=0. if case%3 else .1*H;hi=H if case%5 else .8*H
    def upper(t):
        # Independently integrated response multiplier. r is either zero or >=.1.
        mass=(H-t)*(2*T-H-t)/2 if r==0 else exp(-r*t)*(-np.expm1(-r*(H-t)))/(r*r)-(H-t)*exp(-r*T)/r
        return p.margin_x*p.growth*mass-p.deployment_cost*exp(-(p.learning_rate+r)*t)
    grid=np.linspace(lo,hi,4097);values=[upper(float(t)) for t in grid]
    candidates=[(lo,values[0]),(hi,values[-1])]
    for i in range(1,len(grid)-1):
        if values[i]>values[i-1] and values[i]>=values[i+1]:
            q=minimize_scalar(lambda t:-upper(t),bounds=(grid[i-1],grid[i+1]),method='bounded',options={'xatol':1e-13})
            candidates.append((float(q.x),float(-q.fun)))
    ref_t,ref=max(candidates,key=lambda x:x[1]);actual=optimize(p,'RL',DecisionBounds(delay_lower=lo,delay_upper=hi,announcement_upper=None),rival_delay=min(.15,H))
    value=actual['supremum'];gap=ref-value
    expected_attained = hi == H and ref_t == H
    classification_consistent = (actual["attainment"]=="attained") == expected_attained
    consistent=abs(gap)<=1e-10 and classification_consistent
    if actual['attainment']=='attained':
        consistent=consistent and actual['delay']==H and hi==H and abs(actual['payoff']-payoff(p,'RL',H,0))<1e-12
    rows.append({'case':case,'status':actual['status'],'actual_supremum':value,'reference_supremum':ref,
                 'absolute_error':abs(gap),'actual_delay':actual.get('supremum_delay',actual['delay']),
                 'reference_delay':ref_t,'expected_attained':expected_attained,'classification_consistent':classification_consistent,'pass':consistent,'params':json.dumps(asdict(p),sort_keys=True),
                 'delay_lower':lo,'delay_upper':hi})
with (out/'joint_envelope.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary={'seed':20261010,'cases':len(rows),'max_absolute_error':max(r['absolute_error'] for r in rows),
         'all_pass':all(r['pass'] for r in rows),'classification_checks':len(rows),'classification_mismatches':sum(not r['classification_consistent'] for r in rows),'attained_cases':sum(r['status']=='attained_joint_optimum' for r in rows),
         'scope':'Independent dense/refined numerical envelope comparison; additional to analytical derivative structure and targeted boundary tests. Not a floating-point global certificate.'}
write_json(out/'joint_envelope_summary.json',summary);print(json.dumps(summary,indent=2))
if not summary['all_pass']:raise SystemExit('Joint envelope verification failed')

from entrysignallab.workflow import record_validation
record_validation(out,Path(__file__),seed=20261010)
