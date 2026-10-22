"""Run all shipped experiments without overwriting existing outputs. MIT License."""
from pathlib import Path
import argparse, subprocess, sys
from entrysignallab.workflow import read_json

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--out",default="results");args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];out=Path(args.out).resolve()
    contract=read_json(root/'scripts/release_contract.json')
    for name in contract['experiments']:
        spec=contract['experiment_specs'][name];command=spec['operation']
        if command=='unit_conversion':
            argv=[sys.executable,str(root/'scripts/unit_invariance.py'),'--out',str(out/name)]
        elif command=='workflow_benchmark':
            argv=[sys.executable,str(root/'scripts/workflow_performance.py'),'--config',str(root/spec['config_path']),'--out',str(out/name)]
        elif command=='benchmark':
            argv=[sys.executable,'-m','entrysignallab.cli','benchmark','--out',str(out/name)]
            for key,value in spec['config'].items():argv.extend(['--'+key.replace('_','-'),str(value)])
        else:
            argv=[sys.executable,'-m','entrysignallab.cli',command,'--config',str(root/spec['config_path']),'--out',str(out/name)]
        subprocess.run(argv,check=True)
    for name in contract['experiments']:
        subprocess.run([sys.executable,"-m","entrysignallab.cli","verify",str(out/name),"--check-source"],check=True)

if __name__=="__main__":main()
