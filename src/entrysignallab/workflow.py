"""Validated experiment configuration, sweeps and paired uncertainty. MIT License."""
from dataclasses import asdict, replace, fields
from itertools import product
from pathlib import Path
import json, hashlib, platform, sys, re
from datetime import datetime, timezone
from numbers import Integral
import numpy as np
import scipy, matplotlib
from . import __version__
from .model import ModelParams, finite_number, finite_float_text, STRATEGIES, decisions
from .solver import DecisionBounds, compare, _compare_model_results
from .provenance import environment_record

PARAM_NAMES = {f.name for f in fields(ModelParams)}

def normalize_comparison(spec=None):
    """One comparison policy for CLI, sweeps and paired sampling."""
    spec={} if spec is None else spec
    if not isinstance(spec,dict) or set(spec)-{'tie_tolerance','outside_option'}:
        raise ValueError('comparison must be an object with tie_tolerance and outside_option')
    return {'tie_tolerance':finite_number(spec.get('tie_tolerance',1e-8),'tie_tolerance',minimum=0),
            'outside_option':finite_number(spec.get('outside_option',0.),'outside_option')}

def normalize_error_policy(value='raise'):
    if value not in ('raise','record'):raise ValueError('on_error must be raise or record')
    return value

def configured_feasibility(p,bounds,rival,strategy,delay,announcement):
    """Assess configured controls after validating the mathematical domain."""
    delay=finite_number(delay,'delay',minimum=0)
    announcement=finite_number(announcement,'announcement',minimum=0)
    decisions(p,strategy,delay,announcement);lo,hi=bounds.validate(p);violations=[]
    if strategy.endswith('L'):
        if not lo<=delay<=hi:violations.append({'control':'follower_delay','actual':float(delay),'lower':lo,'upper':hi})
    else:
        rival=finite_number(rival,'rival_delay',minimum=0)
        if rival>p.growth_end:raise ValueError('rival_delay exceeds growth_end')
    if strategy.endswith('F') and delay!=rival:
        violations.append({'control':'fixed_rival_delay','actual':float(delay),'required':float(rival)})
    if strategy.startswith('R') and bounds.announcement_upper is not None and announcement>bounds.announcement_upper:
        violations.append({'control':'announcement','actual':float(announcement),'upper':float(bounds.announcement_upper)})
    return {'within_configured_bounds':not violations,'diagnostic_only':bool(violations),
            'evaluation_scope':'outside_configured_bounds' if violations else 'configured_feasible',
            'bound_violations':violations}

def _json_float(token):
    """Reject a nonzero JSON literal lost before the binary64 domain checks."""
    return finite_float_text(token,'JSON number')

def load_config(path):
    def reject_constant(x): raise ValueError(f"non-finite JSON constant {x}")
    def unique_object(pairs):
        obj={}
        for k,v in pairs:
            if k in obj:raise ValueError(f"duplicate JSON key {k}")
            obj[k]=v
        return obj
    with Path(path).open(encoding="utf-8") as f:
        obj = json.load(f, parse_float=_json_float, parse_constant=reject_constant, object_pairs_hook=unique_object)
    if not isinstance(obj, dict): raise ValueError("configuration must be an object")
    extra = set(obj)-{"params","bounds","rival_delay","axes","uncertainty","seed","label","plot","comparison","on_error","batch","stability"}
    if extra: raise ValueError(f"unknown configuration keys: {sorted(extra)}")
    p = ModelParams.from_dict(obj.get("params", {}))
    bounds = DecisionBounds(**obj.get("bounds", {})); bounds.validate(p)
    rival = obj.get("rival_delay", min(.15,p.growth_end))
    finite_number(rival,"rival_delay",minimum=0)
    if rival>p.growth_end: raise ValueError("rival_delay exceeds growth_end")
    normalize_comparison(obj.get('comparison'));normalize_error_policy(obj.get('on_error','raise'));normalize_batch(obj.get('batch'))
    seed = obj.get("seed",104)
    if isinstance(seed,bool) or not isinstance(seed,int) or seed<0: raise ValueError("seed must be a nonnegative integer")
    return obj,p,bounds,float(rival),seed

