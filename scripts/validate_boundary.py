"""Independent Decimal stock integrals for the v0.5.0 audit cases. MIT License."""
from pathlib import Path
from decimal import Decimal,localcontext
import argparse,warnings
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,payoff,optimize
from entrysignallab.workflow import write_json,record_validation

def reference(p,st,t):
    # Independent zero-discount stock transcription; no operational kernel.
    with localcontext() as ctx:
        ctx.prec=100
        s,f,H,T,w,m,t=map(Decimal.from_float,[p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,t])
        k=f*s*t
        a,b=(1+k,w) if st.endswith('F') else (Decimal(1),w*(1+k))
        share=a/(a+b)
        response=(H-t)*(T-H)+(H-t)**2/2
        lead=t*T-t*t/2
        return float(s*m*(share*response+(lead if st.endswith('F') else 0)))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    if args.out.exists() and any(args.out.iterdir()):raise SystemExit('Choose a fresh output directory')
    rows=[]
    for w in [.5,1.,2.,10.]:
        p=ModelParams(growth=1,growth_end=1,horizon=1e308,network=0,quality_ratio=w,margin_x=1e-308,margin_y=1e308)
        for tau in [0.,.3]:
            for st in ['RF','RL','DF','DL']:
                actual=payoff(p,st,tau,0);expected=reference(p,st,tau)
                rows.append({'kind':'object_payoff','strategy':st,'quality_ratio':w,'delay':tau,'actual':actual,'reference':expected,'absolute_error':abs(actual-expected),'pass':abs(actual-expected)<1e-10})
    p=ModelParams();narrow=[]
    for width in [1,2,4,8]:
        lo=.1;hi=lo
        for _ in range(width):hi=float(np.nextafter(hi,1.))
        controls=[lo]
        while controls[-1]<hi:controls.append(float(np.nextafter(controls[-1],hi)))
        b=DecisionBounds(delay_lower=lo,delay_upper=hi,announcement_upper=0)
        for st in ['RL','DL']:
            with warnings.catch_warnings():
                warnings.simplefilter('error',RuntimeWarning);actual=optimize(p,st,b)['payoff']
            expected=max(reference(p,st,t) for t in controls)
            narrow.append({'kind':'narrow_interval','strategy':st,'ulps':width,'representable_controls':len(controls),'actual':actual,'reference':expected,'absolute_error':abs(actual-expected),'pass':abs(actual-expected)<1e-13})
    report={'object_payoff_cases':len(rows),'narrow_interval_results':len(narrow),'decimal_precision':100,'max_object_error':max(x['absolute_error'] for x in rows),'max_narrow_error':max(x['absolute_error'] for x in narrow),'all_pass':all(x['pass'] for x in rows+narrow),'scope':'Zero-discount independent 100-digit stock integrals and exhaustive binary64 controls in eight narrow intervals. Sampled agreement, not arbitrary-parameter certification.'}
    args.out.mkdir(parents=True);write_json(args.out/'boundary_results.json',rows+narrow);write_json(args.out/'boundary_summary.json',report);record_validation(args.out,Path(__file__),0)
    print(report)
    if not report['all_pass']:raise SystemExit('Boundary validation failed')

if __name__=='__main__':main()
