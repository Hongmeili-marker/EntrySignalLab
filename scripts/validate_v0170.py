"""Independent acceptance of source identities and numerical figure coordinates."""
from pathlib import Path
from dataclasses import asdict
from fractions import Fraction
from itertools import product
import argparse, json, math, re, subprocess, sys
import numpy as np
from entrysignallab import ModelParams
from entrysignallab.audit import source_audit
from entrysignallab import plots
from entrysignallab.workflow import write_json, read_json, verify_manifest, current_source_hashes, record_validation


def reference_source(s, h):
    """Exact rational source transcription; production integration is not used."""
    S, H = Fraction(s), Fraction(h)
    demand = S*H*(2-H)/16
    printed = -S*H*H/16
    difference = demand-printed
    assert difference == S*H/8 and difference > 0
    return demand, printed, difference


def axis_snapshot(axis):
    """Reconstruct raw positions from rendered labels, exponent and offset."""
    lower, upper = axis.get_view_interval()
    ticks = [(float(x), label.get_text()) for x, label in zip(axis.get_majorticklocs(), axis.get_majorticklabels())
             if lower <= x <= upper and label.get_visible()]
    formatter = axis.get_major_formatter()
    order = int(getattr(formatter, 'orderOfMagnitude', 0))
    offset = float(getattr(formatter, 'offset', 0.))
    values = [x for x, text in ticks]
    step = min((b-a for a,b in zip(values, values[1:]) if b>a), default=1.)
    labels = [text for x,text in ticks]
    checks = []
    decoded = []
    for value, label in ticks:
        match = re.fullmatch(r'\$\\mathdefault\{([^{}]+)\}\$', label)
        numeric = (match.group(1) if match else label).replace('\N{MINUS SIGN}', '-')
        try:
            reconstructed = float(numeric)*10.**order+offset
            passed = math.isfinite(reconstructed) and abs(reconstructed-value) <= max(8*math.ulp(value), abs(step)*1e-9)
        except (ValueError, OverflowError):
            reconstructed = None; passed = False
        decoded.append(reconstructed); checks.append(bool(passed))
    return {'values':values, 'labels':labels, 'decoded_values':decoded,
            'roundtrip_checks':checks, 'roundtrip_pass':bool(checks) and all(checks),
            'distinct_labels':len(set(labels)), 'distinct_values':len(set(values)),
            'labels_distinguish_positions':len(set(labels))==len(set(values)),
            'order_of_magnitude':order, 'offset':offset,
            'offset_text':axis.get_offset_text().get_text(),
            'scale_annotation_present':bool(axis.get_offset_text().get_text()) if order or offset else True}


