"""Independent v0.14.0 acceptance for configured controls and research results."""
from pathlib import Path
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import argparse, csv, json, math, subprocess, sys
import numpy as np
from entrysignallab import ModelParams, DecisionBounds, payoff, compare, optimize
from entrysignallab.research import default_research_kernel, optimize_research, ResearchKernel, ModelCapabilities
from entrysignallab.workflow import configured_feasibility, write_json, read_json, load_config, prepare_sweep, execute_case, record_validation
from entrysignallab.plots import resolve_plot_settings
from entrysignallab.batch import CheckpointStore, _export_csv


def reference_payoff(p, strategy, delay, intensity):
    """Direct 100-digit piecewise integrals, independent of the log kernels."""
    with localcontext() as context:
        context.prec = 100
        D = lambda value: Decimal.from_float(float(value))
        s, phi, H, T, w, mx, cA, cD, k, r = map(D, [p.growth, p.network, p.growth_end, p.horizon,
            p.quality_ratio, p.margin_x, p.announcement_cost, p.deployment_cost, p.learning_rate, p.discount])
        t, d = map(D, [delay, intensity])
        if strategy.endswith('F'):
            x = 1 + phi * s * t + (phi * d * t if strategy == 'RF' else 0)
            y = w
        else:
            x = 1 + (phi * d * t if strategy == 'RL' else 0)
            y = w * (1 + phi * s * t)
        if r:
            j0 = lambda a, b: ((-r*a).exp() - (-r*b).exp()) / r
            j1 = lambda a, b: ((1+r*a)*(-r*a).exp() - (1+r*b)*(-r*b).exp()) / (r*r)
            post = j1(t,H) - t*j0(t,H) + (H-t)*j0(H,T)
            lead = j1(Decimal(0),t) + t*j0(t,T)
        else:
            post = (H-t)*(T-H) + (H-t)**2/2
            lead = t*(T-t/2)
        entry = Decimal(0) if strategy.endswith('F') else t
        return mx*s*((lead if strategy.endswith('F') else 0) + post*x/(x+y)) - cA*d*d/2 - cD*(-(k+r)*entry).exp()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out.absolute()
    if out.exists(): raise SystemExit('Choose a fresh output directory')
    out.mkdir(parents=True)
    checks = []; controls = []; objective_rows = []; export_rows = []; cli_rows = []
    def check(name, condition, detail=None): checks.append({'name': name, 'pass': bool(condition), 'detail': detail})
    def rejects(name, operation):
        try: operation(); rejected = False; error = None
        except ValueError as exception: rejected = True; error = str(exception)
        check(name, rejected, error)
        return rejected
    p = ModelParams(); b = DecisionBounds(); kernel = default_research_kernel()
    def candidate(params, strategy, delay, intensity, reported=None):
        result = {'strategy': strategy, 'delay': delay, 'announcement': intensity,
                  'payoff': payoff(params, strategy, delay, intensity) if reported is None else reported}
        return replace(kernel, conditional_solver=lambda *args: dict(result)), result

    for strategy in ['RF', 'RL', 'DF', 'DL']:
        for delay in [Fraction(1,10), Fraction(1,5), Fraction(3,10)]:
            native = float(delay); intensity = Fraction(3,10) if strategy.startswith('R') else Fraction(0)
            bounds = replace(b, delay_lower=native, delay_upper=native, announcement_upper=.3)
            result = configured_feasibility(p, bounds, native, strategy, delay, intensity)
            normalized = configured_feasibility(p, bounds, native, strategy, native, float(intensity))
            name = strategy + '_' + str(delay)
            check('A01_fraction_domain_' + name, result == normalized and result['within_configured_bounds'])
            adapter, original = candidate(p, strategy, delay, intensity)
            answer = optimize_research(adapter, p, strategy, bounds, native)
            check('A01_research_' + name, answer['delay'] == native and answer['announcement'] == float(intensity))
            controls.append({'strategy': strategy, 'fraction': str(delay), 'stored_delay': native,
                             'within_bounds': result['within_configured_bounds']})
    for strategy in ['RF', 'RL', 'DF', 'DL']:
        bounds = replace(b, delay_lower=.1, delay_upper=.1)
        result = configured_feasibility(p, bounds, .1, strategy, .1001, 0.)
        check('A01_true_outside_' + strategy, not result['within_configured_bounds'])
    plot = resolve_plot_settings(p, replace(b, delay_lower=.1, delay_upper=.1, announcement_upper=.3), Fraction(1,10),
        {'delay': Fraction(1,10), 'announcement': Fraction(3,10), 'surface_announcement_max': Fraction(3,10)})
    check('A01_plot_native_json', bool(json.dumps(plot, allow_nan=False)) and plot['trajectory_controls']['RL'] == {'delay': .1, 'announcement': .3})
    for label, value in [('negative', -.1), ('nonzero_underflow', Fraction(1,10**500)), ('complex', .1+0j), ('boolean', True), ('nonfinite', float('inf'))]:
        rejects('A01_invalid_' + label, lambda: configured_feasibility(p,b,.1,'DL',value,0.))
    write_json(out/'configured_controls.json', controls)

    reference_count = 0; maximum_relative_error = 0.
    for scale in [1., 1e-12, 1e-100, 1e-280, 1e-300]:
        for negative in [False, True]:
            q = replace(p, margin_x=scale, deployment_cost=scale if negative else 0.)
            for strategy in ['RF','RL','DF','DL']:
                delay = .1; intensity = .125 if strategy.startswith('R') else 0.
                oracle = reference_payoff(q,strategy,delay,intensity)
                actual = payoff(q,strategy,delay,intensity)
                expected = float(oracle)
                relative_error = abs(actual / expected - 1.)
                maximum_relative_error = max(maximum_relative_error,relative_error); reference_count += 1
                name = strategy+'_'+str(scale)+'_'+str(negative)
                check('A02_decimal_payoff_'+name, relative_error <= 1e-12, relative_error)
                adapter, raw = candidate(q,strategy,delay,intensity,expected)
                answer = optimize_research(adapter,q,strategy,b,delay)
                check('A02_independent_result_accepted_'+name, answer['payoff']==expected and answer['objective_consistency']['status']=='passed')
                objective_rows.append({'strategy':strategy,'scale':scale,'negative':negative,'oracle_100_digit':str(oracle),
                    'kernel_value':actual,'relative_error':relative_error,'independent_result_accepted':True})
    q = replace(p,margin_x=1e-280,deployment_cost=1e-280)
    original = optimize(q,'RF',b,.15)
    for label, value in [('zero',0.),('positive',1e-11),('negative_scale',-1e-11)]:
        altered = replace(kernel,conditional_solver=lambda *args,value=value:{**original,'payoff':value})
        rejects('A02_original_false_'+label,lambda:optimize_research(altered,q,'RF',b,.15))
    bad = replace(kernel,conditional_solver=lambda p,s,b,r:{**optimize(p,s,b,r),'payoff':1e-11} if s=='RF' else optimize(p,s,b,r))
    rejects('A02_false_entry_comparison',lambda:compare(q,b,.15,tie_tolerance=0.,optimizer=lambda p,s,b,r:optimize_research(bad,p,s,b,r)))
    check('A02_genuine_no_entry',compare(q,b,.15,tie_tolerance=0.)['preferred_with_outside_option']==['no_entry'])
    def toy(reference, actual, **options):
        k = ResearchKernel(ModelCapabilities('toy','1',False,False),lambda *a:reference,lambda *a:None,lambda *a:None,
            lambda p,s,b,r:{'strategy':s,'delay':Fraction(-1,8),'announcement':np.int64(-2),'payoff':actual},lambda *a:True,**options)
        return optimize_research(k,{},'custom',{'domain':'negative'})
    smallest = math.ulp(0.)
    for label, reference, value in [('zero_reference',0.,smallest),('false_zero_subnormal',smallest,0.),
                                  ('opposite_subnormal',smallest,-smallest),('ordinary_wrong',1.,1.001),
                                  ('huge_opposite',sys.float_info.max,-sys.float_info.max)]:
        rejects('A02_reject_'+label,lambda:toy(reference,value))
    for label, value in [('positive_subnormal',smallest),('negative_subnormal',-smallest),('zero',0.),('ordinary',1.)]:
        result=toy(value,value);check('A02_accept_'+label,result['payoff']==value and result['objective_consistency']['zero_sign_guard'])
    result=toy(0.,1e-11,objective_atol=1e-10)
    check('A02_explicit_absolute_policy',result['objective_consistency']['absolute_tolerance']==1e-10 and not result['objective_consistency']['zero_sign_guard'])
    result=toy(1.,1.0001,objective_rtol=1e-3)
    check('A02_explicit_relative_policy',result['objective_consistency']['relative_tolerance']==1e-3)
    for field in ['objective_atol','objective_rtol']:
        for label,value in [('negative',-1.),('nonfinite',float('inf')),('boolean',True)]:
            rejects('A02_bad_policy_'+field+'_'+label,lambda:toy(1.,1.,**{field:value}))
    write_json(out/'objective_references.json',objective_rows)

    for label, delay, intensity in [('fraction_delay',Fraction(1,8),0.),('float32_delay',np.float32(.125),0.),
                                   ('int64_announcement',.125,np.int64(0)),('fraction_announcement',.125,Fraction(0))]:
        adapter, original=candidate(p,'DL',delay,intensity)
        result=optimize_research(adapter,p,'DL',b,.125)
        path=out/('export_'+label+'.json');write_json(path,result)
        check('A03_export_'+label,read_json(path)==result and all(type(result[name]) is float for name in ['delay','announcement','payoff']))
        check('A03_preserve_'+label,type(original['delay']) is type(delay) and type(original['announcement']) is type(intensity) and 'objective_consistency' not in original)
        export_rows.append({'case':label,'source_delay_type':type(delay).__name__,'source_announcement_type':type(intensity).__name__,
                            'exported_delay_type':type(result['delay']).__name__,'exported_announcement_type':type(result['announcement']).__name__})
    custom=toy(-1.,-1.);check('A03_negative_custom_domain',custom['delay']==-.125 and custom['announcement']==-2.)
    for strategy in ['RF','RL']:
        result=optimize_research(kernel,p,strategy,replace(b,announcement_upper=None),.125)
        check('A03_null_controls_'+strategy,result['payoff'] is None and result['delay'] is None and result['announcement'] is None and result['objective_consistency']['status']=='not_applicable' and bool(json.dumps(result,allow_nan=False)))
    def extension(params,strategy,bounds,rival):
        adapter,_=candidate(params,strategy,Fraction(1,8),np.int64(0))
        return optimize_research(adapter,params,strategy,bounds,rival)
    comparison=compare(p,b,.125,optimizer=extension)
    check('A03_comparison_json',bool(json.dumps(comparison,allow_nan=False)) and len(comparison['results'])==4)
    meta,tasks=prepare_sweep(p,b,.125,{'deployment_cost':[.001]})
    case=execute_case(p,b,.125,next(tasks()),meta,extension)
    directory=out/'research_checkpoint';directory.mkdir()
    store=CheckpointStore(directory/'checkpoint.sqlite',{'source':'v0140_extension_export'})
    try:
        store.add(case);store.commit();_export_csv(directory,'sweep',store)
        check('A03_checkpoint_roundtrip',list(store.cases())==[case])
    finally:store.close()
    with (directory/'sweep.csv').open() as f:rows=list(csv.DictReader(f))
    check('A03_csv_export',len(rows)==4 and all(float(row['delay'])==.125 for row in rows))
    write_json(out/'research_exports.json',export_rows)

    config=out/'cli_config.json';write_json(config,{'bounds':{'delay_lower':0.,'delay_upper':0.}})
    def cli(label,delay='0',intensity='0',diagnostic=False):
        command=[sys.executable,'-m','entrysignallab.cli','evaluate','--config',str(config),'--strategy','DL','--delay='+delay,'--announcement='+intensity]
        if diagnostic:command.append('--allow-outside-bounds')
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        (out/(label+'.stdout.txt')).write_text(result.stdout);(out/(label+'.stderr.txt')).write_text(result.stderr)
        row={'case':label,'delay_token':delay,'announcement_token':intensity,'exit':result.returncode,
             'output':json.loads(result.stdout) if result.returncode==0 else None,'stderr':result.stderr}
        cli_rows.append(row);return row
    bad_tokens=[('positive_delay','1e-400','0'),('negative_delay','-1e-400','0'),
                ('positive_silent','0','1e-400'),('negative_silent','0','-1e-400'),
                ('uppercase','0.001E-999','0'),('underscore','1_0e-400','0'),
                ('unicode','１e-400','0'),('long_exponent','1e-9999999999','0')]
    for label,delay,intensity in bad_tokens:
        row=cli('underflow_'+label,delay,intensity)
        lexical=Decimal(delay) if Decimal(delay)!=0 else Decimal(intensity)
        check('A04_lexical_nonzero_'+label,lexical!=0)
        check('A04_reject_'+label,row['exit']==2 and 'underflows' in row['stderr'] and row['output'] is None)
    for label,delay,intensity,diagnostic,exit_code in [('exact_zero','0e-400','0e-400',False,0),
        ('signed_zero','-0e-400','-0e-400',False,0),('minimum_subnormal','5e-324','0',True,0),
        ('normal_outside','.001','0',False,2),('silent_nonzero','0','.001',False,2),
        ('overflow','1e400','0',False,2),('nonfinite','NaN','0',False,2),
        ('ordinary','.125','0',True,0),('python_underscore','0_0.125','0',True,0),('python_unicode','０.１２５','0',True,0)]:
        row=cli('control_'+label,delay,intensity,diagnostic)
        check('A04_control_'+label,row['exit']==exit_code and (label!='minimum_subnormal' or row['output']['delay']==smallest))
    for label,token in [('positive','1e-400'),('negative','-1e-400')]:
        path=out/('json_'+label+'.json');path.write_text('{"params":{"growth":'+token+'}}')
        rejects('A04_JSON_retained_'+label,lambda:load_config(path))
    write_json(out/'cli_tokens.json',cli_rows)
    summary={'all_pass':all(row['pass'] for row in checks),'checks':len(checks),
        'configured_fraction_cases':len(controls),'independent_decimal_payoffs':reference_count,
        'decimal_precision':100,'max_payoff_relative_error':maximum_relative_error,
        'original_core_export_cases':len(export_rows),'CLI_underflow_rejections':len(bad_tokens),
        'CLI_control_cases':10,'checkpoint_case_rows':len(rows),
        'scope':'Installed-wheel acceptance, independent Decimal integrals across four strategies and five scales, configured-domain controls, real JSON/checkpoint/CSV exports and genuine CLI processes. Explicit custom tolerance is recorded and is not a proof of objective accuracy or global optimality.'}
    write_json(out/'v0140_checks.json',checks);write_json(out/'v0140_summary.json',summary)
    record_validation(out,Path(__file__),seed=20261018);print(json.dumps(summary,indent=2))
    if not summary['all_pass']:raise SystemExit('v0.14.0 acceptance failed')


if __name__=='__main__':main()
