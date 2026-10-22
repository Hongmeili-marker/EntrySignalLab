"""Independent numeric-entry and research metadata acceptance for v0.13.0."""
from pathlib import Path
from dataclasses import replace
from decimal import Decimal,localcontext
from fractions import Fraction
import argparse,json,math,subprocess,sys,warnings
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,compare,demand,payoff,payoff_grid
from entrysignallab.solver import compare_results
from entrysignallab.research import default_research_kernel,optimize_research,ResearchKernel,ModelCapabilities
from entrysignallab.workflow import load_config,read_json,write_json,record_validation

def dec(x):return Decimal.from_float(float(x))
def stocks(p,st,t,lag,intensity):
    with localcontext() as ctx:
        ctx.prec=80
        s,n,H,T,w=map(dec,[p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio]);t,lag,intensity=map(dec,[t,lag,intensity])
        if st.endswith('F'):a=1+n*(s+intensity)*lag if st=='RF' else 1+n*s*lag;b=w
        else:a=1+n*intensity*lag if st=='RL' else Decimal(1);b=w*(1+n*s*lag)
        mass=s*max(Decimal(0),min(t,H)-lag);lead=s*min(t,lag)
        return [float(mass*a/(a+b)+(lead if st.endswith('F') else 0)),float(mass*b/(a+b)+(0 if st.endswith('F') else lead))]