def _batch_setup(p,bounds,rival,domains,comparison,on_error,plan=None):
    options=normalize_comparison(comparison);policy=normalize_error_policy(on_error)
    rival=finite_number(rival,'rival_delay',minimum=0);bounds.validate(p)
    lowest=lambda name:min(domains[name]) if name in domains else getattr(p,name)
    highest=lambda name:max(domains[name]) if name in domains else getattr(p,name)
    issues=[]
    for name in ['horizon','quality_ratio']:
        if lowest(name)<=0:issues.append(name+' includes non-positive values')
    if highest('growth_end')>lowest('horizon') and not (plan is not None and plan.proves_equal('growth_end','horizon')):
        issues.append('growth_end upper exceeds horizon lower')
    if lowest('growth_end')<rival:issues.append('growth_end lower is below fixed rival_delay')
    if lowest('growth_end')<bounds.delay_lower:issues.append('growth_end lower is below delay_lower')
    if bounds.delay_upper is not None and lowest('growth_end')<bounds.delay_upper:
        issues.append('growth_end lower is below delay_upper')
    if issues and policy=='raise':raise ValueError('infeasible batch domain: '+'; '.join(issues))
    return options,policy,rival,issues


def _batch_case(p,bounds,rival,changes,options,policy,optimizer=None):
    stage='configuration'
    try:
        q=replace(p,**changes);bounds.validate(q)
        if rival>q.growth_end:raise ValueError('growth_end is below fixed rival_delay')
        stage='optimization'
        report=compare(q,bounds,rival,**options,**({"optimizer":optimizer} if optimizer is not None else {}))
        if optimizer is not None:
            # The built-in cache changes first-mover controls, not the owned
            # objective. Arbitrary extension optimizers keep float semantics.
            from .batch import CachedFirstOptimizer
            if type(optimizer) is CachedFirstOptimizer:report=_compare_model_results(q,report)
        return report,None
    except (ValueError,OverflowError,RuntimeError) as error:
        if policy=='raise':raise
        return None,{'batch_status':'invalid_configuration' if stage=='configuration' else 'numerical_error',
                     'error_stage':stage,'error_type':type(error).__name__,'error_message':str(error)}


def _failure_rows(changes,error):
    return [{**changes,'strategy':st,'status':error['batch_status'],'delay':None,'announcement':None,'payoff':None,
             'co_best':'','outside_option_preferred':'','all_rankable':False,**error} for st in STRATEGIES]


def normalize_batch(spec=None):
    spec={} if spec is None else spec
    if not isinstance(spec,dict) or set(spec)-{'max_cases','workers','checkpoint_every'}:raise ValueError('invalid batch options')
    options={'max_cases':100000,'workers':1,'checkpoint_every':25};options.update(spec)
    for name,limit in [('max_cases',10000000),('workers',32),('checkpoint_every',1000)]:
        value=options[name]
        if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=limit:raise ValueError(name+' must be a positive integer <= '+str(limit))
    return options


def prepare_sweep(p,bounds,rival,axes,comparison=None,on_error='raise',batch=None):
    if not isinstance(axes,dict) or not axes:raise ValueError('axes must be a nonempty object')
    if len(axes)>3:raise ValueError('at most three sweep axes are supported')
    domains={}
    for name in sorted(axes):
        values=axes[name]
        if name not in PARAM_NAMES:raise ValueError('unknown parameter '+name)
        if not isinstance(values,list) or not values:raise ValueError('each axis must be a nonempty list')
        domains[name]=[finite_number(v,name,minimum=0) for v in values]
    options,policy,rival,issues=_batch_setup(p,bounds,rival,domains,comparison,on_error);settings=normalize_batch(batch)
    total=1
    for values in domains.values():total*=len(values)
    if total>settings['max_cases']:raise ValueError('requested Cartesian cases exceed max_cases budget')
    meta={'operation':'sweep','requested_cases':total,'comparison':options,'on_error':policy,'batch':settings,'domain_preflight_issues':issues,'parameter_order':list(domains),'task_generator_version':'cartesian-product-v1','axes':domains}
    def tasks():
        for index,values in enumerate(product(*domains.values())):
            yield {'case_index':index,'changes':dict(zip(domains,values)),'sampling_attempts':1}
    return meta,tasks


