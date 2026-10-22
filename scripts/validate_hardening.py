"""Independent Decimal reference for the fixed-control range counterexample."""
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal,localcontext
import argparse,csv,json
from entrysignallab import ModelParams,DecisionBounds,optimize
from entrysignallab.workflow import write_json,record_validation

def reference(p,st,tau):
    with localcontext() as ctx:
        ctx.prec=100
        s,f,H,T,w,m,t=[Decimal.from_float(x) for x in [p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,tau]]
        k=f*s*t
        share=(1+k)/(1+k+w) if st=='RF' else 1/(1+w*(1+k))
        mass=(H-t)*(2*T-H-t)/2
        leading=t*(2*T-t)/2 if st=='RF' else Decimal(0)
        return float(m*s*(leading+mass*share))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    out=args.out
    if out.exists() and any(out.iterdir()):raise SystemExit('Choose a fresh output directory')
    out.mkdir(parents=True,exist_ok=True);rows=[]
    for st in ['RF','RL']:
        p=ModelParams(growth=5e-324 if st=='RF' else 1e-308,network=1e308,growth_end=1e308,horizon=1e308,
                      quality_ratio=1e292 if st=='RF' else 1e-308,margin_x=1e-292 if st=='RF' else 1e-308,margin_y=0)
        for fraction in [.1,.2,.4,.8]:
            tau=p.horizon*fraction;b=DecisionBounds(delay_lower=tau,delay_upper=tau,announcement_upper=0)
            actual=optimize(p,st,b,rival_delay=tau);expected=reference(p,st,tau);error=abs(actual['payoff']-expected)
            rows.append({'strategy':st,'delay_fraction':fraction,'reference_payoff':expected,'actual_payoff':actual['payoff'],
                         'absolute_error':error,'stationarity_residual':actual['announcement_stationarity_residual'],
                         'pass':error<1e-10 and actual['announcement_stationarity_residual']==0,'params':json.dumps(asdict(p),sort_keys=True)})
    with (out/'fixed_control_decimal.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary={'fixed_control_cases':len(rows),'max_absolute_error':max(x['absolute_error'] for x in rows),'all_pass':all(x['pass'] for x in rows),
             'scope':'100-digit Decimal arithmetic with independently transcribed zero-discount stock integrals; eight fixed-zero RF/RL cases, not a universal numerical-range certificate.'}
    write_json(out/'hardening_summary.json',summary)
    if not summary['all_pass']:raise SystemExit('Fixed-control verification failed')
    record_validation(out,Path(__file__),seed=0);print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
