"""Independent original-input comparison references and degenerate figure acceptance."""
from pathlib import Path
from dataclasses import asdict,replace
from fractions import Fraction as F
from decimal import Decimal as D,localcontext
from math import nextafter,inf,isfinite
import argparse,json,subprocess,sys
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,compare,optimize
from entrysignallab.solver import compare_results,NumericalError
from entrysignallab.units import rescale_experiment
from entrysignallab import plots
from entrysignallab.workflow import write_json,read_json,current_source_hashes,verify_manifest,record_validation
from validate_v0180 import rational_reference,primitive_reference
ST=['RF','RL','DF','DL']


def simultaneous_reference(p):
    assert p.network==p.discount==p.learning_rate==0
    s,h,T,w,m,C=map(F,(p.growth,p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.deployment_cost))
    return m*s*(h*h/2+h*(T-h))/(1+w)-C


def expected(values,outside,tolerance):
    best=max(values);labels=[st for st,v in zip(ST,values) if best-v<=tolerance]
    gap=best-outside
    return labels,labels if gap>tolerance else ['no_entry'] if gap < -tolerance else labels+['no_entry'],gap


def plot_snapshot(call,export=True):
    old=plots.save_figure;records=[]
    def capture(fig,path):
        ax=fig.axes[0];fig.canvas.draw();lines=[]
        for line in ax.lines:
            xy=list(zip(map(float,line.get_xdata()),map(float,line.get_ydata())))
            finite=[point for point in xy if all(isfinite(x) for x in point)]
            lines.append({'finite_coordinates':finite,'marker':str(line.get_marker()),
                'total_vertices':len(xy),'label':line.get_label()})
        collections=[{'offsets':np.asarray(c.get_offsets()).tolist(),'paths':len(c.get_paths())} for c in ax.collections]
        records.append({'stem':Path(path).name,'lines':lines,'collections':collections,'title':ax.get_title()})
        if export:old(fig,path)
        else:plots.plt.close(fig)
    plots.save_figure=capture
    try:call()
    finally:plots.save_figure=old
    return records[0]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];cases=[];cli=[];figures=[]
    def check(name,passed,detail=None):checks.append({'name':name,'pass':bool(passed),'detail':detail})
    b=DecisionBounds(delay_lower=0,delay_upper=0,announcement_upper=2)
    frozen=read_json(root/'tests/data/v0180_comparison_observations.json')
    check('frozen_four_defects',len(frozen)==4 and all(x['defect_reproduced'] for x in frozen))
    def validate_case(name,p,b,outside=0.,tol=1e-8,values=None,rival=0.):
        r=compare(p,b,rival,outside_option=outside,tie_tolerance=tol)
        if values is None:values=[simultaneous_reference(p)]*4
        exp_labels,exp_preference,exp_gap=expected(values,F(outside),F(tol))
        check(name+'_labels',r['co_best']==exp_labels)
        check(name+'_preference',r['preferred_with_outside_option']==exp_preference)
        diag=r['outside_option_gap_diagnostic']
        if diag['decision_basis']!='rounded_payoff_difference':
            check(name+'_gap',diag['value']==float(exp_gap))
            check(name+'_sign',diag['sign']==((exp_gap>0)-(exp_gap<0)))
            check(name+'_relation',diag['tolerance_relation']==(1 if exp_gap>F(tol) else -1 if exp_gap < -F(tol) else 0))
        cases.append({'case':name,'params':asdict(p),'outside_option':outside,'tie_tolerance':tol,
            'reference_gap':float(exp_gap),'reference_gap_exact':str(exp_gap),
            'expected_preference':exp_preference,'actual_preference':r['preferred_with_outside_option'],
            'expected_co_best':exp_labels,'actual_co_best':r['co_best'],'actual_gap':r['outside_option_gap'],
            'gap_diagnostic':diag,'reference_scope':'recorded controls, no global optimum certificate'})
        return r
    for row in frozen:
        p=ModelParams(**row['params']);outside=row['outside_option']
        validate_case(row['case'],p,b,outside)
        q=replace(p,deployment_cost=outside)
        check(row['case']+'_cost_identity',simultaneous_reference(q)==simultaneous_reference(p)-F(outside))
        validate_case(row['case']+'_cost_translation',q,b)
    p=ModelParams(**frozen[0]['params']);outside=frozen[0]['outside_option']
    for a,c in [(2.,1.),(1.,4.)]:
        q,d,rival=rescale_experiment(p,b,0,time_factor=a,consumer_factor=c)
        check('units_exact_'+str((a,c)),rival==0 and simultaneous_reference(q)==simultaneous_reference(p))
        validate_case('units_'+str((a,c)),q,d,outside)
    corpus=read_json(root/'tests/data/v0180_comparison_corpus.json')
    for i,row in enumerate(corpus):validate_case('boundary_'+str(i),ModelParams(**row['params']),b,row['outside_option'])
    for scale in [1.,10.,1e3,1e6,1e8,1e9,1e10,1e12,1e14,1e16,1e30,1e100]:
        p=ModelParams(growth=4*scale,network=0,growth_end=1,horizon=1,margin_x=1,margin_y=1)
        for outside in [scale/2,scale*2]:validate_case('far_'+str(scale)+'_'+str(outside),p,b,outside)
    for scale in [1e8,1e12,1e14]:
        p=ModelParams(growth=4*scale,network=0,growth_end=1,horizon=1,margin_x=1,margin_y=1)
        for tol in [nextafter(scale,0),scale,nextafter(scale,inf)]:validate_case('tolerance_boundary_'+str((scale,tol)),p,b,0,tol)
    # Scenario ordering at recorded solver controls, using the independently
    # transcribed rational reference retained from the preceding validator.
    rational_cases=0
    for scale in [1e8,1e12,1e14,1e30,1e100]:
        for network_factor in [0.,.1,1.,10.]:
            for cA in [0.,.01]:
                p=ModelParams(growth=4*scale,network=network_factor/(4*scale),growth_end=1,horizon=1,margin_x=1,margin_y=1,announcement_cost=cA)
                bb=DecisionBounds(delay_lower=.125,delay_upper=.125,announcement_upper=2)
                results=[optimize(p,st,bb,.125) for st in ST]
                vals=[rational_reference(p,x['strategy'],x['delay'],x['announcement']) for x in results]
                validate_case('rational_scenarios_'+str(rational_cases),p,bb,float(max(vals)),values=vals,rival=.125)
                rational_cases+=1
    # Independent global antiderivatives, stabilized at 800 and 1600 digits.
    decimal_cases=0
    for rate,learning in [(.1,0.),(.5,.7),(2.,1.),(1e-100,.7)]:
        p=ModelParams(growth=4e14,network=1e-15,growth_end=1,horizon=1,margin_x=1,margin_y=1,discount=rate,learning_rate=learning,deployment_cost=1e13,announcement_cost=.01)
        bb=DecisionBounds(delay_lower=.125,delay_upper=.125,announcement_upper=2)
        results=[optimize(p,st,bb,0) for st in ST]
        vals=[]
        for x in results:
            one=primitive_reference(p,x['strategy'],x['delay'],x['announcement'],800)[0]
            two=primitive_reference(p,x['strategy'],x['delay'],x['announcement'],1600)[0]
            check('decimal_reference_stability_'+str((rate,x['strategy'])),float(one)==float(two))
            vals.append(two)
        nominal=float(max(vals))
        for outside in [nextafter(nominal,0),nominal,nextafter(nominal,inf)]:
            # Decimal arithmetic for the independent difference must retain its
            # original precision rather than using the process default 28.
            with localcontext() as ctx:
                ctx.prec=1600
                r=compare(p,bb,0,outside_option=outside)
                labels,pref,gap=expected(vals,D.from_float(outside),D.from_float(1e-8))
                check('decimal_preference_'+str(decimal_cases),r['preferred_with_outside_option']==pref)
                check('decimal_labels_'+str(decimal_cases),r['co_best']==labels)
                check('decimal_gap_'+str(decimal_cases),r['outside_option_gap']==float(gap))
                cases.append({'case':'decimal_'+str(decimal_cases),'reference_gap':float(gap),
                    'actual_gap':r['outside_option_gap'],'expected_preference':pref,'actual_preference':r['preferred_with_outside_option'],
                    'gap_diagnostic':r['outside_option_gap_diagnostic']})
            decimal_cases+=1
    tiny=float.fromhex('0x0.0000000000001p-1022')
    p=ModelParams(growth=2*tiny,network=0,growth_end=1,horizon=1,margin_x=1,margin_y=1)
    r=validate_case('genuine_gap_underflow',p,b,0.,0.)
    check('underflow_representation',r['outside_option_gap_diagnostic']['representation']=='underflow')
    check('underflow_sign_preserved',r['outside_option_gap']==0 and r['outside_option_gap_diagnostic']['sign']==1)
    p=ModelParams(growth=0,network=0,margin_x=0,deployment_cost=1,discount=1e308,growth_end=1e308,horizon=1e308)
    bb=DecisionBounds(delay_lower=1e308,delay_upper=1e308,announcement_upper=0)
    try:compare(p,bb,0);controlled=False
    except NumericalError as error:controlled='comparison unresolved' in str(error)
    check('unresolved_original_input_comparison_refused',controlled)
    custom=[{'strategy':st,'payoff':1.} for st in ST]
    check('external_results_unchanged',compare_results(custom,outside_option=1.)['preferred_with_outside_option']==ST+['no_entry'])
    r=compare(ModelParams(),DecisionBounds(announcement_upper=None))
    check('null_ranking_still_withheld',not r['all_rankable'] and r['co_best']==[] and r['preferred_with_outside_option']==[])
    # Real exports and independent coordinate/marker inspection.
    p=ModelParams(growth=4,network=0,growth_end=1,horizon=1,margin_x=1,margin_y=1)
    for name,bb in [('surface_point',replace(b,announcement_upper=0)),
        ('surface_point_delayed',DecisionBounds(delay_lower=.125,delay_upper=.125,announcement_upper=0)),
        ('surface_intensity_slice',b),('surface_delay_slice',DecisionBounds(delay_upper=1,announcement_upper=0)),
        ('surface_full',DecisionBounds(delay_upper=1,announcement_upper=2))]:
        folder=out/'figures'/name;folder.mkdir(parents=True)
        snap=plot_snapshot(lambda:plots.profit_surface(folder,p,bb));figures.append({'case':name,**snap})
        if name.startswith('surface_point'):
            coords=snap['collections'][0]['offsets'];ref=float(rational_reference(p,'RL',bb.delay_lower,0))
            check(name+'_coordinate',coords==[[0.,ref]])
            check(name+'_visible_marker',snap['collections'][0]['paths']>0 and 'point' in snap['title'])
        elif 'slice' in name:check(name+'_line',len(snap['lines'][0]['finite_coordinates'])==81)
        else:check(name+'_contour',bool(snap['collections']))
    rows=[{'strategy':st,'growth':4.,'payoff':1.,'batch_status':'ok'} for st in ST]
    variants={'sweep_point':rows,'sweep_two_points':rows+[{**x,'growth':8.,'payoff':2.} for x in rows],
        'sweep_one_finite':[{**x,'payoff':None} for x in rows]+[{**x,'growth':8.} for x in rows],
        'sweep_empty':[{**x,'payoff':None} for x in rows]}
    for name,data in variants.items():
        folder=out/'figures'/name;folder.mkdir(parents=True)
        snap=plot_snapshot(lambda:plots.sweep_plot(folder,data,'growth'));figures.append({'case':name,**snap})
        lines=snap['lines'][:4]
        if name in ['sweep_point','sweep_one_finite']:
            check(name+'_one_valid',all(len(x['finite_coordinates'])==1 for x in lines))
            check(name+'_visible_markers',all(x['marker']!='None' for x in lines))
            check(name+'_distinguished_markers',len(set(x['marker'] for x in lines))==4)
        elif name=='sweep_empty':check(name+'_no_fabricated_points',all(not x['finite_coordinates'] for x in lines))
        else:check(name+'_two_valid',all(len(x['finite_coordinates'])==2 for x in lines))
    for path in (out/'figures').rglob('*'):
        if path.is_file():check('export_'+str(path.relative_to(out)),path.stat().st_size>0)
    # Installed-package CLI, including error-record behavior and source checks.
    def invoke(name,command,config,extra=None,exit_code=0):
        config_path=out/'configs'/(name+'.json');config_path.parent.mkdir(exist_ok=True);write_json(config_path,config)
        folder=out/'cli'/name
        argv=[sys.executable,'-m','entrysignallab.cli',command,'--config',str(config_path)]
        argv+=extra if command=='evaluate' else ['--out',str(folder)]
        proc=subprocess.run(argv,capture_output=True,text=True)
        check(name+'_exit',proc.returncode==exit_code,proc.stderr)
        write_json(out/(name+'_process.json'),{'argv':argv,'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
        if proc.returncode!=exit_code:raise ValueError(name+': '+proc.stderr)
        if exit_code:
            check(name+'_no_output',not folder.exists());check(name+'_controlled','Traceback' not in proc.stderr)
        elif command!='evaluate':
            receipt=verify_manifest(folder,current_source_hashes());write_json(out/(name+'_receipt.json'),receipt);check(name+'_source_binding',receipt['valid'])
            if (folder/'comparison.json').exists():
                result=read_json(folder/'comparison.json');check(name+'_gap',result['outside_option_gap']==config.get('expected_gap',.25) if 'expected_gap' in config else result['outside_option_gap']==(.25 if name!='cli_surface_point' else 1.))
            if command=='sweep':
                import csv
                with (folder/'sweep.csv').open() as f:records=list(csv.DictReader(f))
                check(name+'_csv',all(x['outside_option_preferred']=='RF|RL|DF|DL' and float(x['outside_option_gap'])==.25 and x['outside_option_gap_basis']=='exact_original_input_difference' for x in records))
            if command=='uncertainty':
                u=read_json(folder/'uncertainty_summary.json')['outside_option_summary']
                check(name+'_frequency',u['numerical_error']==2 if name=='cli_unresolved_record' else u['entry_preferred']==4)
        cli.append({'case':name,'command':command,'exit':proc.returncode});return folder
    p=ModelParams(**frozen[0]['params']);config={'params':asdict(p),'bounds':asdict(b),'rival_delay':0,'comparison':{'outside_option':frozen[0]['outside_option']}}
    invoke('cli_evaluate','evaluate',config,['--strategy','DL','--delay','0'])
    invoke('cli_optimize','optimize',config)
    folder=invoke('cli_reproduce','reproduce',config)
    check('html_discloses_model_gap','Gap to the non-entry reference: 0.25' in (folder/'report.html').read_text())
    for workers in [1,2]:invoke('cli_sweep_'+str(workers),'sweep',{**config,'axes':{'quality_ratio':[1.]},'batch':{'workers':workers}})
    invoke('cli_uncertainty','uncertainty',{**config,'uncertainty':{'samples':4,'ranges':{'quality_ratio':[1.,1.]}}})
    point={'params':{'growth':4,'network':0,'growth_end':1,'horizon':1,'margin_x':1,'margin_y':1},'bounds':{'delay_upper':0,'announcement_upper':0},'rival_delay':0}
    invoke('cli_surface_point','reproduce',point)
    unresolved={'params':{'growth':0,'network':0,'margin_x':0,'deployment_cost':1,'discount':1e308,'growth_end':1e308,'horizon':1e308},'bounds':{'delay_lower':1e308,'delay_upper':1e308,'announcement_upper':0},'rival_delay':0}
    invoke('cli_unresolved','optimize',unresolved,exit_code=2)
    invoke('cli_unresolved_record','uncertainty',{**unresolved,'on_error':'record','uncertainty':{'samples':2,'ranges':{'quality_ratio':[1.,1.]}}})
    summary={'all_pass':all(x['pass'] for x in checks),'checks':len(checks),'frozen_wrong_preferences':len(frozen),
        'boundary_cases':len(corpus),'far_controls':24,'cost_translations':4,'exact_unit_changes':2,
        'rational_scenario_cases':rational_cases,'decimal_scenario_cases':decimal_cases,
        'comparison_cases':len(cases),'figure_cases':len(figures),'exported_figure_files':27,
        'CLI_processes':len(cli),'controlled_comparison_refusals':2,
        'scope':'Exact original-input simultaneous-entry and rational scenario references, independent global Decimal antiderivatives at recorded controls, finite plot cases and installed Linux CLI. No universal rounding, interval, global or empirical certificate.'}
    write_json(out/'comparison_checks.json',cases);write_json(out/'figure_checks.json',figures);write_json(out/'CLI_checks.json',cli);write_json(out/'checks.json',checks);write_json(out/'v0190_summary.json',summary)
    print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('v0.19.0 acceptance failed')
    record_validation(out,Path(__file__),20261019)

if __name__=='__main__':main()