def _constraint_domain_issues(plan,p):
    low=lambda n:plan.domains[n][0] if n in plan.domains else getattr(p,n)
    high=lambda n:plan.domains[n][1] if n in plan.domains else getattr(p,n)
    violations=[];impossible=[]
    for c in plan.constraints:
        if c.get('right')==c['left'] or ('right' in c and plan.proves_equal(c['left'],c['right'])):continue  # le/ge on the same finite value is tautological.
        alo,ahi=low(c['left']),high(c['left']);blo,bhi=(low(c['right']),high(c['right'])) if 'right' in c else (c['value'],c['value'])
        violates=ahi>blo if c['relation']=='le' else alo<bhi
        cannot=alo>bhi if c['relation']=='le' else ahi<blo
        if violates:violations.append('sampling domain crosses constraint '+str(c))
        if cannot:impossible.append('sampling domain cannot satisfy constraint '+str(c))
    return violations,impossible


def prepare_uncertainty(p,bounds,rival,ranges,n=100,seed=104,comparison=None,on_error='raise',batch=None,
                        marginals=None,correlation=None,constraints=None,constraint_mode='record',max_draw_attempts=100):
    from .sampling import SamplingPlan
    if isinstance(n,bool) or not isinstance(n,Integral) or n<1:raise ValueError('sample count must be a positive integer')
    if isinstance(seed,bool) or not isinstance(seed,Integral) or seed<0:raise ValueError('seed must be a nonnegative integer')
    settings=normalize_batch(batch)
    if n>settings['max_cases']:raise ValueError('requested samples exceed max_cases budget')
    policy=normalize_error_policy(on_error);plan=SamplingPlan(p,ranges,int(seed),marginals,correlation,constraints,constraint_mode,max_draw_attempts)
    options,_,rival,issues=_batch_setup(p,bounds,rival,plan.domains,comparison,'record' if plan.mode=='resample' else policy,plan)
    crossed,impossible=_constraint_domain_issues(plan,p);issues+=crossed
    if impossible:raise ValueError('; '.join(impossible))
    if crossed and policy=='raise' and plan.mode!='resample':raise ValueError('; '.join(crossed))
    if plan.mode=='resample':
        max_h=plan.domains['growth_end'][1] if 'growth_end' in plan.domains else p.growth_end
        max_t=plan.domains['horizon'][1] if 'horizon' in plan.domains else p.horizon
        min_h=plan.domains['growth_end'][0] if 'growth_end' in plan.domains else p.growth_end
        if max_h<max(rival,bounds.delay_lower,bounds.delay_upper or 0) or min_h>max_t:raise ValueError('sampling domain has no feasible model')
    meta={'operation':'uncertainty','requested_cases':int(n),'samples':int(n),'seed':int(seed),'comparison':options,'on_error':policy,
          'batch':settings,'domain_preflight_issues':issues,'sampling':plan.metadata()}
    def tasks():
        for index in range(int(n)):
            rejected=0
            for attempt in range(plan.max_attempts if plan.mode=='resample' else 1):
                try:changes=plan.draw(index,attempt)
                except (ValueError,OverflowError,RuntimeError,FloatingPointError) as error:
                    yield {'case_index':index,'changes':{name:None for name in plan.specs},'sampling_attempts':attempt+1,
                           'sampling_accepted':0,'sampling_rejected':rejected,'sampling_numerical_failures':1,'sampling_exhausted':False,
                           'sampling_failure':{'batch_status':'numerical_error','error_stage':'sampling','error_type':type(error).__name__,'error_message':str(error)}}
                    break
                full={**asdict(p),**changes};reason=None
                try:
                    q=replace(p,**changes);bounds.validate(q)
                    if rival>q.growth_end:raise ValueError('growth_end is below fixed rival_delay')
                    if plan.constraint_issues(full):raise ValueError('sample violates explicit joint constraint')
                except ValueError as e:reason=str(e)
                if reason is not None:
                    rejected+=1
                    if plan.mode=='resample' and attempt+1<plan.max_attempts:continue
                yield {'case_index':index,'changes':changes,'sampling_attempts':attempt+1,'sampling_error':reason,
                       'sampling_accepted':int(reason is None),'sampling_rejected':rejected,'sampling_numerical_failures':0,
                       'sampling_exhausted':reason is not None and plan.mode=='resample'}
                break
    return meta,tasks


