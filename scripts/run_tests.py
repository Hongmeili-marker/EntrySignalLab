"""Run the discovered suite and persist complete structured/text test evidence."""
from pathlib import Path
import unittest,argparse,io,json
from entrysignallab import __version__
from entrysignallab.workflow import current_source_hashes,write_json,record_test_evidence

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();root=Path(__file__).resolve().parents[1]
    args.out.mkdir(parents=True,exist_ok=True)
    suite=unittest.defaultTestLoader.discover(str(root/'tests'));expected=suite.countTestCases();stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    log=stream.getvalue();(args.out/'unit_tests.log').write_text(log)
    record={'version':__version__,'discovered_tests':expected,'tests_run':result.testsRun,'successful':result.wasSuccessful(),
        'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),'source_sha256':current_source_hashes()}
    write_json(args.out/'unit_tests.json',record);print(json.dumps(record,indent=2))
    if not result.wasSuccessful() or result.testsRun!=expected:raise SystemExit('Incomplete or failed test suite')
    record_test_evidence(args.out,Path(__file__),root/'tests')

if __name__=="__main__":main()
