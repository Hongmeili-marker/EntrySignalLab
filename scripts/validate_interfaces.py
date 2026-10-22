"""Independent interface selection and feasible-domain accounting references."""
from pathlib import Path
from decimal import Decimal
from dataclasses import asdict
import argparse,csv,json,subprocess,sys,hashlib
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,compare,optimize
from entrysignallab.workflow import sweep,uncertainty,write_json,record_validation,verify_manifest,current_source_hashes

STRATEGIES=('RF','RL','DF','DL')
def reference_labels(results,tolerance,outside):
    # Independent Decimal selection from returned payoff values; not a payoff oracle.
    vals={r['strategy']:Decimal.from_float(r['payoff']) for r in results}
    best=max(vals.values());tol=Decimal.from_float(float(tolerance));ref=Decimal.from_float(float(outside))
    labels=[s for s in STRATEGIES if best-vals[s]<=tol]
    preferred=labels if best>ref+tol else ['no_entry'] if best<ref-tol else labels+['no_entry']
    return labels,preferred

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    if args.out.exists():raise SystemExit('Choose a fresh interface validation directory')
    args.out.mkdir(parents=True);checks=[]
    def check(kind,name,actual,expected):checks.append({'kind':kind,'name':name,'actual':actual,'reference':expected,'pass':actual==expected})
    def cli(name,operation,cfg,extra=()):
        path=args.out/(name+'.json');write_json(path,cfg);out=args.out/name
        command=[sys.executable,'-m','entrysignallab.cli',operation,'--config',str(path),*extra]
        if operation!='evaluate':command+=['--out',str(out)]
        proc=subprocess.run(command,capture_output=True,text=True)
        write_json(args.out/(name+'_execution.json'),{'command':command,'exit':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
        return proc,out
    b=DecisionBounds(scouting_points=21)
    params=[ModelParams(),ModelParams(margin_x=1e-10,margin_y=1e-10),ModelParams(growth=0),ModelParams(growth_end=.01,horizon=.02)]
    policies=[{'tie_tolerance':0.,'outside_option':0.},{'tie_tolerance':1e-8,'outside_option':0.},{'tie_tolerance':0.,'outside_option':1.}]
    for i,p in enumerate(params):
        for j,opts in enumerate(policies):
            name=f'policy_{i}_{j}';r=compare(p,b,**opts);expected=reference_labels(r['results'],opts['tie_tolerance'],opts['outside_option'])
            check('comparison_policy',name+'_api',[r['co_best'],r['preferred_with_outside_option']],list(expected))
            proc,out=cli(name,'optimize',{'params':asdict(p),'bounds':asdict(b),'comparison':opts})
            if proc.returncode!=0:raise RuntimeError(proc.stderr)
            c=json.loads((out/'comparison.json').read_text());check('comparison_policy',name+'_cli',[c['co_best'],c['preferred_with_outside_option']],list(expected))
            rival=min(.15,p.growth_end);rows=sweep(p,b,rival,{'network':[p.network]},opts)
            check('comparison_policy',name+'_sweep',[rows[0]['co_best'].split('|'),rows[0]['outside_option_preferred'].split('|')],list(expected))
            u=uncertainty(p,b,rival,{'network':[p.network,p.network]},n=1,comparison=opts)
            check('comparison_policy',name+'_uncertainty',[u['rows'][0]['co_best'].split('|'),u['rows'][0]['outside_option_preferred'].split('|')],list(expected))
    cfg=json.loads((Path(__file__).resolve().parents[1]/'examples/bounded_evaluation.json').read_text())
    # Independently evaluate inequalities for eight controls, then exercise both CLI modes.
    controls=[('RL',.22,.005),('RL',.1,.005),('RL',.22,2.),('RL',.1,2.),('DF',.15,0.),('DF',.1,0.),('DL',.2,0.),('RF',.15,.02)]
    for i,(st,t,d) in enumerate(controls):
        feasible=(.2<=t<=.25 if st.endswith('L') else t==.15) and (d<=.01 if st.startswith('R') else d==0)
        extra=['--strategy',st,'--delay',str(t),'--announcement',str(d)]
        proc,_=cli('evaluate_'+str(i),'evaluate',cfg,extra)
        check('configured_evaluation',f'default_{i}',proc.returncode,0 if feasible else 2)
        proc,_=cli('diagnostic_'+str(i),'evaluate',cfg,extra+['--allow-outside-bounds'])
        record=json.loads(proc.stdout) if proc.returncode==0 else {}
        check('configured_evaluation',f'diagnostic_{i}',[proc.returncode,record.get('within_configured_bounds'),record.get('diagnostic_only')],[0,feasible,not feasible])
    for i,extra in enumerate([['--strategy','RL','--delay','1'],['--strategy','DL','--delay','.2','--announcement','1']]):
        proc,_=cli('global_reject_'+str(i),'evaluate',cfg,extra+['--allow-outside-bounds'])
        check('configured_evaluation','global_reject_'+str(i),proc.returncode,2)
    p=params[-1]
    for st in STRATEGIES:
        actual=optimize(p,st,b)['delay'];check('default_rival',st+'_domain',0<=actual<=p.growth_end,True)
    for st in ['RL','DL']:check('default_rival',st+'_irrelevant',optimize(p,st,b,rival_delay=10),optimize(p,st,b))
    for operation,cfgname in [('sweep','sweep_failure_record'),('uncertainty','uncertainty_failure_record')]:
        cfg=json.loads((Path(__file__).resolve().parents[1]/'examples'/(cfgname+'.json')).read_text());proc,out=cli(cfgname,operation,cfg)
        check('batch_accounting',operation+'_exit',proc.returncode,0)
        summary=json.loads((out/(operation+'_summary.json')).read_text());rows=list(csv.DictReader((out/(operation+'.csv')).open()))
        if operation=='sweep':
            requested=3;failed=1;completed=2;actual=[summary['requested_cases'],summary['failed_cases'],summary['completed_cases']]
        else:
            requested=20
            words=[int.from_bytes(hashlib.sha256(b'parameter:growth_end').digest()[i:i+4],'little') for i in range(0,32,4)]
            draws=[.1*(1-(u:=float(np.random.Generator(np.random.PCG64(np.random.SeedSequence([104,i,0,*words]))).random())))+.2*u for i in range(requested)]
            failed=int(sum(v<.15 for v in draws));completed=requested-failed
            actual=[summary['requested_samples'],summary['failed_samples'],summary['completed_samples']]
            check('batch_accounting','frequency_count_total',sum(x['count'] for x in summary['summary'].values()),requested)
            check('batch_accounting','requested_denominator',summary['summary']['invalid_configuration']['frequency'],failed/requested)
            valid=sum(x['valid_sample_frequency'] or 0 for x in summary['summary'].values());check('batch_accounting','valid_denominator',abs(valid-1)<1e-14,True)
        check('batch_accounting',operation+'_counts',actual,[requested,failed,completed])
        check('batch_accounting',operation+'_four_null_rows',sum(r['batch_status']=='invalid_configuration' and r['payoff']=='' and r['outside_option_preferred']=='' for r in rows),4*failed)
        check('batch_accounting',operation+'_manifest',verify_manifest(out,current_source_hashes())['valid'],True)
        cfg['on_error']='raise';proc,out=cli(cfgname+'_strict',operation,cfg);check('batch_accounting',operation+'_preflight',[proc.returncode,out.exists()],[2,False])
    rows=sweep(ModelParams(margin_x=100,network=0),DecisionBounds(announcement_upper=0,scouting_points=21),.15,{'growth':[.1,1e308]},on_error='record')
    check('batch_accounting','actual_overflow_records',sum(r['batch_status']=='numerical_error' and r['payoff'] is None for r in rows),4)
    all_failed=uncertainty(ModelParams(),b,.15,{'growth_end':[.1,.1]},n=2,on_error='record')
    check('batch_accounting','all_failed_conditional',[all_failed['run_status'],all(x['valid_sample_frequency'] is None for x in all_failed['summary'].values())],['all_failed',True])
    report={'checks':len(checks),'comparison_policy_checks':sum(x['kind']=='comparison_policy' for x in checks),'configured_evaluation_checks':sum(x['kind']=='configured_evaluation' for x in checks),'default_rival_checks':sum(x['kind']=='default_rival' for x in checks),'batch_accounting_checks':sum(x['kind']=='batch_accounting' for x in checks),'all_pass':all(x['pass'] for x in checks),'scope':'Independent Decimal selection from observed payoffs and independent feasible-domain/RNG accounting, with installed-wheel CLI calls. This verifies interface policy and batch accounting, not an independent numerical payoff oracle or arbitrary-parameter certification.'}
    write_json(args.out/'interfaces_results.json',checks);write_json(args.out/'interfaces_summary.json',report);record_validation(args.out,Path(__file__),104);print(report)
    if not report['all_pass']:raise SystemExit('Interface validation failed')
if __name__=='__main__':main()
