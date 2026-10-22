"""Audit counterexamples and broad unit changes against the installed release."""
from pathlib import Path
from math import exp
from dataclasses import asdict
import argparse,json,csv,tempfile
import numpy as np
from entrysignallab import *
from entrysignallab.workflow import manifest,verify_manifest,write_json,current_source_hashes
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args();out=Path(args.out)
if out.exists() and any(out.iterdir()):raise SystemExit('Choose a fresh output directory')
out.mkdir(parents=True,exist_ok=True);checks=[]
def add(name,observation,success):checks.append({'name':name,'observed':observation,'pass':bool(success)})
p=ModelParams(growth_end=2e-308,horizon=1e-307,discount=1e308,learning_rate=1e308,deployment_cost=1,margin_x=0,margin_y=0)
v=payoff(p,'DL',1e-308);add('combined_rate',{'actual':v,'expected':-exp(-2)},abs(v+exp(-2))<1e-14)
try:rescale_experiment(ModelParams(announcement_cost=1e-200),DecisionBounds(announcement_upper=None),.15,1e-100,1);rejected=False;msg=''
except ValueError as e:rejected=True;msg=str(e)
add('positive_cost_preserved_or_rejected',msg,rejected)
r=optimize(ModelParams(announcement_cost=1e6),'RF');add('tiny_interior_label',r['announcement_active'],r['announcement_active']=='interior')
with tempfile.TemporaryDirectory() as td:
    d=Path(td);write_json(d/'config.json',{});m=manifest(d,{},104,'test');m['source_sha256']['model.py']='0'*64;write_json(d/'manifest.json',m)
    report=verify_manifest(d,current_source_hashes());add('source_binding_rejects_mismatch',report,not report['valid'])
    write_json(d/'extra.json',{});report=verify_manifest(d);add('inventory_rejects_addition',report,not report['valid'])
rows=[];rng=np.random.default_rng(20261012)
for i in range(20):
    p=ModelParams(discount=float(rng.uniform(0,2)),announcement_cost=float(10**rng.uniform(-5,-2)),deployment_cost=float(rng.uniform(.005,.03)),learning_rate=float(rng.uniform(0,15)),quality_ratio=float(rng.uniform(.3,3)))
    a=[1e-9,1e-3,1,1e3,1e9][i%5];b=[1e-6,1,1e6,100][i%4]
    q,bounds,rival=rescale_experiment(p,DecisionBounds(),.15,a,b)
    for st in ['RF','RL','DF','DL']:
        old=optimize(p,st);new=optimize(q,st,bounds,rival)
        d=.4 if st.startswith('R') else 0
        error=abs(payoff(p,st,.2,d)-payoff(q,st,.2*a,d*b/a));gap=abs(old['payoff']-new['payoff'])
        # Near numerical ties can move candidate coordinates; only exact active-domain labels are audited separately.
        rows.append({'case':i,'strategy':st,'time_factor':a,'consumer_factor':b,'same_control_error':error,'optimizer_error':gap,'pass':error<1e-10 and gap<1e-9})
with (out/'wide_unit_changes.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
add('wide_unit_changes',{'comparisons':len(rows),'payoff_checks':len(rows)*2,'max_same_control_error':max(x['same_control_error'] for x in rows),'max_optimizer_error':max(x['optimizer_error'] for x in rows)},all(x['pass'] for x in rows))
summary={'checks':checks,'all_pass':all(x['pass'] for x in checks),'scope':'Targeted audit states and 20 finite unit conversions. Does not promise every finite scale is numerically representable.'}
write_json(out/'revision_summary.json',summary);print(json.dumps(summary,indent=2))
if not summary['all_pass']:raise SystemExit('Revision validation failed')

from entrysignallab.workflow import record_validation
record_validation(out,Path(__file__),seed=20261012)