def execute_case(p,bounds,rival,task,meta,optimizer=None):
    changes=task['changes'];policy=meta['on_error'];options=meta['comparison']
    if task.get('sampling_failure'):
        error=task['sampling_failure'];report=None
        if policy=='raise':raise ValueError(error['error_message'])
    elif task.get('sampling_error'):
        if policy=='raise':raise ValueError(task['sampling_error'])
        error={'batch_status':'invalid_configuration','error_stage':'sampling','error_type':'ValueError','error_message':task['sampling_error']};report=None
    else:report,error=_batch_case(p,bounds,rival,changes,options,policy,optimizer)
    if error:case_rows=_failure_rows(changes,error)
    else:
        case_rows=[{**changes,**result,'co_best':'|'.join(report['co_best']),
                    'outside_option_preferred':'|'.join(report['preferred_with_outside_option']),
                    'all_rankable':report['all_rankable'],'all_local_quality_passed':report['all_local_quality_passed'],
                    'local_quality_status':report['local_quality_status'],'local_quality_assessment_complete':report['local_quality_assessment_complete'],
                    'scenario_local_quality_status':report['local_quality_by_strategy'][result['strategy']],
                    'entry_payoff_gap':report['entry_payoff_gap'],'outside_option_gap':report['outside_option_gap'],
                    'entry_payoff_gap_basis':(report['entry_payoff_gap_diagnostic'] or {}).get('decision_basis','rounded_payoff_difference'),
                    'outside_option_gap_basis':(report['outside_option_gap_diagnostic'] or {}).get('decision_basis','rounded_payoff_difference'),
                    'outside_option_gap_representation':(report['outside_option_gap_diagnostic'] or {}).get('representation'),
                    'outside_option_gap_sign':(report['outside_option_gap_diagnostic'] or {}).get('sign'),
                    'batch_status':'ok'} for result in report['results']]
    label=error['batch_status'] if error else 'unrankable' if not report['all_rankable'] else report['co_best'][0] if len(report['co_best'])==1 else 'tie'
    preferred=[] if error else report['preferred_with_outside_option']
    participation=error['batch_status'] if error else 'unrankable' if not preferred else 'non_entry_preferred' if preferred==['no_entry'] else 'tie' if 'no_entry' in preferred else 'entry_preferred'
    rows=[{**r,'case_index':task['case_index'],'comparison_tie_tolerance':options['tie_tolerance'],
           'outside_option_payoff':options['outside_option'],'batch_on_error':policy,'sampling_attempts':task['sampling_attempts']} for r in case_rows]
    accounting={k:task[k] for k in ['sampling_accepted','sampling_rejected','sampling_numerical_failures','sampling_exhausted'] if k in task}
    if meta['operation']=='uncertainty':rows=[{**r,'sample':task['case_index'],'winner':label,'participation':participation,**accounting} for r in rows]
    failure=None if not error else {'sample':task['case_index'],'params':{**asdict(p),**changes},**error,'sampling_attempts':task['sampling_attempts']}
    if failure:failure.update(accounting)
    return {'case_index':task['case_index'],'rows':rows,'failure':failure,'winner':label,'participation':participation,'sampling_attempts':task['sampling_attempts'],**accounting}


def sweep(p,bounds,rival,axes,comparison=None,on_error='raise',batch=None):
    meta,tasks=prepare_sweep(p,bounds,rival,axes,comparison,on_error,batch)
    return [r for task in tasks() for r in execute_case(p,bounds,rival,task,meta)['rows']]


