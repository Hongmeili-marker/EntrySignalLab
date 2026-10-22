"""Regression tests for the frozen v0.4.0 audit counterexamples."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest,json,io,contextlib
from entrysignallab import ModelParams,DecisionBounds,payoff,optimize
from entrysignallab.audit import source_audit
from entrysignallab.cli import main
from entrysignallab.workflow import (write_json,read_json,record_test_evidence,verify_test_evidence,
    current_source_hashes,manifest,verify_manifest,record_validation,verify_validation)
from entrysignallab import __version__

class FixedControlTests(unittest.TestCase):
    def params(self):
        return ModelParams(growth=1e-308,network=1e308,growth_end=1e308,horizon=1e308,
                           quality_ratio=1e-308,margin_x=1e-308,margin_y=0)
    def test_fixed_zero_does_not_need_gradient(self):
        p=self.params();r=optimize(p,'RL',DecisionBounds(delay_lower=1e307,delay_upper=1e307,announcement_upper=0),0)
        self.assertAlmostEqual(r['payoff'],.405/1.1,places=11)
        self.assertEqual(r['announcement_stationarity_residual'],0)
        self.assertEqual(r['announcement_stationarity_scaled_residual'],0)
    def test_upper_bound_has_no_positive_kkt_violation(self):
        r=optimize(ModelParams(),'RF')
        self.assertEqual(r['announcement_active'],'upper')
        self.assertEqual(r['announcement_stationarity_scaled_residual'],0)
    def test_interior_scale_free_residual(self):
        r=optimize(ModelParams(announcement_cost=.0002),'RF')
        self.assertEqual(r['announcement_active'],'interior')
        self.assertLess(r['announcement_stationarity_scaled_residual'],1e-10)
    def test_irrelevant_intensity_residual(self):
        r=optimize(ModelParams(network=0),'RL')
        self.assertEqual(r['announcement_stationarity_scaled_residual'],0)
    def test_raw_overflow_is_explicit(self):
        from entrysignallab.solver import announcement_stationarity
        r=announcement_stationarity(self.params(),'RL',1e307,0,'lower')
        self.assertIsNone(r['raw']);self.assertGreater(r['log'],709)
        self.assertEqual(r['representation'],'outside_float_range');self.assertEqual(r['scaled'],1)

class SourceAuditRangeTests(unittest.TestCase):
    def test_underflow_is_controlled(self):
        with self.assertRaisesRegex(ValueError,'floating-point range'):source_audit(ModelParams(growth=1e-200,network=1e-200))
    def test_overflow_is_controlled(self):
        with self.assertRaisesRegex(ValueError,'floating-point range'):source_audit(ModelParams(growth=1e200,network=1e200))
    def test_cli_underflow_no_traceback_no_output(self):
        with TemporaryDirectory() as td:
            d=Path(td);write_json(d/'c.json',{'params':{'growth':1e-200,'network':1e-200}});error=io.StringIO()
            with contextlib.redirect_stderr(error):code=main(['audit','--config',str(d/'c.json'),'--out',str(d/'out')])
            self.assertEqual(code,2);self.assertNotIn('Traceback',error.getvalue());self.assertFalse((d/'out').exists())
    def test_reproduce_records_skip_reason(self):
        with TemporaryDirectory() as td:
            d=Path(td);write_json(d/'c.json',{'params':{'growth':1e-200,'network':1e-200}})
            with patch('entrysignallab.cli.trajectories'),patch('entrysignallab.cli.profit_surface'),patch('entrysignallab.cli.html_report'),contextlib.redirect_stdout(io.StringIO()):
                code=main(['reproduce','--config',str(d/'c.json'),'--out',str(d/'out')])
            self.assertEqual(code,0);r=read_json(d/'out/source_audit_status.json')
            self.assertEqual(r['status'],'skipped');self.assertIn('floating-point range',r['reason'])
            self.assertTrue(verify_manifest(d/'out',current_source_hashes())['valid'])

class TestReceiptTests(unittest.TestCase):
    def setup_record(self,d):
        suite=d/'suite';suite.mkdir();(suite/'test_one.py').write_text('pass\n');runner=d/'runner.py';runner.write_text('pass\n');out=d/'out';out.mkdir()
        write_json(out/'unit_tests.json',{'version':__version__,'discovered_tests':1,'tests_run':1,'successful':True,'failures':0,'errors':0,'skips':0,'source_sha256':current_source_hashes()})
        (out/'unit_tests.log').write_text('Ran 1 tests in 0.001s\n\nOK\n');record_test_evidence(out,runner,suite)
        return suite,runner,out
    def test_valid_receipt(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));self.assertTrue(verify_test_evidence(o,r,s)['valid'])
    def test_changed_suite_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));(s/'test_one.py').write_text('raise Exception()\n');self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_added_test_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));(s/'test_two.py').write_text('pass\n');self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_removed_test_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));(s/'test_one.py').unlink();self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_changed_runner_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));r.write_text('raise Exception()\n');self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_changed_log_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));(o/'unit_tests.log').write_text('Ran 1 tests\nFAILED\n');self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_wrong_test_version_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));j=read_json(o/'unit_tests.json');j['version']='0.4.0';write_json(o/'unit_tests.json',j);record_test_evidence(o,r,s)
            self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_skips_rejected_even_when_resealed(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));j=read_json(o/'unit_tests.json');j['skips']=1;write_json(o/'unit_tests.json',j);record_test_evidence(o,r,s)
            self.assertFalse(verify_test_evidence(o,r,s)['valid'])
    def test_empty_suite_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));(s/'test_one.py').unlink()
            with self.assertRaisesRegex(ValueError,'empty'):record_test_evidence(o,r,s)
    def test_float_schema_rejected(self):
        with TemporaryDirectory() as td:
            s,r,o=self.setup_record(Path(td));j=read_json(o/'manifest.json');j['manifest_schema']=1.;write_json(o/'manifest.json',j)
            self.assertFalse(verify_manifest(o)['valid'])
    def test_wrong_validation_seed_rejected(self):
        with TemporaryDirectory() as td:
            d=Path(td);out=d/'out';out.mkdir();script=d/'v.py';script.write_text('pass\n');write_json(out/'x.json',{});record_validation(out,script,7)
            self.assertTrue(verify_validation(out,script,7)['valid']);self.assertFalse(verify_validation(out,script,8)['valid'])
