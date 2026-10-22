"""Independent uncut discounted integrals and visible finite-run checks."""
from pathlib import Path
from dataclasses import asdict,replace
from decimal import Decimal as D,localcontext,MAX_EMAX,MIN_EMIN
from fractions import Fraction as F
from math import isfinite
import argparse,json,csv,subprocess,sys
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,compare
from entrysignallab.model import _guarded_objective_gap
from entrysignallab.solver import NumericalError
from entrysignallab.workflow import write_json,read_json,verify_manifest,current_source_hashes,record_validation
from entrysignallab import plots
ST=['RF','RL','DF','DL']


def factored_reference(p,precision=200):
    """Independent fixed tau=1 H=T=2 n=0 w=m=s=1 integral."""
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        r,k,C=map(D.from_float,(p.discount,p.learning_rate,p.deployment_cost))
        bracket=(1-(1+r)*(-r).exp())/(2*r*r)-C*(-k).exp()
        return (int(bracket>0)-int(bracket<0)),float(abs(bracket).ln()-r)


def uncut_reference(p,st,tau,delta,precision=200):
    """Separate closed-form positive segment integrals; no exponent cut.

    Corpus rates/lengths are chosen away from small-x cancellation. No model
    integration or production precision helper is used as the reference.
    """
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,H,T,w,m,r,c,C,k,t,d=map(D.from_float,(p.growth,p.network,p.growth_end,p.horizon,
            p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,p.deployment_cost,p.learning_rate,float(tau),float(delta)))
        if st=='RF':a,b=1+n*(s+d)*t,w
        elif st=='DF':a,b=1+n*s*t,w
        elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
        else:a,b=D(1),w*(1+n*s*t)
        def zeroth(left,right):return ((-r*left).exp()-(-r*right).exp())/r if right>left else D(0)
        # Shift each ramp before evaluating: no cancellation of global
        # primitives containing an enormous common constant.
        def ramp(left,right):
            length=right-left
            return (-r*left).exp()*(1-(1+r*length)*(-r*length).exp())/(r*r) if length>0 else D(0)
        follower=s*a/(a+b)*(ramp(t,H)+(H-t)*zeroth(H,T))
        leader=s*(ramp(D(0),t)+t*zeroth(t,T)) if st.endswith('F') else D(0)
        entry=D(0) if st.endswith('F') else t
        return m*(leader+follower)-c*d*d/2-C*(-(k+r)*entry).exp()


def plot_snapshot(directory,rows,export=True):
    original=plots.save_figure;record={}
    def capture(fig,path):
        fig.canvas.draw();series=[]
        for line in fig.axes[0].lines:
            if line.get_label() not in ST:continue
            xy=np.column_stack((line.get_xdata(),line.get_ydata())).astype(float)
            valid=np.isfinite(xy).all(axis=1);marks=line.get_markevery() or []
            edges=[i for i in range(len(xy)-1) if valid[i] and valid[i+1] and np.any(xy[i]!=xy[i+1])]
            covered=set()
            for i in edges:covered.update((tuple(xy[i]),tuple(xy[i+1])))
            if line.get_marker() not in ('None','none','',' '):covered.update(tuple(xy[i]) for i in marks if valid[i])
            expected={tuple(point) for point in xy[valid]}
            series.append({'strategy':line.get_label(),'vertices':[[float(v) if np.isfinite(v) else None for v in point] for point in xy],
                'marker':str(line.get_marker()),'markevery':list(marks),'finite_observations':int(valid.sum()),
                'nonzero_finite_segments':edges,'all_unique_finite_coordinates_visible':expected<=covered})
        record.update(series=series)
        if export:original(fig,path)
        else:plots.plt.close(fig)
    plots.save_figure=capture
    try:plots.sweep_plot(directory,rows,'growth')
    finally:plots.save_figure=original
    return record


