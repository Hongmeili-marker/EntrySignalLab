"""Reproduce a payoff-preserving unit conversion through the public API."""
import argparse
from pathlib import Path
from dataclasses import asdict
from entrysignallab import rescale_experiment,compare,payoff
from entrysignallab.workflow import load_config,write_json,manifest

ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
root=Path(__file__).resolve().parents[1]
config,p,bounds,rival,seed=load_config(root/'examples/discounted_quality.json')
q,b,new_rival=rescale_experiment(p,bounds,rival,12,1000)
old=compare(p,bounds,rival);new=compare(q,b,new_rival)
rows=[]
for a,c in zip(old['results'],new['results']):
    transformed=payoff(q,a['strategy'],a['delay']*12,a['announcement']*1000/12)
    rows.append({'strategy':a['strategy'],'original_payoff':a['payoff'],'transformed_same_control_payoff':transformed,
                 'converted_optimizer_payoff':c['payoff'],'same_control_error':abs(a['payoff']-transformed),
                 'optimizer_value_error':abs(a['payoff']-c['payoff'])})
if max(r['same_control_error'] for r in rows)>1e-12 or max(r['optimizer_value_error'] for r in rows)>1e-9:
    raise SystemExit('Unit invariance check failed')
out=Path(args.out)
if out.exists() and any(out.iterdir()): raise SystemExit('Choose a fresh output directory')
out.mkdir(parents=True,exist_ok=True)
record={'time_factor':12,'consumer_factor':1000,'original_params':asdict(p),'converted_params':asdict(q),
        'converted_bounds':asdict(b),'converted_rival_delay':new_rival,'comparisons':rows,
        'interpretation':'Representation change with fixed payoff units; no additional empirical validation.'}
write_json(out/'unit_invariance.json',record);manifest(out,config,seed,'unit_conversion')