def summarize_sweep(rows,comparison=None,on_error=None):
    if not rows:raise ValueError('cannot summarize an empty sweep')
    policies={(r['comparison_tie_tolerance'],r['outside_option_payoff'],r.get('batch_on_error','raise')) for r in rows}
    if len(policies)!=1:raise ValueError('mixed sweep comparison or failure policies')
    tie,outside,recorded=next(iter(policies));actual={'tie_tolerance':tie,'outside_option':outside}
    if comparison is not None and normalize_comparison(comparison)!=actual:raise ValueError('summary comparison disagrees with rows')
    if on_error is not None and normalize_error_policy(on_error)!=recorded:raise ValueError('summary error policy disagrees with rows')
    cases={r['case_index']:r for r in rows};counts={name:0 for name in ['ok','invalid_configuration','numerical_error']}
    for row in cases.values():counts[row['batch_status']]+=1
    failures=[{'case_index':r['case_index'],'batch_status':r['batch_status'],'error_stage':r['error_stage'],'error_type':r['error_type'],'error_message':r['error_message']} for r in cases.values() if r['batch_status']!='ok']
    failed=len(cases)-counts['ok']
    return {'requested_cases':len(cases),'completed_cases':counts['ok'],'failed_cases':failed,
            'rankable_cases':sum(r['batch_status']=='ok' and r['all_rankable'] for r in cases.values()),
            'unrankable_cases':sum(r['batch_status']=='ok' and not r['all_rankable'] for r in cases.values()),
            'quality_warning_cases':sum(r['batch_status']=='ok' and r.get('local_quality_status')=='fail' for r in cases.values()),
            'quality_status_counts':{k:sum(r['batch_status']=='ok' and r.get('local_quality_status','not_assessed')==k for r in cases.values()) for k in ['pass','fail','not_assessed']},
            'quality_assessment_complete_cases':sum(r['batch_status']=='ok' and r.get('local_quality_assessment_complete',False) for r in cases.values()),
            'quality_excluded_failed_cases':failed,
            'failure_counts':{k:counts[k] for k in ['invalid_configuration','numerical_error']},'failures':failures,
            'run_status':'all_failed' if failed==len(cases) else 'partial_failure' if failed else 'complete',
            'on_error':recorded,'comparison':actual,
            'interpretation':'Failed cases retain null payoffs. Quality warnings and valid unrankable models remain distinct from failed computations.'}


