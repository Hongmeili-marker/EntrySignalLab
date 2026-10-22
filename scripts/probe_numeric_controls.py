"""Independent zero-discount rational controls across wide finite scales."""
from pathlib import Path
from fractions import Fraction as F
import argparse, json, math, random
from entrysignallab import ModelParams, revenues, payoff, payoff_grid, demand
from entrysignallab.workflow import current_source_hashes

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);out=ap.parse_args().out
    out.mkdir(parents=True,exist_ok=False)
    rng=random.Random(20261018);records=[]
    def check(value, ref):
        try: expected=float(ref)
        except OverflowError: return None, None
        if not math.isfinite(expected):return None,None
        error=abs(value-expected)
        allowance=max(8*math.ulp(expected),1e-11*abs(expected))
        return error<=allowance,error/max(abs(expected),math.ulp(0.))
    for i in range(256):
        s,phi,m,w,d=[10.**rng.uniform(a,b) for a,b in [(-150,150),(-150,150),(-100,100),(-150,150),(-150,150)]]
        H=10.**rng.uniform(-50,50);T=2*H;t=H*.375
        p=ModelParams(growth=s,network=phi,growth_end=H,horizon=T,margin_x=m,quality_ratio=w)
        S,P,M,W,HQ,TQ,Q=map(F,[s,phi,m,w,H,T,t])
        for st in ['RF','RL','DF','DL']:
            delta=d if st.startswith('R') else 0.;D=F(delta)
            x=1+P*S*Q+(P*D*Q if st=='RF' else 0) if st.endswith('F') else 1+(P*D*Q if st=='RL' else 0)
            y=W if st.endswith('F') else W*(1+P*S*Q)
            z=x/(x+y);post=(HQ-Q)*(TQ-HQ)+(HQ-Q)**2/2;lead=Q*(TQ-Q/2)
            ref=M*S*((lead if st.endswith('F') else 0)+post*z)
            for method,call in [('payoff',lambda:payoff(p,st,t,delta)),('grid',lambda:float(payoff_grid(p,st,[t],[delta])[0,0]))]:
                try:
                    value=call();passed,relative=check(value,ref)
                    records.append({'case':i,'strategy':st,'method':method,'pass':passed is True,
                                    'relative_error':relative,'actual':value,'controlled_range_error':False})
                except ValueError as e:
                    expected,_=check(0.,ref)
                    records.append({'case':i,'strategy':st,'method':method,'pass':expected is None,
                                    'controlled_range_error':True,'error':str(e)})
            # Independently verify demand at an interior post-entry time.
            time=(t+H)/2;u=F(time)
            dx=S*((Q if st.endswith('F') else 0)+(u-Q)*z)
            dy=S*((Q if st.endswith('L') else 0)+(u-Q)*(1-z))
            vx,vy=demand(p,st,time,t,delta)
            for name,v,r in [('demand_x',vx,dx),('demand_y',vy,dy)]:
                passed,relative=check(v,r)
                records.append({'case':i,'strategy':st,'method':name,'pass':passed is True,
                                'relative_error':relative,'actual':v,'controlled_range_error':False})
    summary={'parameter_sets':256,'checks':len(records),'all_pass':all(r['pass'] for r in records),
             'failures':[r for r in records if not r['pass']],
             'controlled_range_errors':sum(r['controlled_range_error'] for r in records),
             'maximum_relative_error':max(r.get('relative_error') or 0 for r in records),
             'source_sha256':current_source_hashes(),'seed':20261018,
             'policy':'Exact rational zero-discount reference; allowance max(8 reference ULPs, relative 1e-11). Nonzero costs, discounted integration and global optimality are outside this added control corpus.'}
    (out/'checks.json').write_text(json.dumps(records,indent=2,allow_nan=False)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='source_sha256'},indent=2))
    if not summary['all_pass']:raise SystemExit(1)

if __name__=='__main__':main()
