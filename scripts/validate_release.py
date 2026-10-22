"""Independent audit oracle; runs against the installed release. Run with installed wheel."""
from pathlib import Path
from dataclasses import asdict
from math import exp
import sys,json,csv,platform,unittest,io,contextlib,subprocess,argparse
import numpy as np, scipy, matplotlib
from scipy.integrate import quad
from scipy.optimize import minimize_scalar,brentq
from entrysignallab import ModelParams, DecisionBounds, optimize, compare, payoff, revenues, shares, demand
from entrysignallab.model import announcement_gradient
from entrysignallab.cli import main
BASE=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args()
OUT=Path(args.out).resolve()
if OUT.exists() and any(OUT.iterdir()):raise SystemExit('Choose a fresh verification directory')
OUT.mkdir(parents=True,exist_ok=True)
checks=[]
def check(name,expected,observed,ok,details=None):
    checks.append(dict(name=name,expected=expected,observed=observed,pass_=bool(ok),details=details))
# Counterexample with a provable, attained joint maximum at maturity.
p=ModelParams(deployment_cost=.05,learning_rate=1)
b=DecisionBounds(announcement_upper=None)
r=optimize(p,'RL',b)
expected=-p.deployment_cost*exp(-p.learning_rate*p.growth_end)
# For every positive tau, payoff <= U(tau)=m*s*(H-tau)*(2T-H-tau)/2-cD*exp(-k*tau).
# U'(tau)=-m*s*(T-tau)+k*cD*exp(-k*tau) >= k*cD*exp(-k*H)-m*s*T >0.
lower_derivative=p.learning_rate*p.deployment_cost*exp(-p.learning_rate*p.growth_end)-p.margin_x*p.growth*p.horizon
attained=payoff(p,'RL',p.growth_end,0)
check('A01_joint_unbounded_boundary','finite joint optimum: delay=H, announcement=0 representative',r,r['payoff'] is not None and abs(r['payoff']-expected)<1e-12,{'attained_payoff':attained,'expected_payoff':expected,'strict_derivative_lower_bound':lower_derivative,'params':asdict(p),'bounds':asdict(b),'comparison_at_simultaneous_rival_entry':compare(p,b,rival_delay=0),'proof':'For tau>0, payoff <= U(tau); U is strictly increasing. At H, U(H) is attained for every finite delta. At tau=0, actual payoff <=U(0)<U(H).'})
# A finite cap with zero focal margin: all follower delays have exactly the same payoff.
pflat=ModelParams(margin_x=0)
rr=optimize(pflat,'DL')
check('A02_zero_margin_nonuniqueness','delay_nonunique=True for full flat delay interval',rr,rr['delay_nonunique'],{'payoffs_at_three_delays':[payoff(pflat,'DL',t) for t in [0,.15,.3]]})
rr=optimize(ModelParams(growth=0),'RL',DecisionBounds(delay_lower=.1,delay_upper=.1))
check('A03_singleton_delay_uniqueness','delay_nonunique=False when admissible delay set is {0.1}',rr,not rr['delay_nonunique'])
# A zero growth object still has a positive declared growth period: existing recognized flat case.
rr=optimize(ModelParams(growth=0),'RL')
check('A04_existing_zero_growth_nonuniqueness',True,rr['delay_nonunique'],rr['delay_nonunique'])
# CLI validation before output: ordinary invalid configs are guarded, benchmark differs.
invalid=OUT/'invalid_benchmark_should_not_exist'
with contextlib.redirect_stderr(io.StringIO()) as err:
    code=main(['benchmark','--out',str(invalid),'--grid-points','1'])
check('A05_benchmark_prevalidation','exit 2 with no output directory',{'exit':code,'directory_exists':invalid.exists(),'stderr':err.getvalue()},code==2 and not invalid.exists())
# Additional source-independent closed form revenue and optimizer oracle (r=0).
rng=np.random.default_rng(20261005); integration=[]
def scalar_stocks(p,st,t,tau,d):
    if st=='RF': wx,wy=1+p.network*(p.growth+d)*tau,p.quality_ratio
    elif st=='DF': wx,wy=1+p.network*p.growth*tau,p.quality_ratio
    elif st=='RL': wx,wy=1+p.network*d*tau,p.quality_ratio*(1+p.network*p.growth*tau)
    else: wx,wy=1,p.quality_ratio*(1+p.network*p.growth*tau)
    z=wx/(wx+wy);u=min(t,p.growth_end)
    if u<=tau:lead=p.growth*u;follow=0.
    else:lead=p.growth*tau;follow=p.growth*(u-tau)
    return (lead+follow*z,follow*(1-z)) if st.endswith('F') else (follow*z,lead+follow*(1-z))