def summarize_uncertainty(cases,meta,keep_rows=False):
    from .sampling import wilson_interval,linear_quantiles
    counts={st:0 for st in STRATEGIES};counts.update({'tie':0,'unrankable':0,'invalid_configuration':0,'numerical_error':0})
    participation={k:0 for k in ['entry_preferred','non_entry_preferred','tie','unrankable','invalid_configuration','numerical_error']}
    rows=[];failures=[];attempts=0;accepted=0;rejected=0;numerical_draw_failures=0;exhausted=0;quality_counts={k:0 for k in ['pass','fail','not_assessed']};quality_complete=0;payoffs={st:[] for st in STRATEGIES};actual=0
    for case in cases:
        actual+=1;counts[case['winner']]+=1;participation[case['participation']]+=1;attempts+=case['sampling_attempts']
        accepted+=case['sampling_accepted'];rejected+=case['sampling_rejected'];numerical_draw_failures+=case['sampling_numerical_failures'];exhausted+=int(case['sampling_exhausted'])
        if case['failure']:failures.append(case['failure'])
        else:
            quality_counts[case['rows'][0].get('local_quality_status','not_assessed')]+=1
            quality_complete+=int(case['rows'][0].get('local_quality_assessment_complete',False))
            for row in case['rows']:
                if row['payoff'] is not None:payoffs[row['strategy']].append(row['payoff'])
        if keep_rows:rows.extend(case['rows'])
    n=meta['requested_cases']
    if actual!=n:raise ValueError('uncertainty summary requires all requested cases')
    if attempts!=accepted+rejected+numerical_draw_failures:raise ValueError('sampling attempt accounting mismatch')
    completed=n-len(failures)
    summary={k:{'count':v,'frequency':v/n,'frequency_ci95':wilson_interval(v,n),
                'valid_sample_frequency':v/completed if completed and k not in ['invalid_configuration','numerical_error'] else None,
                'valid_sample_frequency_ci95':wilson_interval(v,completed) if completed and k not in ['invalid_configuration','numerical_error'] else None} for k,v in counts.items()}
    result={'samples':n,'requested_samples':n,'completed_samples':completed,'failed_samples':len(failures),'seed':meta['seed'],
            'on_error':meta['on_error'],'comparison':meta['comparison'],'domain_preflight_issues':meta['domain_preflight_issues'],'failures':failures,
            'sampling':meta['sampling'],'draw_attempts':attempts,'accepted_draws':accepted,'rejected_draw_attempts':rejected,
            'sampling_numerical_failures':numerical_draw_failures,'exhausted_samples':exhausted,'quality_warning_samples':quality_counts['fail'],
            'quality_status_counts':quality_counts,'quality_assessment_complete_samples':quality_complete,
            'quality_excluded_failed_samples':len(failures),
            'quality_interpretation':'Status counts partition completed samples. Any explicit failed local check takes precedence; pass requires four finite assessed candidates. Other completed samples are not_assessed; per-scenario unattained results are not_applicable. Quality warnings count fail only. Configuration/computation failures are excluded.',
            'attempt_accounting':'draw_attempts = accepted_draws + rejected_draw_attempts + sampling_numerical_failures; optimization failures do not undo accepted draws.',
            'run_status':'all_failed' if not completed else 'partial_failure' if failures else 'complete',
            'frequency_denominator':'requested_samples','valid_sample_frequency_denominator':'completed_samples',
            'distribution':'Explicit bounded marginals; independent or Gaussian copula; paired across scenarios. See sampling metadata.',
            'interval_interpretation':'Marginal Wilson 95% Monte Carlo sampling intervals, not simultaneous intervals, empirical market probabilities or optimizer error bounds.',
            'interpretation':'Requested-draw frequencies retain failures. Completed-draw frequencies use a separate denominator; rejection sampling changes the target to the feasible conditional distribution.',
            'summary':summary,'outside_option_summary':participation,
            'outside_option_frequencies':{k:{'frequency':v/n,'frequency_ci95':wilson_interval(v,n)} for k,v in participation.items()},
            'payoff_summaries':{st:{'finite_cases':len(v),'quantiles_05_50_95':linear_quantiles(v,[.05,.5,.95]) if v else None} for st,v in payoffs.items()}}
    if keep_rows:result['rows']=rows
    return result


def uncertainty(p,bounds,rival,ranges,n=100,seed=104,comparison=None,on_error='raise',batch=None,
                marginals=None,correlation=None,constraints=None,constraint_mode='record',max_draw_attempts=100):
    meta,tasks=prepare_uncertainty(p,bounds,rival,ranges,n,seed,comparison,on_error,batch,marginals,correlation,constraints,constraint_mode,max_draw_attempts)
    return summarize_uncertainty((execute_case(p,bounds,rival,task,meta) for task in tasks()),meta,True)

def csv_export_row(row):
    """The added probe ledger is strict JSON in CSV; legacy cells keep their format."""
    return {key:(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
                 if key=='local_probe_diagnostics' and value is not None else value)
            for key,value in row.items()}