def plot_snapshot(xs, ys, directory=None):
    """Inspect actual axes; optionally retain all production figure formats."""
    rows=[]
    coordinates=list(product(xs,ys))
    for i,(x,y) in enumerate(coordinates):
        # Include the white unrankable category in every singleton fixture;
        # its outline must keep the actual point visible on a white canvas.
        unrankable=(len(xs)==1 or len(ys)==1) and i==len(coordinates)-1
        rows.extend({'growth':float(x), 'network':float(y), 'strategy':st,
                     'co_best':'' if unrankable else 'RF',
                     'all_rankable':not unrankable, 'batch_status':'ok'}
                    for st in ['RF','RL','DF','DL'])
    captured={}; original=plots.save_figure
    def capture(fig, path):
        try:
            fig.canvas.draw()
            captured['x']=axis_snapshot(fig.axes[0].xaxis)
            captured['y']=axis_snapshot(fig.axes[0].yaxis)
            if len(xs)==1 or len(ys)==1:
                artist=fig.axes[0].collections[0]
                expected=np.array([[x,y] for y in ys for x in xs],dtype=float)
                actual=np.asarray(artist.get_offsets(),dtype=float)
                colors=artist.get_facecolors();edges=artist.get_edgecolors()
                captured['sampled_points']={'positions':actual.tolist(),
                    'positions_exact':bool(np.array_equal(actual,expected)),
                    'visible':bool(len(colors)>0 and np.all(colors[:,3]>0) and np.all(artist.get_sizes()>0)
                                   and len(edges)>0 and np.all(edges[:,3]>0) and np.all(artist.get_linewidths()>0))}
            if directory is not None:original(fig,path)
        finally:
            plots.plt.close(fig)
    plots.save_figure=capture
    try:
        if directory is not None:Path(directory).mkdir(parents=True,exist_ok=False)
        plots.regime_plot(Path(directory or '.'),rows,{'growth':list(xs),'network':list(ys)})
    finally:
        plots.save_figure=original
    return captured


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);out=ap.parse_args().out.absolute()
    out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];checks=[];source_records=[];figure_records=[];cli_records=[]
    def check(name,condition,detail=None):checks.append({'name':name,'pass':bool(condition),'detail':detail})
    baseline=read_json(root/'tests/data/v0160_round3_observations.json')
    check('frozen_input_version',baseline['version']=='0.16.0')
    check('frozen_defects',baseline['defect_observations']==12 and baseline['control_observations']==5 and baseline['all_observations_reproduced'])
    # Reuse every source counterexample's exact original binary64 inputs.
    for old in baseline['observations']:
        if old['finding']!='A07' or 'params' not in old['detail']:continue
        p=ModelParams(**old['detail']['params'])
        source_records.append((old['name'],p))
    for s,h in product([.1,1e-5,1e-10,1e-11,1e-20,1e-100,1e100],[.3,.001,1e-100]):
        source_records.append(('wide_'+str(s)+'_'+str(h),ModelParams(growth=s,growth_end=h)))
    source_records.extend([('rounded_printed_zero_'+str(h),ModelParams(growth_end=h)) for h in [1e-170,1e-200,1e-300]])
    source_outputs=[]
    maximum_relative_error=0.
    for name,p in source_records:
        ref,printed,difference=reference_source(p.growth,p.growth_end)
        item=next(x for x in source_audit(p)['checks'] if x['id']=='DF_INTEGRAL_IDENTITY')
        relative_error=abs(item['from_demand']/float(ref)-1)
        maximum_relative_error=max(maximum_relative_error,relative_error)
        check(name+'_analytic_fail',item['pass'] is False)
        check(name+'_basis',item['decision_basis']=='analytic_nonidentity' and item['numerical_values_are_descriptive'] is True)
        printed_reference=float(printed)
        printed_error=abs(item['from_printed_eq15']-printed_reference)
        check(name+'_numeric',relative_error<1e-11 and printed_error<=max(8*math.ulp(printed_reference),1e-13*abs(printed_reference)))
        normalized=float(difference/ref)
        check(name+'_normalized',abs(item['normalized_discrepancy']-normalized)<=4*math.ulp(normalized))
        source_outputs.append({'case':name,'params':asdict(p),'actual':item,'exact_difference':str(difference),
                               'expected_demand':float(ref),'expected_printed':float(printed)})
    for name,params in [('zero_growth',{'growth':0}),('zero_H',{'growth_end':0}),('zero_network',{'network':0}),('changed_discount',{'discount':.1}),('source_range',{'growth':1e-200,'network':1e-200})]:
        try:source_audit(ModelParams(**params));rejected=False
        except ValueError:rejected=True
        check('source_preconditions_'+name,rejected)
    write_json(out/'source_checks.json',source_outputs)
    # Small, ordinary, large, shifted and degenerate axes; check both directions.
    ordinary=[.5,1.,1.5]
    cases=[]
    for scale in [1e-9,1e-4,1e-3,.1,1e3,1e12]:
        values=[scale,2*scale,3*scale]
        cases.extend([('scale_x_'+str(scale),values,ordinary),('scale_y_'+str(scale),ordinary,values)])
    for base,step in [(1e9,.001),(1e12,1.)]:
        values=[base+i*step for i in range(3)]
        cases.extend([('offset_x_'+str(base),values,ordinary),('offset_y_'+str(base),ordinary,values)])
    cases.extend([('singleton_x',[.0001],ordinary),('singleton_y',ordinary,[.0001]),('singleton_both',[.0001],[.0002])])
    for name,xs,ys in cases:
        folder=out/('figure_'+name)
        axes=plot_snapshot(xs,ys,folder)
        for axis in ['x','y']:
            values=axes[axis]
            check(name+'_'+axis+'_roundtrip',values['roundtrip_pass'],values)
            check(name+'_'+axis+'_distinct',values['labels_distinguish_positions'],values)
            check(name+'_'+axis+'_annotation',values['scale_annotation_present'],values)
        if 'sampled_points' in axes:
            check(name+'_sample_positions',axes['sampled_points']['positions_exact'])
            check(name+'_samples_visible',axes['sampled_points']['visible'])
        for suffix in ['png','pdf','svg']:
            check(name+'_export_'+suffix,(folder/('strategy_regions.'+suffix)).stat().st_size>0)
        svg=(folder/'strategy_regions.svg').read_text()
        check(name+'_svg_labels',all(label in svg for axis in ['x','y'] for label in axes[axis]['labels']))
        figure_records.append({'case':name,'x':xs,'y':ys,'axes':axes})
    write_json(out/'figure_checks.json',figure_records)
    def cli(name,config,command):
        path=out/(name+'_config.json');write_json(path,config);folder=out/name
        process=subprocess.run([sys.executable,'-m','entrysignallab.cli',command,'--config',str(path),'--out',str(folder)],text=True,capture_output=True,timeout=120)
        (out/(name+'_stdout.txt')).write_text(process.stdout);(out/(name+'_stderr.txt')).write_text(process.stderr)
        check(name+'_exit',process.returncode==0,process.stderr)
        receipt=verify_manifest(folder,current_source_hashes());check(name+'_receipt',receipt['valid'],receipt)
        cli_records.append({'case':name,'command':command,'exit':process.returncode,'verified':receipt['valid']})
        if process.returncode:raise RuntimeError(process.stderr)
        return folder
    for command in ['audit','reproduce']:
        folder=cli('cli_small_source_'+command,{'params':{'growth':1e-11}},command)
        item=next(x for x in read_json(folder/'source_audit.json')['checks'] if x['id']=='DF_INTEGRAL_IDENTITY')
        check(command+'_source_false',item['pass'] is False and item['decision_basis']=='analytic_nonidentity')
        if command=='reproduce':
            check('html_analytic_basis','analytic_nonidentity' in (folder/'report.html').read_text())
    plot_configs=[('small_x',read_json(root/'examples/small_scale_regions.json')),
                  ('small_y',read_json(root/'examples/small_scale_y_regions.json')),
                  ('small_quality',{'axes':{'quality_ratio':[.0001,.0002,.0003],'network':[.5,1.]},'bounds':{'announcement_upper':0}})]
    for name,config in plot_configs:
        folder=cli('cli_'+name,config,'sweep')
        svg=(folder/'strategy_regions.svg').read_text()
        check(name+'_no_fixed_zero_labels','<!-- 0.000 -->' not in svg)
        check(name+'_scientific_annotation','10^' in svg)
    write_json(out/'CLI_checks.json',cli_records)
    # Preserve the audit's independent wide-scale numerical control corpus.
    subprocess.run([sys.executable,str(root/'scripts/probe_numeric_controls.py'),'--out',str(out/'numeric_controls')],check=True)
    numeric=read_json(out/'numeric_controls/summary.json')
    for i,row in enumerate(read_json(out/'numeric_controls/checks.json')):check('rational_control_'+str(i),row['pass'])
    summary={'checks':len(checks),'all_pass':all(x['pass'] for x in checks),'source_identity_cases':len(source_outputs),
             'source_max_relative_error':maximum_relative_error,'figure_cases':len(figure_records),'CLI_processes':len(cli_records),
             'frozen_baseline_observations':baseline['total'],'frozen_defect_observations':baseline['defect_observations'],
             'independent_rational_parameter_sets':numeric['parameter_sets'],'independent_rational_checks':numeric['checks'],
             'max_rational_relative_error':numeric['maximum_relative_error'],
             'scope':'Analytic source nonidentity, independently reconstructed plotted coordinates and exact rational zero-discount references. No empirical, global-optimality or universal plotting claim.'}
    write_json(out/'checks.json',checks);write_json(out/'v0170_summary.json',summary);print(json.dumps(summary,indent=2))
    record_validation(out,Path(__file__),20261018)
    if not summary['all_pass']:raise SystemExit(1)


if __name__=='__main__':main()