for i in range(400):
    T=float(rng.uniform(.2,4)); H=float(rng.uniform(.001,T))
    p=ModelParams(growth=float(10**rng.uniform(-3,1)),network=float(10**rng.uniform(-3,1)),growth_end=H,horizon=T,quality_ratio=float(10**rng.uniform(-1,1)),margin_x=float(rng.uniform(0,2)),margin_y=float(rng.uniform(0,2)),discount=[0,1e-12,1e-5,.01,.5,5,30,100][i%8])
    tau=float(rng.uniform(0,H));d=float(rng.uniform(0,10));bounds=sorted(set([0,tau,H,T]))
    for st in ['RF','RL','DF','DL']:
        ds=d if st[0]=='R' else 0.; actual=revenues(p,st,tau,ds)
        for j,m in enumerate([p.margin_x,p.margin_y]):
            ref=m*sum(quad(lambda t:exp(-p.discount*t)*scalar_stocks(p,st,t,tau,ds)[j],a,b,epsabs=1e-13,epsrel=2e-12)[0] for a,b in zip(bounds,bounds[1:]))
            integration.append({'case':i,'strategy':st,'platform':'xy'[j],'actual':actual[j],'independent':ref,'absolute_error':abs(actual[j]-ref),'scaled_error':abs(actual[j]-ref)/max(1.,abs(ref))})