def write_json(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")

def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def canonical_hash(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def read_json(path):
    """Strict JSON for archived records as well as experiment inputs."""
    def reject(value):raise ValueError(f"non-finite JSON constant {value}")
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError(f"duplicate JSON key {key}")
            result[key]=value
        return result
    return json.loads(Path(path).read_text(),parse_float=_json_float,parse_constant=reject,object_pairs_hook=unique)

def current_source_hashes():
    """Hashes of the executing package, including its version declaration."""
    return {p.name:sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}

def manifest(directory,config,seed,operation):
    directory=Path(directory)
    sources=current_source_hashes()
    artifacts={str(p.relative_to(directory)):sha256(p) for p in sorted(directory.rglob("*")) if p.is_file() and p!=directory/"manifest.json"}
    record={"manifest_schema":1,"software":"EntrySignalLab","version":__version__,"model_contract":"piecewise-demand-v1","operation":operation,
            "utc_created":datetime.now(timezone.utc).isoformat(),"config":config,"config_sha256":canonical_hash(config),"seed":seed,
            "python":sys.version,"numpy":np.__version__,"scipy":scipy.__version__,"matplotlib":matplotlib.__version__,
            "platform":platform.platform(),"machine":platform.machine(),"processor":platform.processor(),
            "environment":environment_record(),
            "source_sha256":sources,"artifacts_sha256":artifacts,"equilibrium_computed":False}
    write_json(directory/"manifest.json",record);return record

def verify_manifest(directory, expected_source=None):
    """Check schema, exact artifact inventory, hashes and optional package binding."""
    root=Path(directory).resolve();errors=[];artifacts={};source_verified=None
    try:
        record=read_json(root/"manifest.json")
        if not isinstance(record,dict):raise ValueError("manifest must be a JSON object")
        required={"software","version","model_contract","operation","utc_created","config","config_sha256",
                  "seed","python","numpy","scipy","matplotlib","platform","machine","processor",
                  "environment","source_sha256","artifacts_sha256","equilibrium_computed"}
        missing_fields=required-set(record)
        if missing_fields:raise ValueError(f"missing manifest fields: {sorted(missing_fields)}")
        if type(record.get("manifest_schema",1)) is not int or record.get("manifest_schema",1)!=1:
            raise ValueError("unsupported manifest schema")
        if record["software"]!="EntrySignalLab" or record["model_contract"]!="piecewise-demand-v1":
            raise ValueError("unknown software or model contract")
        if not isinstance(record["version"],str) or not re.fullmatch(r"\d+\.\d+\.\d+",record["version"]):
            raise ValueError("version must be a three-component version string")
        if not isinstance(record["operation"],str) or not record["operation"]:
            raise ValueError("operation must be a nonempty string")
        if not isinstance(record["utc_created"],str) or datetime.fromisoformat(record["utc_created"]).tzinfo is None:
            raise ValueError("utc_created must be a timezone-aware ISO timestamp")
        if isinstance(record["seed"],bool) or not isinstance(record["seed"],int) or record["seed"]<0:
            raise ValueError("seed must be a nonnegative integer")
        if not isinstance(record["config"],dict) or not isinstance(record["environment"],dict):
            raise ValueError("config and environment must be objects")
        if record["equilibrium_computed"] is not False:
            raise ValueError("this model does not compute equilibria")
        for field in ["python","numpy","scipy","matplotlib","platform","machine","processor"]:
            if not isinstance(record[field],str):raise ValueError(f"{field} must be a string")
        for field in ["artifacts_sha256","source_sha256"]:
            mapping=record.get(field)
            if not isinstance(mapping,dict) or not all(isinstance(k,str) and isinstance(v,str) and re.fullmatch(r"[0-9a-f]{64}",v) for k,v in mapping.items()):
                raise ValueError(f"{field} must map paths to SHA-256 hexadecimal strings")
        if not record["source_sha256"]:raise ValueError("source_sha256 must not be empty")
        if not isinstance(record["config_sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",record["config_sha256"]):
            raise ValueError("config_sha256 must be a SHA-256 hexadecimal string")
        artifacts=record["artifacts_sha256"]
        if canonical_hash(record["config"])!=record["config_sha256"]:errors.append("configuration hash mismatch")
        actual={str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p!=root/"manifest.json"}
        missing=set(artifacts)-actual;extra=actual-set(artifacts)
        errors.extend(f"missing artifact: {n}" for n in sorted(missing))
        errors.extend(f"unexpected artifact: {n}" for n in sorted(extra))
        for name,expected in artifacts.items():
            path=(root/name).resolve()
            if not path.is_relative_to(root) or Path(name).is_absolute():errors.append(f"unsafe artifact path: {name}");continue
            if not path.is_file() or sha256(path)!=expected:errors.append(f"artifact hash mismatch: {name}")
        if "config.json" in artifacts:
            archived=read_json(root/"config.json")
            if canonical_hash(archived)!=canonical_hash(record["config"]):errors.append("config.json disagrees with manifest configuration")
        if expected_source is not None:
            source_verified=record["source_sha256"]==expected_source
            if not source_verified:errors.append("recorded source does not match the expected package")
    except (OSError,ValueError,TypeError,KeyError) as exc:
        errors.append(f"invalid manifest: {exc}")
    return {"valid":not errors,"errors":errors,"checked_artifacts":len(artifacts),"source_verified":source_verified,
            "scope":"Checks schema, exact archived file inventory, configuration and hashes. Source binding is checked only when an expected package is supplied. Does not establish authorship, authenticity, scientific validity or that recorded execution actually occurred."}

def validation_config(script):
    script=Path(script)
    return {"validator":script.name,"validator_sha256":sha256(script)}

def record_validation(directory,script,seed=0):
    """Bind independent-validator outputs to package and validator source."""
    return manifest(directory,validation_config(script),seed,"independent_validation")

def verify_validation(directory,script,expected_seed=None):
    report=verify_manifest(directory,current_source_hashes())
    if report["valid"]:
        record=read_json(Path(directory)/"manifest.json")
        if record["version"]!=__version__ or record["operation"]!="independent_validation" or record["config"]!=validation_config(script):
            report["errors"].append("validation receipt does not match current version and validator")
            report["valid"]=False
        if expected_seed is not None and record['seed']!=expected_seed:
            report['errors'].append('validation seed disagrees with release contract')
            report['valid']=False
    return report

def test_evidence_config(runner,test_directory):
    """Bind all test source files and the runner, independently of package hashes."""
    test_directory=Path(test_directory)
    sources={str(p.relative_to(test_directory)):sha256(p) for p in sorted(test_directory.rglob('*.py'))}
    if not sources:raise ValueError('test suite source inventory must not be empty')
    return {'runner':Path(runner).name,'runner_sha256':sha256(runner),'test_suite_sha256':sources}

def record_test_evidence(directory,runner,test_directory):
    return manifest(directory,test_evidence_config(runner,test_directory),0,'unit_tests')

def verify_test_evidence(directory,runner,test_directory):
    """Check the test receipt, runner, suite, log and structured record.

    This validates correspondence, not that the recorded execution happened.
    """
    directory=Path(directory)
    report=verify_manifest(directory,current_source_hashes())
    if report['valid']:
        try:
            m=read_json(directory/'manifest.json');r=read_json(directory/'unit_tests.json')
            if m['version']!=__version__ or m['operation']!='unit_tests' or m['seed']!=0 or m['config']!=test_evidence_config(runner,test_directory):
                raise ValueError('test receipt does not match current version, runner and suite')
            if not isinstance(r,dict) or r.get('version')!=__version__ or r.get('source_sha256')!=current_source_hashes():
                raise ValueError('test record does not match current package and version')
            for key in ['discovered_tests','tests_run','failures','errors','skips']:
                if type(r.get(key)) is not int or r[key]<0:raise ValueError('invalid test count '+key)
            if r.get('successful') is not True or r['tests_run']<1 or r['tests_run']!=r['discovered_tests'] or r['failures'] or r['errors'] or r['skips']:
                raise ValueError('incomplete, skipped or failed release tests')
            text=(directory/'unit_tests.log').read_text()
            match=re.search(r'Ran (\d+) tests',text)
            if not match or int(match[1])!=r['tests_run'] or not text.rstrip().endswith('OK'):
                raise ValueError('test log disagrees with structured record')
        except (OSError,ValueError,TypeError,KeyError) as error:
            report['valid']=False;report['errors'].append('invalid test evidence: '+str(error))
    return report
