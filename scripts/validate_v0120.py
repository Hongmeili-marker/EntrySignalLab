"""Independent acceptance for all five v0.11 findings; real workers and Decimal."""
from pathlib import Path
from dataclasses import replace,asdict
from fractions import Fraction
from decimal import Decimal,localcontext,MAX_EMAX,MIN_EMIN
from statistics import NormalDist
import argparse,hashlib,json,math,sqlite3,sys
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,compare,payoff,optimize,rescale_experiment
from entrysignallab.model import finite_number
from entrysignallab.batch import run_batch
from entrysignallab.workflow import prepare_sweep,uncertainty,write_json,read_json,record_validation
from entrysignallab.research import ResearchKernel,ModelCapabilities,default_research_kernel,optimize_research
from entrysignallab.solver import compare_results
from entrysignallab.sampling import wilson_interval

def stored(directory):
    with sqlite3.connect(directory/'checkpoint.sqlite') as db:
        return dict(db.execute('SELECT case_index,payload FROM cases ORDER BY case_index'))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True,type=Path);out=ap.parse_args().out.resolve()
    if out.exists():raise SystemExit('Choose a fresh directory')
    out.mkdir(parents=True);p=ModelParams();b=DecisionBounds(scouting_points=3,announcement_upper=0);checks=[];batch_rows=[]
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    def rejects(name,call):
        try:call();denied=False;error=None
        except ValueError as e:denied=True;error=str(e)
        check(name,denied,error)
    sequences={'duplicate_middle':[0,0,1],'duplicate_tail':[0,1,1],'negative':[-1,0,1],
               'boolean':[False,1],'float':[0.,1],'overrun':[0,1,2],'missing':[0],'backward':[0,1,0]}
    for workers in [1,2]:
        for resume in [False,True]:
            for name,order in sequences.items():
                m,t=prepare_sweep(p,b,.15,{'growth':[.1,.11]},batch={'workers':workers,'checkpoint_every':1});tasks=list(t());directory=out/f'{name}_w{workers}_r{resume}'
                if resume:
                    def stop(n):
                        if n==1:raise RuntimeError('intentional interruption')
                    try:run_batch(directory,p,b,.15,m,t,{},progress_callback=stop)
                    except RuntimeError:pass
                before=stored(directory) if resume else {}
                seq=[{**tasks[0 if not isinstance(i,int) or isinstance(i,bool) or not 0<=i<2 else i],'case_index':i} for i in order]
                try:run_batch(directory,p,b,.15,m,lambda:iter(seq),{},resume=resume);denied=False;error=None
                except ValueError as e:denied=True;error=str(e)
                # A full committed prefix may validly omit its missing suffix;
                # 'missing' still lacks case 1 and must fail in either mode.
                progress=read_json(directory/'batch_progress.json');after=stored(directory)
                unchanged=all(after.get(k)==v for k,v in before.items())
                check('A01_'+name+f'_w{workers}_r{resume}',denied and progress['state']!='completed' and unchanged)
                batch_rows.append({'name':name,'workers':workers,'resume':resume,'indices':order,'denied':denied,'error':error,'state':progress['state'],'committed_prefix_retained':unchanged})
    for workers in [1,2]:
        for mode in ['new','full_resume','suffix_resume','complete_empty']:
            m,t=prepare_sweep(p,b,.15,{'growth':[.1,.11]},batch={'workers':workers,'checkpoint_every':1});directory=out/f'valid_w{workers}_{mode}'
            if mode!='new':
                if mode=='complete_empty':run_batch(directory,p,b,.15,m,t,{})
                else:
                    def stop(n):
                        if n==1:raise RuntimeError('intentional interruption')
                    try:run_batch(directory,p,b,.15,m,t,{},progress_callback=stop)
                    except RuntimeError:pass
            factory=(lambda:iter([])) if mode=='complete_empty' else (lambda:iter(list(t())[1:])) if mode=='suffix_resume' else t
            v=run_batch(directory,p,b,.15,m,factory,{},resume=mode!='new')
            check('A01_valid_'+str(workers)+'_'+mode,v['completed_cases']==2 and v['batch_execution']['processed_cases']==2)
    write_json(out/'batch_sequence_observations.json',batch_rows)
    type_rows=[]
    for dtype in [np.float32,np.float64]:
        for field in ['payoff_atol','payoff_rtol']:
            bb=replace(b,**{field:dtype(1e-8)});v=compare(p,bb,.15);u=uncertainty(p,bb,.15,{'growth':[.1,.11]},n=2)
            serializable=True
            try:json.dumps({'bounds':asdict(bb),'comparison':v,'uncertainty':u},allow_nan=False)
            except TypeError:serializable=False
            native=all(type(x['local_quality_passed']) is bool for x in v['results'])
            check('A02_types_'+dtype.__name__+'_'+field,type(getattr(bb,field)) is float and native and serializable and v['local_quality_status']=='pass' and u['quality_status_counts']['pass']==2)
            type_rows.append({'dtype':dtype.__name__,'field':field,'normalized_type':type(getattr(bb,field)).__name__,'local_checks_python_bool':native,'serializable':serializable,'quality_counts':u['quality_status_counts']})
            for workers in [1,2]:
                m,t=prepare_sweep(p,bb,.15,{'growth':[.1,.11]},batch={'workers':workers,'checkpoint_every':1});directory=out/f'numpy_{dtype.__name__}_{field}_{workers}'
                def stop(n):
                    if n==1:raise RuntimeError('intentional interruption')
                try:run_batch(directory,p,bb,.15,m,t,{},progress_callback=stop)
                except RuntimeError:pass
                rr=run_batch(directory,p,bb,.15,m,t,{},resume=True)
                check('A02_resumed_'+dtype.__name__+'_'+field+'_'+str(workers),rr['quality_status_counts']=={'pass':2,'fail':0,'not_assessed':0})
    for flag,expected in [(np.bool_(True),'pass'),(np.bool_(False),'fail'),('true','not_assessed'),(None,'not_assessed')]:
        v=compare_results([{'strategy':s,'payoff':1.,'local_quality_passed':flag} for s in ['RF','RL','DF','DL']])
        check('A02_explicit_boolean_'+str(flag),v['local_quality_status']==expected and bool(json.dumps(v)))
    write_json(out/'normalized_type_observations.json',type_rows)
    tiny=Fraction(1,10**500)
    for name,call in [('fraction',lambda:finite_number(tiny,'positive',positive=True)),
        ('horizon',lambda:ModelParams(growth_end=0,horizon=tiny)),('quality',lambda:ModelParams(quality_ratio=tiny)),
        ('growth',lambda:ModelParams(growth=tiny)),('huge_integer',lambda:ModelParams(growth=10**10000)),
        ('bound',lambda:replace(b,tolerance=tiny).validate(p)),('units',lambda:rescale_experiment(p,b,.15,time_factor=tiny)),
        ('genuine_zero',lambda:ModelParams(growth_end=0,horizon=0))]:rejects('A03_'+name,call)
    extended=np.longdouble('1e-500');rejects('A03_longdouble',lambda:ModelParams(growth_end=0,horizon=extended))
    smallest=float(np.nextafter(0.,1.));check('A03_smallest_positive',ModelParams(growth_end=0,horizon=smallest).horizon==smallest)
    check('A03_fraction_control',ModelParams(growth=Fraction(1,10)).growth==.1)
    check('A03_nonnegative_zero',ModelParams(growth=-0.).growth==0.)
    kernel=default_research_kernel()
    def extension(state,payoff_value='actual',controls=True,extra=None,omit=()):
        def solve(p,s,b,r):
            value={'strategy':s,'delay':.1 if controls else None,'announcement':0 if controls else None,'payoff':payoff(p,s,.1) if payoff_value=='actual' else payoff_value}
            if state is not None:value['attainment']=state
            value.update(extra or {})
            for key in omit:value.pop(key,None)
            return value
        return replace(kernel,conditional_solver=solve)
    for state in ['not_attained','unknown_state']:
        rejects('A04_finite_'+state,lambda:optimize_research(extension(state),p,'DL',b,.15))
    for state in ['attained','candidate',None]:
        v=optimize_research(extension(state),p,'DL',b,.15)
        check('A04_valid_'+str(state),v['attainment']==('candidate' if state is None else state) and v['payoff']==payoff(p,'DL',.1))
    for st,bb in [('DL',b),('RF',b),('RF',replace(b,announcement_upper=None))]:
        pp=p if bb.announcement_upper is not None else replace(p,announcement_cost=.01)
        rejects('A04_false_unattained_'+st+'_'+str(bb.announcement_upper),lambda:optimize_research(extension('not_attained',None,False),pp,st,bb,.15))
    for st in ['RF','RL']:
        v=optimize_research(kernel,p,st,replace(b,announcement_upper=None),.15)
        check('A04_real_unattained_'+st,v['attainment']=='not_attained' and v['payoff'] is None and v['delay'] is None)
    rejects('A04_missing_controls',lambda:optimize_research(extension('not_attained',None,False,omit=['delay']),p,'RF',replace(b,announcement_upper=None),.15))
    rejects('A04_conflicting_status',lambda:optimize_research(extension('attained',extra={'status':'no_finite_joint_optimum'}),p,'DL',b,.15))
    rejects('A04_nonfinite_supremum',lambda:optimize_research(extension('candidate',extra={'supremum':float('inf')}),p,'DL',b,.15))
    rejects('A04_numpy_validator_not_literal',lambda:optimize_research(replace(kernel,validate_solution=lambda *a:np.bool_(True)),p,'DL',b,.15))
    toy=ResearchKernel(ModelCapabilities('open-domain-toy','1',False,False),lambda *a:1.,lambda *a:None,lambda *a:None,
        lambda p,s,b,r:{'strategy':s,'delay':None,'announcement':None,'payoff':None,'attainment':'not_attained'},lambda p,s,b,r,v:b=={'open':True})
    check('A04_custom_model_owns_existence',optimize_research(toy,{},'toy',{'open':True})['attainment']=='not_attained')
    quantiles=[]
    for exponent in [309,320,325,400,10000]:
        n=10**exponent
        for label,k in [('zero',0),('one',1),('small',10**5),('audit',10**25),('middle',n//2),('near_full',n-1),('full',n)]:
            for confidence in [.5,.95,float(np.nextafter(1.,0.)),float(np.nextafter(0.,1.))]:
                got=wilson_interval(k,n,confidence)
                with localcontext() as c:
                    c.prec=1200;c.Emax=MAX_EMAX;c.Emin=MIN_EMIN;N=Decimal(n);pp=Decimal(k)/N;z=Decimal.from_float(-NormalDist().inv_cdf((1-confidence)/2));den=1+z*z/N
                    center=(pp+z*z/(2*N))/den;half=z*(pp*(1-pp)/N+z*z/(4*N*N)).sqrt()/den
                    ref=[max(0.,float(center-half)),min(1.,float(center+half))]
                error=max(abs(a-r)/math.ulp(r) for a,r in zip(got,ref))
                quantiles.append({'total_power_of_ten':exponent,'count_recipe':label,'confidence':confidence,'observed':got,'decimal_reference':ref,'max_endpoint_ulp_error':error})
    check('A05_independent_decimal_140',all(x['max_endpoint_ulp_error']<=2 for x in quantiles),{'values':len(quantiles),'max_ulp_error':max(x['max_endpoint_ulp_error'] for x in quantiles)})
    original=wilson_interval(10**25,10**325);check('A05_original_nonzero_width',original[0]<1e-300<original[1],original)
    check('A05_empty',wilson_interval(0,0) is None)
    for dtype,n in [(np.int32,32768),(np.int64,2**31),(np.uint64,2**64-1)]:
        check('A05_numpy_'+dtype.__name__,wilson_interval(dtype(0),dtype(n))==wilson_interval(0,n))
    write_json(out/'wilson_decimal_reference.json',quantiles);write_json(out/'v0120_checks.json',checks)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'batch_sequence_cases':len(batch_rows),
        'wilson_reference_values':len(quantiles),'max_wilson_endpoint_ulp_error':max(x['max_endpoint_ulp_error'] for x in quantiles),
        'scope':'Local Linux installed-wheel execution, real one/two-worker recovery, type/domain/state checks and independent 1200-digit Decimal Wilson arithmetic. No global or empirical certificate.'}
    write_json(out/'v0120_summary.json',summary);record_validation(out,Path(__file__),20261018);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('Audit acceptance failed')

if __name__=='__main__':main()