with (OUT/'independent_integration.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(integration[0]));w.writeheader();w.writerows(integration)
check('A06_independent_integration_3200','max scaled error <= 1e-10',{'comparisons':len(integration),'max_absolute_error':max(x['absolute_error'] for x in integration),'max_scaled_error':max(x['scaled_error'] for x in integration)},max(x['scaled_error'] for x in integration)<1e-10)
def closed_payoff(p,st,t,d):
    M=p.growth*(p.growth_end-t)*(2*p.horizon-p.growth_end-t)/2
    wx=1+p.network*t*d if st=='RL' else 1.
    wy=p.quality_ratio*(1+p.network*p.growth*t)
    return p.margin_x*M*wx/(wx+wy)-p.announcement_cost*d*d/2-p.deployment_cost*exp(-p.learning_rate*t)
def closed_profile(p,st,t,cap):
    if st=='DL':return 0.
    M=p.growth*(p.growth_end-t)*(2*p.horizon-p.growth_end-t)/2
    a=p.network*t;v=p.quality_ratio*(1+p.network*p.growth*t)
    def g(d):return p.margin_x*M*a*v/(1+a*d+v)**2-p.announcement_cost*d
    if g(0)<=0:return 0.
    if p.announcement_cost==0 or g(cap)>=0:return cap
    # Independent bracket + a tighter tolerance than the implementation.
    return brentq(g,0,cap,xtol=1e-14,rtol=1e-14)
opts=[]
for i in range(60):
    H=float(rng.uniform(.02,.95));p=ModelParams(growth=float(10**rng.uniform(-3,.7)),network=float(10**rng.uniform(-2,1)),growth_end=H,quality_ratio=float(10**rng.uniform(-1,1)),margin_x=float(10**rng.uniform(-2,.3)),announcement_cost=0 if i%6==0 else float(10**rng.uniform(-7,-.5)),deployment_cost=0 if i%9==0 else float(10**rng.uniform(-5,0)),learning_rate=float(rng.uniform(0,80)))
    cap=float(10**rng.uniform(-1,1));b=DecisionBounds(announcement_upper=cap)
    for st in ['RL','DL']:
        def value(t):return closed_payoff(p,st,t,closed_profile(p,st,t,cap))
        grid=np.linspace(0,H,4097);vv=np.array([value(float(t)) for t in grid]);cand=[(float(grid[0]),float(vv[0])),(float(grid[-1]),float(vv[-1]))]
        intervals={(grid[0],grid[1]),(grid[-2],grid[-1])}
        for j in range(1,len(grid)-1):
            if vv[j]>=vv[j-1] and vv[j]>=vv[j+1] and (vv[j]>vv[j-1] or vv[j]>vv[j+1]):
                intervals.add((grid[j-1],grid[j+1]))
        for left,right in sorted(intervals):
            q=minimize_scalar(lambda u:-value(left+(right-left)*u),bounds=(0,1),method='bounded',options={'xatol':1e-12})
            if not q.success:raise RuntimeError('Independent refinement did not converge')
            cand.append((float(left+(right-left)*q.x),float(-q.fun)))
        tref,vref=max(cand,key=lambda x:x[1]);actual=optimize(p,st,b,rival_delay=min(.15,H))
        row={'case':i,'strategy':st,'actual_payoff':actual['payoff'],'reference_payoff':vref,'reference_delay':tref,'actual_delay':actual['delay'],'gap':vref-actual['payoff'],'local_residual':actual['local_improvement_residual'],'params':json.dumps(asdict(p),sort_keys=True),'cap':cap}
        opts.append(row)
with (OUT/'independent_optimizer.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(opts[0]));w.writeheader();w.writerows(opts)
assessed=[x['local_residual'] for x in opts if x['local_residual'] is not None]
check('A07_independent_optimizer_120','no payoff deficit above 1e-9',{'cases':60,'follower_results':len(opts),'max_payoff_deficit':max(x['gap'] for x in opts),'max_local_improvement_residual':max(assessed) if assessed else None,'assessed_legacy_residual_results':len(assessed),'unassessed_legacy_residual_results':len(opts)-len(assessed)},max(x['gap'] for x in opts)<1e-9)
# Numerical stress: representable economic objective but intermediate square overflows.
psmall=ModelParams(growth=1e-150,network=1e150,quality_ratio=1e155)
try: r=optimize(psmall,'RF'); obs=r; good=r['payoff'] is not None
except Exception as exc: obs={'exception':type(exc).__name__,'message':str(exc)};good=False
check('A08_intermediate_gradient_square','finite optimization or controlled ValueError with scale guidance',obs,good,{'params':asdict(psmall),'classification':'extreme scale robustness; outside reported numerical validation range'})
# A declared arbitrarily small positive announcement cost makes bracketing impractical.
ptiny=ModelParams(announcement_cost=1e-100)
try:r=optimize(ptiny,'RF',DecisionBounds(announcement_upper=None));obs=r;good=True
except Exception as exc:obs={'exception':type(exc).__name__,'message':str(exc)};good=False
check('A09_tiny_cost_root_bracket','finite RF candidate for a finite positive cost',obs,good,{'params':asdict(ptiny),'classification':'extreme scale robustness; outside reported numerical validation range'})
# Three shipped notebook cells: execute in the installed-wheel interpreter.
ns={};notebook=json.loads((BASE/'examples/quick_start.ipynb').read_text());cells=[c for c in notebook['cells'] if c['cell_type']=='code']
try:
    with contextlib.redirect_stdout(io.StringIO()):
        for cell in cells:exec(''.join(cell['source']),ns)
    check('A10_notebook','all 3 cells execute',len(cells),len(cells)==3)
except Exception as exc:check('A10_notebook','all 3 cells execute',str(exc),False)
result={'audit_seed':20261005,'environment':{'python':sys.version,'numpy':np.__version__,'scipy':scipy.__version__,'matplotlib':matplotlib.__version__,'platform':platform.platform(),'installed_package_path':__import__('entrysignallab').__file__,'venv':sys.prefix,'base_prefix':sys.base_prefix},'checks':checks,'scope':'Targeted counterexamples are distinct from sampled agreement checks. No global optimality or empirical validity certification.'}
(OUT/'audit_numerics.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
if not all(c['pass_'] for c in checks): raise SystemExit('Verification failed; inspect audit_numerics.json')
print(json.dumps({'environment':result['environment'],'checks':[{'name':c['name'],'pass':c['pass_'],'observed':c['observed']} for c in checks]},indent=2))

from entrysignallab.workflow import record_validation
record_validation(OUT,Path(__file__),seed=20261005)
