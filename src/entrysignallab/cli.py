"""Command line interface. MIT License."""
import argparse, json, sys
from pathlib import Path
from dataclasses import asdict
from .locking import DirectoryLock
from . import __version__
from .audit import source_audit
from .model import ModelParams, revenues, payoff, finite_float_text
from .solver import compare,compare_stability
from .workflow import load_config, write_json, manifest, verify_manifest, sweep, uncertainty, current_source_hashes
from .workflow import normalize_comparison,configured_feasibility,summarize_sweep,prepare_sweep,prepare_uncertainty
from .plots import write_csv, trajectories, profit_surface, sweep_plot, regime_plot, html_report, resolve_plot_settings
from .benchmark import run_benchmark, validate_benchmark

def control_float(token):
    try:return finite_float_text(token,'control')
    except ValueError as error:raise argparse.ArgumentTypeError(str(error)) from None

def prepare_directory(path):
    directory=Path(path)
    if directory.exists() and any(directory.iterdir()):raise ValueError("output directory must be empty; choose a new directory to preserve earlier runs")
    directory.mkdir(parents=True,exist_ok=True);return directory

def main(argv=None):
    parser=argparse.ArgumentParser(prog="entrysignal",description="Preannouncement and entry-timing analysis with explicit conditional controls")
    parser.add_argument("--version",action="version",version=__version__)
    sub=parser.add_subparsers(dest="command",required=True)
    for command in ["audit","optimize","sweep","uncertainty","reproduce"]:
        sp=sub.add_parser(command);sp.add_argument("--config",required=True);sp.add_argument("--out",required=True)
    for command in ['sweep','uncertainty']:sub.choices[command].add_argument('--resume',action='store_true',help='resume an incomplete source/config-matched checkpoint')
    ev=sub.add_parser("evaluate");ev.add_argument("--config",required=True);ev.add_argument("--strategy",choices=["RF","RL","DF","DL"],required=True)
    ev.add_argument("--delay",type=control_float,required=True);ev.add_argument("--announcement",type=control_float,default=0.)
    ev.add_argument('--allow-outside-bounds',action='store_true',help='diagnostic evaluation outside configured controls; mathematical domains remain required')
    bv=sub.add_parser("benchmark");bv.add_argument("--out",required=True);bv.add_argument("--seed",type=int,default=104)
    bv.add_argument("--accuracy-cases",type=int,default=80);bv.add_argument("--repeats",type=int,default=5);bv.add_argument("--grid-points",type=int,default=201)
    vf=sub.add_parser("verify");vf.add_argument("directory");vf.add_argument("--check-source",action="store_true",help="also bind recorded hashes to this installed package")
    args=parser.parse_args(argv)
    try:
        if args.command=="verify":
            report=verify_manifest(args.directory,current_source_hashes() if args.check_source else None);print(json.dumps(report,indent=2));return 0 if report["valid"] else 2
        if args.command=="benchmark":
            validate_benchmark(args.seed,args.accuracy_cases,args.repeats,args.grid_points)
            with DirectoryLock(args.out):
                directory=prepare_directory(args.out)
                report=run_benchmark(directory,args.seed,args.accuracy_cases,args.repeats,args.grid_points)
                manifest(directory,{"seed":args.seed,"accuracy_cases":args.accuracy_cases,"repeats":args.repeats,"grid_points":args.grid_points},args.seed,"benchmark")
                print(json.dumps({"integration_pass":report["integration_pass"],"max_absolute_integration_error":report["max_absolute_integration_error"],"output":str(directory)},indent=2));return 0
        config,p,bounds,rival,seed=load_config(args.config)
        if config.get("stability") is not None and args.command not in ["optimize","reproduce"]:raise ValueError("stability requires optimize or reproduce")
        options=normalize_comparison(config.get('comparison'));policy=config.get('on_error','raise')
        if args.command=="evaluate":
            feasibility=configured_feasibility(p,bounds,rival,args.strategy,args.delay,args.announcement)
            if not feasibility['within_configured_bounds'] and not args.allow_outside_bounds:
                raise ValueError('controls are outside configured bounds; use --allow-outside-bounds for diagnostic evaluation: '+json.dumps(feasibility['bound_violations']))
            rx,ry=revenues(p,args.strategy,args.delay,args.announcement)
            print(json.dumps({"strategy":args.strategy,'delay':args.delay,'announcement':args.announcement,
                "revenue_x":rx,"revenue_y":ry,"payoff_x":payoff(p,args.strategy,args.delay,args.announcement),**feasibility},indent=2,allow_nan=False));return 0
        # Validate the complete experiment before writing any files.
        audit=source_audit(p) if args.command=="audit" else None
        comparison=compare(p,bounds,rival,**options) if args.command in ["optimize","reproduce"] else None
        sweep_rows=None
        if args.command in ["sweep","uncertainty"]:
            from .batch import run_batch
            if args.command=="sweep":meta,tasks=prepare_sweep(p,bounds,rival,config["axes"],options,policy,config.get("batch"))
            else:
                spec=config["uncertainty"]
                if not isinstance(spec,dict) or set(spec)-{"ranges","samples","marginals","correlation","constraints","constraint_mode","max_draw_attempts"}:raise ValueError("unknown uncertainty keys")
                meta,tasks=prepare_uncertainty(p,bounds,rival,spec.get("ranges",{}),spec.get("samples",100),seed,options,policy,config.get("batch"),**{k:v for k,v in spec.items() if k not in ["ranges","samples"]})
            with DirectoryLock(args.out) as lease:
                summary=run_batch(args.out,p,bounds,rival,meta,tasks,config,args.resume,lock=lease)
                directory=Path(args.out)
                if args.command=="sweep":
                    if meta["requested_cases"]<=10000:
                        import sqlite3
                        from contextlib import closing
                        with closing(sqlite3.connect((directory/"checkpoint.sqlite").resolve().as_uri()+"?mode=ro",uri=True)) as db:
                            rows=[row for payload, in db.execute("SELECT payload FROM cases ORDER BY case_index") for row in json.loads(payload)["rows"]]
                        if len(config["axes"])==1:sweep_plot(directory,rows,next(iter(config["axes"])),options["outside_option"])
                        elif len(config["axes"])==2:regime_plot(directory,rows,config["axes"])
                    else:write_json(directory/"plot_status.json",{"status":"skipped","reason":"More than 10000 cases; inspect CSV or create a smaller disclosed plot experiment."})
                manifest(directory,config,seed,args.command)
                print(json.dumps({"operation":args.command,"output":str(directory),"run_status":summary["run_status"],"equilibrium_computed":False},indent=2));return 0
        audit_status=None
        if args.command=="reproduce":
            try:
                audit=source_audit(p);audit_status={'status':'evaluated'}
            except ValueError as error:
                audit_status={'status':'skipped','reason':str(error)}
        plot_settings=resolve_plot_settings(p,bounds,rival,config.get("plot")) if args.command=="reproduce" else None
        stability=None
        if config.get("stability") is not None:
            spec=config["stability"]
            if not isinstance(spec,dict) or set(spec)-{"factors"}:raise ValueError("stability accepts only factors")
            if args.command not in ["optimize","reproduce"]:raise ValueError("stability requires optimize or reproduce")
            stability=compare_stability(p,bounds,rival,options,spec.get("factors",[1,2,4]))
        with DirectoryLock(args.out):
            directory=prepare_directory(args.out)
            write_json(directory/"config.json",config)
            if stability:write_json(directory/"stability.json",stability)
            if audit_status:write_json(directory/'source_audit_status.json',audit_status)
            if audit:write_json(directory/"source_audit.json",audit)
            if comparison:
                write_json(directory/"comparison.json",comparison);write_csv(directory/"optima.csv",comparison["results"])
            if args.command=="reproduce":
                write_json(directory/"plot_settings.json",plot_settings)
                trajectories(directory,p,controls=plot_settings["trajectory_controls"])
                profit_surface(directory,p,bounds,plot_settings);html_report(directory,comparison,audit,plot_settings,stability=stability)
            manifest(directory,config,seed,args.command)
            run_status='complete'
            print(json.dumps({"operation":args.command,"output":str(directory),'run_status':run_status,"equilibrium_computed":False},indent=2));return 0
    except (ValueError,TypeError,KeyError,OSError,OverflowError,RuntimeError) as e:
        print(f"entrysignal: {e}",file=sys.stderr);return 2

if __name__=="__main__":raise SystemExit(main())