def grid_reference(p,st,tau,intensity):
    with localcontext() as ctx:
        ctx.prec=80
        s,n,H,T,w,m,r,cA,cD,k=map(dec,[p.growth,p.network,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,p.deployment_cost,p.learning_rate])
        tau,intensity=map(dec,[tau,intensity])
        if st.endswith('F'):a=1+n*(s+intensity)*tau if st=='RF' else 1+n*s*tau;b=w
        else:a=1+n*intensity*tau if st=='RL' else Decimal(1);b=w*(1+n*s*tau)
        if r:
            j0=lambda lo,hi:((-r*lo).exp()-(-r*hi).exp())/r
            j1=lambda lo,hi:((1+r*lo)*(-r*lo).exp()-(1+r*hi)*(-r*hi).exp())/(r*r)
            response=j1(tau,H)-tau*j0(tau,H)+(H-tau)*j0(H,T)
            lead=j1(Decimal(0),tau)+tau*j0(tau,T)
        else:response=(H-tau)*(T-H)+(H-tau)**2/2;lead=tau*T-tau*tau/2
        entry=Decimal(0) if st.endswith('F') else tau
        return float(m*s*((lead if st.endswith('F') else 0)+response*a/(a+b))-cA*intensity*intensity/2-cD*(-(k+r)*entry).exp())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True,type=Path);out=ap.parse_args().out.resolve()
    if out.exists():raise SystemExit('Choose a fresh output directory')
    out.mkdir(parents=True);checks=[];typed=[];json_rows=[];array_rows=[];stock_rows=[];grid_rows=[];research_rows=[]
    p=ModelParams();b=DecisionBounds();sts=['RF','RL','DF','DL']
    def check(name,condition,detail=None):checks.append({'name':name,'pass':bool(condition),'detail':detail})
    def reject(name,f):
        try:f();accepted=True;error=None
        except ValueError as e:accepted=False;error=str(e)
        check(name,not accepted,error);return not accepted
    datasets=[('int64',[np.int64(2**63-1),np.int64(-(2**63-1)),np.int64(0),np.int64(-1)]),
      ('float32',[np.float32(3e38),np.float32(-3e38),np.float32(-3e38),np.float32(-3e38)]),
      ('uint64',[np.uint64(0),np.uint64(2**64-1),np.uint64(1),np.uint64(2)]),
      ('int32',[np.int32(-2**31),np.int32(2**31-1),np.int32(1),np.int32(-1)]),
      ('float16',[np.float16(-60000),np.float16(60000),np.float16(0),np.float16(1)]),
      ('float64',[np.float64(-1e300),np.float64(1e300),np.float64(0),np.float64(1)]),
      ('fraction',[Fraction(1,8),Fraction(1,4),Fraction(-1,2),Fraction(0)])]
    for name,values in datasets:
        rows=[{'strategy':s,'payoff':v,'local_quality_passed':np.bool_(True)} for s,v in zip(sts,values)]
        oracle=[dec(v) for v in values];best=max(oracle);labels=[s for s,v in zip(sts,oracle) if v==best]
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter('always');r=compare_results(rows,0.)
        expected_gap=float(sorted(oracle,reverse=True)[0]-sorted(oracle,reverse=True)[1])
        check('A01_ranking_'+name,r['co_best']==labels)
        check('A01_gap_'+name,r['entry_payoff_gap']==expected_gap and r['entry_payoff_gap_diagnostic']['representation']=='finite')
        check('A01_native_json_'+name,all(type(x['payoff']) is float and type(x['local_quality_passed']) is bool for x in r['results']) and bool(json.dumps(r,allow_nan=False)) and not ws)
        check('A01_copy_'+name,all(type(rows[i]['payoff']) is type(values[i]) for i in range(4)) and all(a is not c for a,c in zip(rows,r['results'])))
        custom=compare(p,tie_tolerance=0.,optimizer=lambda p,s,b,r:rows[sts.index(s)])
        check('A01_custom_'+name,custom['co_best']==labels)
        typed.append({'dtype':name,'expected':labels,'actual':r['co_best'],'entry_gap':r['entry_payoff_gap'],'warnings':[str(x.message) for x in ws]})
    r=compare_results([{'strategy':s,'payoff':v} for s,v in zip(sts,[sys.float_info.max,-sys.float_info.max,-sys.float_info.max,-sys.float_info.max])],0.)
    check('A01_real_binary64_range',r['co_best']==['RF'] and r['entry_payoff_gap'] is None and r['entry_payoff_gap_diagnostic']['representation']=='outside_float_range')
    reject('A01_nonzero_payoff_underflow',lambda:compare_results([{'strategy':s,'payoff':Fraction(1,10**500)} for s in sts]))
    write_json(out/'typed_comparison.json',typed)

    literals=['1e-400','-1e-400','1.000e-999','-0.001E-999','0.00001e-999','-0.00001e-999','1e999','-1e999']
    cli_rejected=0
    for i,token in enumerate(literals):
        source='{"params":{"growth":'+token+'}}';path=out/f'literal_{i}.json';path.write_text(source)
        lexical=json.loads(source,parse_float=Decimal)['params']['growth']
        check('A02_oracle_nonzero_'+str(i),lexical!=0)
        reject('A02_load_'+str(i),lambda:load_config(path));reject('A02_archive_read_'+str(i),lambda:read_json(path))
        output=out/f'cli_reject_{i}'
        r=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(path),'--out',str(output)],capture_output=True,text=True)
        correct=r.returncode==2 and not output.exists();cli_rejected+=int(correct);check('A02_cli_'+str(i),correct,r.stderr)
        json_rows.append({'literal':token,'decimal':str(lexical),'exit':r.returncode,'directory_exists':output.exists(),'stderr':r.stderr})
    for i,token in enumerate(['0e-400','-0e-400','0.000E99999999999999999999','5e-324','0.1']):
        path=out/f'valid_{i}.json';path.write_text('{"params":{"growth":'+token+'}}')
        value=load_config(path)[1].growth;check('A02_valid_'+str(i),value==float(token))
    zero=out/'valid_0.json';r=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(zero),'--out',str(out/'cli_zero_control')],capture_output=True,text=True)
    check('A02_cli_zero_control',r.returncode==0,r.stderr)
    for label,source in [('duplicate','{"params":{"growth":0.1,"growth":0.2}}'),('nan','{"params":{"growth":NaN}}'),('unknown','{"not_a_field":1}')]:
        path=out/(label+'.json');path.write_text(source);reject('A02_'+label,lambda:load_config(path))
    path=out/'integer.json';path.write_text(json.dumps({'seed':10**100+1,'label':'1e-400'}));c=load_config(path)
    check('A02_integer_and_string',type(c[4]) is int and c[4]==10**100+1 and c[0]['label']=='1e-400')
    write_json(out/'json_literals.json',json_rows)

    tiny=np.longdouble('1e-400');wide=bool(tiny!=0 and float(tiny)==0);check('A03_host_wider_longdouble',wide)
    operations=[('negative_time_scalar',lambda:demand(p,'DL',-tiny,.1)),('negative_time_vector',lambda:demand(p,'DL',np.array([-tiny]),.1)),
      ('negative_time_matrix',lambda:demand(p,'DL',np.array([[-tiny,.2]],dtype=np.longdouble),.1)),('positive_time',lambda:demand(p,'DL',np.array([tiny]),.1)),
      ('negative_delay',lambda:payoff_grid(p,'DL',np.array([-tiny]),[0.])),('positive_delay',lambda:payoff_grid(p,'DL',np.array([tiny]),[0.])),
      ('silent_intensity',lambda:payoff_grid(p,'DL',[.1],np.array([tiny]))),('negative_intensity',lambda:payoff_grid(p,'RL',[.1],np.array([-tiny]))),
      ('discounted_silent_intensity',lambda:payoff_grid(replace(p,discount=.4),'DL',[.1],np.array([tiny])))]
    for name,f in operations:array_rows.append({'name':name,'rejected':reject('A03_'+name,f)})
    for name,f in [('fraction_underflow',lambda:demand(p,'DL',[Fraction(-1,10**500)],.1)),('complex',lambda:demand(p,'DL',[.2+0j],.1)),
      ('negative_subnormal',lambda:demand(p,'DL',[-math.ulp(0.)],.1)),('boolean',lambda:demand(p,'DL',[True],.1)),('string',lambda:demand(p,'DL',['0.2'],.1))]:reject('A03_'+name,f)
    for name,t in [('scalar',.2),('integer_matrix',np.array([[0,1],[1,0]],dtype=np.uint64)),('subnormal',[math.ulp(0.)]),('empty',np.array([],dtype=float))]:
        x,y=demand(p,'DL',t,.125);check('A03_shape_'+name,np.shape(x)==np.shape(t) and np.shape(y)==np.shape(t) and np.all(np.isfinite(x)))
    write_json(out/'array_conversion.json',{'host_wide':wide,'cases':array_rows})

    maximum_stock_error=0.;reference_values=0;fraction_cases=0
    for st in sts:
        intensity=Fraction(1,4) if st.startswith('R') else Fraction(0)
        for label,times in [('scalar',.2),('vector',[.2,.3]),('matrix',np.array([[0.,.125],[.2,1.]]))]:
            got=demand(p,st,times,Fraction(1,8),intensity);native=demand(p,st,times,.125,float(intensity));fraction_cases+=1
            check('A04_native_'+st+'_'+label,all(np.array_equal(a,c) for a,c in zip(got,native)))
            expected=np.array([stocks(p,st,t,.125,float(intensity)) for t in np.asarray(times).flat]).T
            actual=np.array([np.asarray(x).ravel() for x in got]);err=float(np.max(np.abs(actual-expected)));maximum_stock_error=max(maximum_stock_error,err);reference_values+=expected.size
            check('A04_decimal_'+st+'_'+label,err<=1e-14,err)
            stock_rows.append({'strategy':st,'shape':label,'reference_values':int(expected.size),'max_absolute_error':err})
    write_json(out/'stock_references.json',stock_rows)
    maximum_grid_error=0.;grid_values=0
    for discount in [0.,.4]:
        q=replace(p,discount=discount,announcement_cost=.0002,deployment_cost=.012,learning_rate=12.)
        for st in sts:
            ts=np.array([0.,.125,.3],dtype=np.float32);ts[-1]=0.25 # avoid rounding past H
            ds=np.array([0.,.125] if st.startswith('R') else [0.],dtype=np.float32)
            got=payoff_grid(q,st,ts,ds);expected=np.array([[grid_reference(q,st,float(t),float(d)) for t in ts] for d in ds])
            err=float(np.max(abs(got-expected)));maximum_grid_error=max(maximum_grid_error,err);grid_values+=got.size
            check('A04_grid_'+str(discount)+'_'+st,err<=1e-14,err)
            grid_rows.append({'strategy':st,'discount':discount,'values':int(got.size),'max_absolute_error':err})
    write_json(out/'grid_references.json',grid_rows)

    kernel=default_research_kernel();unbounded=DecisionBounds(announcement_upper=None);reference=optimize_research(kernel,p,'RL',unbounded,.15)
    def altered(change,st='RL',params=p,bounds=unbounded):
        r=optimize_research(kernel,params,st,bounds,.15);r.update(change)
        return optimize_research(replace(kernel,conditional_solver=lambda *a:dict(r)),params,st,bounds,.15)
    mutations=[('attained_status',{'status':'attained_joint_optimum'}),('profile_status',{'status':'profile_optimum'}),('value',{'supremum':1000.}),
      ('negative_lag',{'supremum_delay':-.1}),('outside_lag',{'supremum_delay':1000.}),('wrong_inside_lag',{'supremum_delay':.2}),
      ('combined',{'status':'attained_joint_optimum','supremum':1000.,'supremum_delay':1000.})]
    for name,change in mutations:research_rows.append({'name':name,'rejected':reject('A05_'+name,lambda:altered(change))})
    for field in ['status','supremum','supremum_delay']:reject('A05_missing_'+field,lambda:altered({field:None}))
    reject('A05_RF_spurious',lambda:altered({'supremum':1.},st='RF'))
    reject('A05_tolerance_not_user_quality',lambda:altered({'supremum':1000.},bounds=replace(unbounded,payoff_atol=1e9,payoff_rtol=1e9)))
    reject('A05_small_scale_false_zero',lambda:altered({'supremum':0.},params=replace(p,margin_x=1e-280)))
    accepted=altered({'supremum_delay':math.ulp(0.)});check('A05_equal_envelope_location',accepted['supremum_delay']==math.ulp(0.))
    for st in ['RF','RL']:check('A05_genuine_'+st,altered({},st=st)['payoff'] is None)
    joint=optimize_research(kernel,replace(p,deployment_cost=.05,learning_rate=1.),'RL',unbounded,0.)
    check('A05_joint_boundary',joint['status']=='attained_joint_optimum' and joint['delay']==p.growth_end)
    supremum_refs=[]
    for q,lo in [(p,0.),(replace(p,growth=.2,growth_end=.4,horizon=1.4,margin_x=.3),.05),(replace(p,margin_x=1e-280),0.)]:
        bb=replace(unbounded,delay_lower=lo);r=optimize_research(kernel,q,'RL',bb,.15)
        with localcontext() as ctx:
            ctx.prec=80;s,m,H,T,t=map(dec,[q.growth,q.margin_x,q.growth_end,q.horizon,lo]);oracle=float(m*s*((H-t)*(T-H)+(H-t)**2/2))
        relative=abs(r['supremum']/oracle-1) if oracle else abs(r['supremum'])
        check('A05_decimal_supremum_'+str(len(supremum_refs)),r['payoff'] is None and r['supremum_delay']==lo and relative<=1e-12,relative)
        supremum_refs.append({'value':r['supremum'],'oracle':oracle,'lag':lo,'relative_error':relative})
    custom={'strategy':'open','payoff':None,'delay':None,'announcement':None,'attainment':'not_attained','status':'custom_limit','supremum':-1.,'supremum_delay':-5.}
    own=ResearchKernel(ModelCapabilities('open','1',False,False),lambda *a:0.,lambda *a:None,lambda *a:None,lambda *a:dict(custom),lambda p,s,b,r,v:b=={'open':True})
    check('A05_model_owns_semantics',optimize_research(own,{},'open',{'open':True})['supremum_delay']==-5.)
    reject('A05_literal_true',lambda:optimize_research(replace(kernel,validate_solution=lambda *a:np.bool_(True)),p,'DL',b,.15))
    write_json(out/'research_metadata.json',{'mutations':research_rows,'supremum_references':supremum_refs})
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'typed_payoff_dtypes':len(datasets),'json_cli_rejections':cli_rejected,
      'array_underflow_rejections':sum(x['rejected'] for x in array_rows),'fraction_demand_cases':fraction_cases,'independent_stock_values':reference_values,
      'max_stock_absolute_error':maximum_stock_error,'independent_grid_values':grid_values,'max_grid_absolute_error':maximum_grid_error,
      'default_metadata_mutations':len(mutations),'independent_supremum_values':len(supremum_refs),
      'scope':'Independent Decimal ranking, lexical values, piecewise stocks, discounted integrals and default-envelope references plus input/CLI controls. Local host has wider longdouble. Callback/metadata checks are not arbitrary-model optimality proofs.'}
    write_json(out/'v0130_checks.json',checks);write_json(out/'v0130_summary.json',summary)
    record_validation(out,Path(__file__),seed=20261018);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('v0.13.0 acceptance failed')

if __name__=='__main__':main()
