"""Reproduce the visualization and CLI exception findings with the installed release."""
from pathlib import Path
import argparse,json,subprocess,sys,csv
ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);args=ap.parse_args();root=Path(args.out).resolve()
if root.exists() and any(root.iterdir()):raise SystemExit('Choose a new empty audit output directory')
root.mkdir(parents=True,exist_ok=True)
def call(argv,stem):
    r=subprocess.run([sys.executable,'-m','entrysignallab.cli',*argv],capture_output=True,text=True)
    (root/(stem+'_stdout.log')).write_text(r.stdout);(root/(stem+'_stderr.log')).write_text(r.stderr)
    return r.returncode
p=root/'plot_config.json';p.write_text(json.dumps({'bounds':{'announcement_upper':.1}}))
plotcode=call(['reproduce','--config',str(p),'--out',str(root/'plot')],'plot')
rows=list(csv.DictReader((root/'plot/demand_trajectories.csv').open()))
tiny=root/'tiny_config.json';tiny.write_text(json.dumps({'params':{'announcement_cost':1e-100},'bounds':{'announcement_upper':None}}))
tinycode=call(['optimize','--config',str(tiny),'--out',str(root/'tiny')],'tiny')
invalidcode=call(['benchmark','--grid-points','1','--out',str(root/'invalid')],'invalid')
results={'plot_exit':plotcode,'configured_cap':.1,'R_plot_intensities':sorted(set(float(r['announcement']) for r in rows if r['strategy'].startswith('R'))),'out_of_bound_rows':sum(float(r['announcement'])>.1 for r in rows),'tiny_cost_exit':tinycode,'tiny_cost_traceback_present':'Traceback' in (root/'tiny_stderr.log').read_text(),'invalid_benchmark_exit':invalidcode,'invalid_benchmark_created_directory':(root/'invalid').exists()}
(root/'workflow_probe.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))

from entrysignallab.workflow import record_validation
record_validation(root,Path(__file__),seed=104)
