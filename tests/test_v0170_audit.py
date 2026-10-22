"""Regressions for independently specified identities and readable coordinates."""
from pathlib import Path
from fractions import Fraction
import json, subprocess, sys, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0170 import plot_snapshot
from entrysignallab import ModelParams
from entrysignallab.audit import source_audit
from entrysignallab.workflow import verify_manifest,current_source_hashes


def identity(p):
    return next(x for x in source_audit(p)['checks'] if x['id']=='DF_INTEGRAL_IDENTITY')


class SourceIdentityRegression(unittest.TestCase):
    def test_small_growth_cannot_prove_identity(self):
        for s in [1e-11,1e-20,1e-100]:
            for h in [.3,.001]:
                with self.subTest(growth=s,H=h):
                    result=identity(ModelParams(growth=s,growth_end=h))
                    self.assertFalse(result['pass'])
                    self.assertGreater(result['from_demand'],0)
                    self.assertLess(result['from_printed_eq15'],0)

    def test_small_maturity_cannot_prove_identity(self):
        for h in [1e-11,1e-20,1e-100]:
            with self.subTest(H=h):self.assertFalse(identity(ModelParams(growth_end=h))['pass'])

    def test_exact_difference_is_positive(self):
        for s,h in [(1e-100,.3),(.1,1e-100),(.1,.3),(1e100,.3)]:
            S,H=Fraction(s),Fraction(h)
            gap=S*H*(2-H)/16-(-S*H*H/16)
            self.assertEqual(gap,S*H/8)
            self.assertGreater(gap,0)
            self.assertFalse(identity(ModelParams(growth=s,growth_end=h))['pass'])

    def test_printed_underflow_retains_analytic_decision(self):
        result=identity(ModelParams(growth_end=1e-200))
        self.assertEqual(result['from_printed_eq15'],0)
        self.assertGreater(result['from_demand'],0)
        self.assertFalse(result['pass'])
        self.assertEqual(result['decision_basis'],'analytic_nonidentity')
        self.assertTrue(result['numerical_values_are_descriptive'])

    def test_default_source_flags_keep_interpretation(self):
        results=source_audit(ModelParams())['checks']
        self.assertEqual(len(results),6)
        self.assertTrue(all(x['pass'] is False for x in results))
        self.assertAlmostEqual(identity(ModelParams())['normalized_discrepancy'],2/1.7)

    def cli(self,command):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);config=root/'config.json';folder=root/'out'
            config.write_text(json.dumps({'params':{'growth':1e-11}}))
            result=subprocess.run([sys.executable,'-m','entrysignallab.cli',command,'--config',str(config),'--out',str(folder)],capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stderr)
            record=json.loads((folder/'source_audit.json').read_text())
            item=next(x for x in record['checks'] if x['id']=='DF_INTEGRAL_IDENTITY')
            self.assertFalse(item['pass'])
            self.assertTrue(verify_manifest(folder,current_source_hashes())['valid'])
            if command=='reproduce':self.assertIn('analytic_nonidentity',(folder/'report.html').read_text())

    def test_audit_cli_rejects_false_identity(self):self.cli('audit')
    def test_html_reproduction_preserves_analytic_basis(self):self.cli('reproduce')


class FigureCoordinateRegression(unittest.TestCase):
    def verify_axes(self,xs,ys):
        axes=plot_snapshot(xs,ys)
        for name in ['x','y']:
            axis=axes[name]
            with self.subTest(axis=name):
                self.assertTrue(axis['roundtrip_pass'],axis)
                self.assertTrue(axis['labels_distinguish_positions'],axis)
                self.assertTrue(axis['scale_annotation_present'],axis)
        if 'sampled_points' in axes:
            self.assertTrue(axes['sampled_points']['positions_exact'])
            self.assertTrue(axes['sampled_points']['visible'])
        return axes

    def test_small_x(self):self.verify_axes([.0001,.0002,.0003],[.5,1.])
    def test_small_y(self):self.verify_axes([.5,1.],[.0001,.0002,.0003])
    def test_tiny_x(self):self.verify_axes([1e-9,2e-9,3e-9],[.5,1.])
    def test_tiny_y(self):self.verify_axes([.5,1.],[1e-9,2e-9,3e-9])
    def test_large_x(self):self.verify_axes([1e12,2e12,3e12],[.5,1.])
    def test_large_y(self):self.verify_axes([.5,1.],[1e12,2e12,3e12])
    def test_shifted_x(self):self.verify_axes([1e9,1e9+.001,1e9+.002],[.5,1.])
    def test_shifted_y(self):self.verify_axes([.5,1.],[1e9,1e9+.001,1e9+.002])
    def test_ordinary_axes(self):self.verify_axes([.1,.2,.3],[.5,1.])
    def test_singleton_x(self):self.verify_axes([.0001],[.5,1.])
    def test_singleton_y(self):self.verify_axes([.5,1.],[.0001])
    def test_singleton_both(self):self.verify_axes([.0001],[.0002])

    def test_export_contains_rendered_coordinate_labels(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)/'figure';axes=plot_snapshot([.0001,.0002,.0003],[.5,1.],folder)
            text=(folder/'strategy_regions.svg').read_text()
            self.assertTrue(axes['x']['roundtrip_pass'])
            self.assertNotEqual(axes['x']['distinct_labels'],1)
            self.assertIn('10^',text)
            for axis in axes.values():
                for label in axis['labels']:self.assertIn(label,text)
            for suffix in ['png','pdf','svg']:self.assertGreater((folder/('strategy_regions.'+suffix)).stat().st_size,0)


if __name__=='__main__':unittest.main()