def uncut_gap_reference(p,left,right,precision=200):
    """Cancel only analytically shared leader/cost pieces in the oracle."""
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        if left['strategy'][-1]==right['strategy'][-1] and left['delay']==right['delay']:
            s,n,w,t,c=map(F,(p.growth,p.network,p.quality_ratio,left['delay'],p.announcement_cost))
            def share(row):
                d=F(row['announcement']);st=row['strategy']
                if st=='RF':a,b=1+n*(s+d)*t,w
                elif st=='DF':a,b=1+n*s*t,w
                elif st=='RL':a,b=1+n*d*t,w*(1+n*s*t)
                else:a,b=F(1),w*(1+n*s*t)
                return a/(a+b)
            coefficient=F(p.margin_x)*s*(share(left)-share(right))
            cost=c*(F(left['announcement'])**2-F(right['announcement'])**2)/2
            r,H,T,t=map(D.from_float,(p.discount,p.growth_end,p.horizon,float(left['delay'])))
            length=H-t
            mass=(-r*t).exp()*(1-(1+r*length)*(-r*length).exp())/(r*r)
            mass+=(H-t)*(((-r*H).exp()-(-r*T).exp())/r)
            convert=lambda x:D(x.numerator)/D(x.denominator)
            return convert(coefficient)*mass-convert(cost)
        values=[uncut_reference(p,row['strategy'],row['delay'],row['announcement'],precision) for row in (left,right)]
        return values[0]-values[1]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];cases=[];figures=[];cli=[]
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    frozen=read_json(root/'tests/data/v0190_A13_boundary_corpus.json')
    check('frozen_corpus_identity',len(frozen)==60 and sum(r['wrong_preference'] for r in frozen)==15 and sum(r['status']=='controlled_refusal' for r in frozen)==24)
    bounds=DecisionBounds(delay_lower=1,delay_upper=1,announcement_upper=0)
    for i,row in enumerate(frozen):
        p=ModelParams(**row['params']);a=factored_reference(p,200);b=factored_reference(p,400)
        check('reference_stable_'+str(i),a==b)
        report=compare(p,bounds,0,tie_tolerance=0);diag=report['outside_option_gap_diagnostic']
        expected=['RL','DL'] if a[0]>0 else ['no_entry']
        check('frozen_sign_'+str(i),diag['sign']==a[0])
        check('frozen_preference_'+str(i),report['preferred_with_outside_option']==expected)
        check('frozen_log_'+str(i),abs(diag['log_abs']-a[1])<1e-9)
        check('frozen_underflow_'+str(i),diag['value']==0 and diag['representation']=='underflow')
        cases.append({'case':'frozen_'+str(i),'params':asdict(p),'reference_sign':a[0],'reference_log_abs':a[1],
                      'expected_preference':expected,'actual_preference':report['preferred_with_outside_option'],'diagnostic':diag})
    named=ModelParams(growth=1,network=0,growth_end=2,horizon=2,margin_x=1,discount=99999,learning_rate=2,deployment_cost=1e20)
    for tol in (0.,float.fromhex('0x0.0000000000001p-1022'),1e-8):
        report=compare(named,bounds,0,tie_tolerance=tol);diag=report['outside_option_gap_diagnostic']
        check('tolerance_preference_'+str(tol),report['preferred_with_outside_option']==(['no_entry'] if tol==0 else ['RL','DL','no_entry']))
        check('tolerance_keeps_negative_sign_'+str(tol),diag['sign']==-1)
    # All four scenarios and both objective directions, independently evaluated
    # before comparing. Rates large enough to enter the new factored branch.
    general=0
    for rate in (99999.,100001.,120000.):
        for monetary in (1e-80,1.,1e80):
            p=ModelParams(growth=1.25,network=.7,growth_end=2,horizon=3,quality_ratio=1.3,
                margin_x=monetary,discount=rate,deployment_cost=2*monetary,learning_rate=3.)
            controls=[{'strategy':st,'delay':1.,'announcement':.4 if st.startswith('R') else 0.} for st in ST]
            for i in range(4):
                for j in range(4):
                    if i==j:continue
                    with localcontext() as ctx:
                        ctx.prec=400
                        gap=uncut_gap_reference(p,controls[i],controls[j],400);sgn=int(gap>0)-int(gap<0)
                        log_ref=float(abs(gap).ln()) if gap else None
                    lowgap=uncut_gap_reference(p,controls[i],controls[j],200)
                    check('general_reference_sign_'+str(general),(int(lowgap>0)-int(lowgap<0))==sgn)
                    actual=_guarded_objective_gap(p,controls[i],controls[j],tie_tolerance=0)
                    check('general_sign_'+str(general),actual['sign']==sgn)
                    check('general_tolerance_'+str(general),actual['tolerance_relation']==sgn)
                    check('general_log_'+str(general),actual['log_abs']==log_ref or abs(actual['log_abs']-log_ref)<1e-9)
                    general+=1
    huge=ModelParams(growth=0,network=0,margin_x=0,deployment_cost=1,discount=1e308,growth_end=1,horizon=1)
    report=compare(huge,bounds,0,tie_tolerance=0)
    check('old_refusal_now_resolved',report['preferred_with_outside_option']==['no_entry'] and report['outside_option_gap_diagnostic']['sign']==-1)
    check('huge_finite_log',report['outside_option_gap_diagnostic']['log_abs']==-1e308)
    unsupported=replace(huge,growth_end=1e308,horizon=1e308)
    bigbounds=replace(bounds,delay_lower=1e308,delay_upper=1e308)
    try:compare(unsupported,bigbounds,0,tie_tolerance=0);refused=False
    except NumericalError as e:refused='logarithmic magnitude' in str(e)
    check('unrepresentable_log_refused',refused)
    # Tail omission must prevent a decision when the retained sum is too small.
    # This helper stress case deliberately exceeds the model-input coefficient
    # domain; it tests the numerical guard, not model support for such inputs.
    from entrysignallab.model import _scaled_objective_gap
    try:_scaled_objective_gap({None:F(1,10**43440),('exp',F(100001)):-F(1)},F(0),0);tail_refused=False
    except ValueError as e:tail_refused='comparison unresolved' in str(e)
    check('omitted_tail_cannot_be_silently_zero',tail_refused)

    variants={
        'duplicate':[(4.,1.),(4.,1.)],
        'isolated':[(1.,1.),(2.,None),(3.,1.)],
        'mixed':[(1.,1.),(2.,2.),(3.,None),(4.,3.)],
        'duplicate_with_gap':[(1.,1.),(1.,1.),(2.,None),(3.,2.),(3.,2.)],
        'singleton':[(4.,1.)],
        'connected':[(1.,1.),(2.,2.),(3.,3.)],
        'all_null':[(1.,None),(2.,None)],
        'empty':[],
        'repeated_then_connected':[(1.,1.),(1.,1.),(2.,2.)],
        'negative_isolated':[(1.,-1.),(2.,None),(3.,0.)],
    }
    for name,points in variants.items():
        rows=[{'strategy':st,'growth':x,'payoff':y,'batch_status':'numerical_error' if y is None else 'ok'} for st in ST for x,y in points]
        folder=out/'figures'/name;folder.mkdir(parents=True)
        snap=plot_snapshot(folder,rows);figures.append({'case':name,**snap})
        for series in snap['series']:
            check(name+'_'+series['strategy']+'_visibility',series['all_unique_finite_coordinates_visible'])
            expected=[[x,y] for x,y in sorted(points)]
            check(name+'_'+series['strategy']+'_vertices',series['vertices']==expected)
        check(name+'_four_strategy_objects',len(snap['series'])==4)
        for suffix in ['png','pdf','svg']:check(name+'_'+suffix,(folder/('sensitivity.'+suffix)).stat().st_size>0)
    def invoke(name,command,config,expected_exit=0):
        path=out/'configs'/(name+'.json');path.parent.mkdir(exist_ok=True);write_json(path,config)
        destination=out/'cli'/name
        argv=[sys.executable,'-m','entrysignallab.cli',command,'--config',str(path),'--out',str(destination)]
        proc=subprocess.run(argv,capture_output=True,text=True)
        check(name+'_exit',proc.returncode==expected_exit,proc.stderr)
        if proc.returncode!=expected_exit:raise ValueError(name+': '+proc.stderr)
        item={'case':name,'argv':argv,'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr}
        if expected_exit:
            check(name+'_no_output',not destination.exists());check(name+'_no_traceback','Traceback' not in proc.stderr)
        else:
            receipt=verify_manifest(destination,current_source_hashes());item['receipt']=receipt;check(name+'_binding',receipt['valid'])
        cli.append(item);return destination
    cfg={'params':asdict(named),'bounds':asdict(bounds),'rival_delay':0,'comparison':{'tie_tolerance':0}}
    folder=invoke('negative','optimize',cfg)
    check('cli_negative_preference',read_json(folder/'comparison.json')['preferred_with_outside_option']==['no_entry'])
    folder=invoke('positive','optimize',{**cfg,'params':asdict(replace(named,deployment_cost=.01,learning_rate=20))})
    check('cli_positive_preference',read_json(folder/'comparison.json')['preferred_with_outside_option']==['RL','DL'])
    folder=invoke('default_tolerance','optimize',{**cfg,'comparison':{'tie_tolerance':1e-8}})
    check('cli_default_tie',read_json(folder/'comparison.json')['preferred_with_outside_option']==['RL','DL','no_entry'])
    for workers in [1,2]:
        folder=invoke('sweep_'+str(workers),'sweep',{**cfg,'axes':{'deployment_cost':[1e20,1e20]},'batch':{'workers':workers}})
        with (folder/'sweep.csv').open() as f:rows=list(csv.DictReader(f))
        check('cli_sweep_'+str(workers)+'_all_cases',len(rows)==8 and all(r['outside_option_preferred']=='no_entry' and r['outside_option_gap_sign']=='-1' for r in rows))
    folder=invoke('uncertainty','uncertainty',{**cfg,'uncertainty':{'samples':2,'ranges':{'deployment_cost':[1e20,1e20]}}})
    check('cli_uncertainty_counts',read_json(folder/'uncertainty_summary.json')['outside_option_summary']['non_entry_preferred']==2)
    duplicate={'params':{'growth':4,'network':0,'growth_end':1,'horizon':1,'margin_x':1,'margin_y':1},'bounds':{'delay_upper':0,'announcement_upper':0},'rival_delay':0,'axes':{'growth':[4,4]}}
    folder=invoke('duplicate','sweep',duplicate)
    with (folder/'sweep.csv').open() as f:rows=list(csv.DictReader(f))
    check('duplicate_csv_retained',len(rows)==8 and all(r['payoff']=='1.0' for r in rows))
    rows=[{**r,'growth':float(r['growth']),'payoff':float(r['payoff'])} for r in rows]
    snap=plot_snapshot(out/'figures/duplicate',rows,False)
    check('real_duplicate_visible',all(r['all_unique_finite_coordinates_visible'] for r in snap['series']))
    old={'params':asdict(huge),'bounds':asdict(bounds),'rival_delay':0,'comparison':{'tie_tolerance':0}}
    folder=invoke('old_refusal_resolved','optimize',old)
    check('cli_old_refusal_resolved',read_json(folder/'comparison.json')['preferred_with_outside_option']==['no_entry'])
    unsupported_cfg={'params':asdict(unsupported),'bounds':asdict(bigbounds),'rival_delay':0}
    invoke('log_range_refusal','optimize',unsupported_cfg,2)
    folder=invoke('log_range_record','uncertainty',{**unsupported_cfg,'on_error':'record','uncertainty':{'samples':2,'ranges':{'quality_ratio':[1.,1.]}}})
    check('cli_recorded_errors',read_json(folder/'uncertainty_summary.json')['outside_option_summary']['numerical_error']==2)
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'frozen_boundary_cases':len(frozen),
        'repaired_wrong_preferences':15,'previously_refused_cases_resolved':24,'general_pair_comparisons':general,
        'figure_cases':len(figures),'exported_figure_files':3*len(figures),'CLI_processes':len(cli),
        'scope':'Independent uncut 200/400-digit event integrals and factored signs at recorded controls, finite-run artist/export checks, actual installed Linux CLI. Adaptive arithmetic/tail guards are not interval or global certificates.'}
    write_json(out/'comparison_cases.json',cases);write_json(out/'figure_checks.json',figures)
    write_json(out/'CLI_checks.json',cli);write_json(out/'checks.json',checks);write_json(out/'v0200_summary.json',summary)
    record_validation(out,Path(__file__),20261019);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit(2)


if __name__=='__main__':main()
