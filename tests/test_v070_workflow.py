"""Interface policy, configured feasibility and transparent batch outcomes."""
import contextlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,compare
from entrysignallab.cli import main
from entrysignallab.workflow import (normalize_comparison,normalize_error_policy,configured_feasibility,
    sweep,summarize_sweep,uncertainty,load_config,verify_manifest,current_source_hashes)
from entrysignallab.plots import sweep_plot,regime_plot,html_report

class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.p=ModelParams();self.b=DecisionBounds(scouting_points=21);self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def cli(self,op,config=None,*extra):
        cfg=self.root/'config.json';cfg.write_text(json.dumps(config or {}));out=self.root/'output'
        args=[op,'--config',str(cfg),*extra]
        if op!='evaluate':args+=['--out',str(out)]
        stdout=io.StringIO();stderr=io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):code=main(args)
        return code,stdout.getvalue(),stderr.getvalue(),out
    def test_default_policy(self):self.assertEqual(normalize_comparison(),{'tie_tolerance':1e-8,'outside_option':0.})
    def test_custom_policy(self):self.assertEqual(normalize_comparison({'tie_tolerance':0,'outside_option':-.2}),{'tie_tolerance':0.,'outside_option':-.2})
    def test_policy_rejects_unknown(self):
        with self.assertRaises(ValueError):normalize_comparison({'relative_tolerance':.1})
    def test_policy_rejects_negative_tolerance(self):
        with self.assertRaises(ValueError):normalize_comparison({'tie_tolerance':-1})
    def test_policy_rejects_bool(self):
        for key in ['tie_tolerance','outside_option']:
            with self.subTest(key=key),self.assertRaises(ValueError):normalize_comparison({key:True})
    def test_policy_rejects_nonfinite(self):
        for v in [float('nan'),float('inf')]:
            with self.subTest(value=v),self.assertRaises(ValueError):normalize_comparison({'outside_option':v})
    def test_policy_rejects_nonobject(self):
        with self.assertRaises(ValueError):normalize_comparison([])
    def test_error_policy_rejects_unknown(self):
        with self.assertRaises(ValueError):normalize_error_policy('skip')
    def test_config_roundtrip(self):
        cfg=self.root/'cfg.json';cfg.write_text(json.dumps({'comparison':{'tie_tolerance':0,'outside_option':1},'on_error':'record'}));raw,*_=load_config(cfg)
        self.assertEqual(raw['comparison']['outside_option'],1);self.assertEqual(raw['on_error'],'record')
    def test_tiny_payoff_policy_changes_only_labels(self):
        p=ModelParams(margin_x=1e-10,margin_y=1e-10);a=compare(p,self.b);b=compare(p,self.b,tie_tolerance=0)
        self.assertEqual(len(a['co_best']),4);self.assertEqual(b['co_best'],['RF']);self.assertEqual(a['results'],b['results'])
    def test_cli_custom_matches_api(self):
        cfg={'params':{'margin_x':1e-10,'margin_y':1e-10},'bounds':{'scouting_points':21},'comparison':{'tie_tolerance':0,'outside_option':1e-11}}
        code,_,_,out=self.cli('optimize',cfg);self.assertEqual(code,0)
        self.assertEqual(json.loads((out/'comparison.json').read_text()),compare(ModelParams(**cfg['params']),self.b,**cfg['comparison']))
    def test_sweep_custom_matches_api(self):
        opts={'tie_tolerance':0,'outside_option':1.};rows=sweep(self.p,self.b,.15,{'network':[.85]},opts);r=compare(self.p,self.b,.15,**opts)
        self.assertEqual(rows[0]['co_best'],'|'.join(r['co_best']));self.assertEqual(rows[0]['outside_option_preferred'],'no_entry')
    def test_uncertainty_custom_matches_api(self):
        opts={'tie_tolerance':0,'outside_option':1.};r=uncertainty(self.p,self.b,.15,{'network':[.85,.85]},n=2,comparison=opts)
        self.assertEqual(r['outside_option_summary']['non_entry_preferred'],2);self.assertEqual(r['comparison'],opts)
    def test_short_h_default_all_strategies(self):
        p=ModelParams(growth_end=.01,horizon=.02)
        for st in ['RF','RL','DF','DL']:
            with self.subTest(strategy=st):self.assertIsNotNone(optimize(p,st,self.b)['payoff'])
    def test_short_h_api_cli_same_defaults(self):
        cfg={'params':{'growth_end':.01,'horizon':.02},'bounds':{'scouting_points':21}}
        code,_,_,out=self.cli('optimize',cfg);self.assertEqual(code,0);self.assertEqual(json.loads((out/'comparison.json').read_text()),compare(ModelParams(**cfg['params']),self.b))
    def test_follower_ignores_irrelevant_rival(self):
        for st in ['RL','DL']:
            with self.subTest(strategy=st):self.assertEqual(optimize(self.p,st,self.b,rival_delay=10),optimize(self.p,st,self.b))
    def test_first_explicit_invalid_rival_rejected(self):
        for st in ['RF','DF']:
            with self.subTest(strategy=st),self.assertRaises(ValueError):optimize(self.p,st,self.b,rival_delay=10)
    def test_follower_bounds_default_reject(self):
        code,out,err,_=self.cli('evaluate',{'bounds':{'delay_lower':.2,'delay_upper':.25}},'--strategy','RL','--delay','.1');self.assertEqual(code,2);self.assertEqual(out,'');self.assertIn('--allow-outside-bounds',err)
    def test_follower_bounds_diagnostic(self):
        code,out,_,_=self.cli('evaluate',{'bounds':{'delay_lower':.2,'delay_upper':.25}},'--strategy','RL','--delay','.1','--allow-outside-bounds');r=json.loads(out)
        self.assertEqual(code,0);self.assertTrue(r['diagnostic_only']);self.assertFalse(r['within_configured_bounds']);self.assertEqual(r['bound_violations'][0]['control'],'follower_delay')
    def test_announcement_cap_default_reject(self):
        code,*_=self.cli('evaluate',{'bounds':{'announcement_upper':.01}},'--strategy','RF','--delay','.15','--announcement','2');self.assertEqual(code,2)
    def test_fixed_rival_mismatch(self):
        r=configured_feasibility(self.p,self.b,.15,'DF',.1,0);self.assertEqual(r['bound_violations'][0]['control'],'fixed_rival_delay')
    def test_feasible_evaluation_flags(self):
        r=configured_feasibility(self.p,self.b,.15,'RL',.1,.1);self.assertTrue(r['within_configured_bounds']);self.assertFalse(r['diagnostic_only'])
    def test_diagnostic_still_rejects_global_delay(self):
        code,*_=self.cli('evaluate',{},'--strategy','RL','--delay','1','--allow-outside-bounds');self.assertEqual(code,2)
    def test_diagnostic_still_rejects_silent_announcement(self):
        code,*_=self.cli('evaluate',{},'--strategy','DL','--delay','.1','--announcement','1','--allow-outside-bounds');self.assertEqual(code,2)
    def test_sweep_joint_preflight_before_solver(self):
        with patch('entrysignallab.workflow.compare') as mock,self.assertRaises(ValueError):sweep(self.p,self.b,.15,{'growth_end':[.1,.2]})
        mock.assert_not_called()
    def test_uncertainty_joint_preflight_before_solver(self):
        with patch('entrysignallab.workflow.compare') as mock,self.assertRaises(ValueError):uncertainty(self.p,self.b,.15,{'growth_end':[.1,.2]})
        mock.assert_not_called()
    def test_horizon_preflight(self):
        with self.assertRaises(ValueError):sweep(self.p,self.b,.15,{'growth_end':[.3,.4],'horizon':[.35,.5]})
    def test_bounds_preflight(self):
        with self.assertRaises(ValueError):uncertainty(self.p,DecisionBounds(delay_upper=.25),.1,{'growth_end':[.2,.3]})
    def test_record_retains_four_null_failure_rows(self):
        rows=sweep(self.p,self.b,.15,{'growth_end':[.1,.2]},on_error='record');failed=rows[:4]
        self.assertEqual(len(rows),8);self.assertTrue(all(r['payoff'] is None and r['batch_status']=='invalid_configuration' and r['outside_option_preferred']=='' for r in failed))
    def test_record_summary_counts(self):
        r=summarize_sweep(sweep(self.p,self.b,.15,{'growth_end':[.1,.2,.3]},on_error='record'),on_error='record')
        self.assertEqual((r['requested_cases'],r['completed_cases'],r['failed_cases']),(3,2,1));self.assertEqual(r['run_status'],'partial_failure')
    def test_numerical_failure_distinct(self):
        with patch('entrysignallab.workflow.compare',side_effect=RuntimeError('optimizer did not converge')):rows=sweep(self.p,self.b,.15,{'network':[.1]},on_error='record')
        self.assertTrue(all(r['batch_status']=='numerical_error' and r['error_stage']=='optimization' for r in rows))
    def test_strict_numerical_error_propagates(self):
        with patch('entrysignallab.workflow.compare',side_effect=RuntimeError('optimizer did not converge')),self.assertRaises(RuntimeError):sweep(self.p,self.b,.15,{'network':[.1]})
    def test_record_invalid_shapes_still_rejected(self):
        for ranges in [{'network':[1]}, {'bad':[0,1]}, {'network':[1,0]}]:
            with self.subTest(ranges=ranges),self.assertRaises(ValueError):uncertainty(self.p,self.b,.15,ranges,on_error='record')
    def test_uncertainty_denominators_and_reproducibility(self):
        args=(self.p,self.b,.15,{'growth_end':[.1,.2]});a=uncertainty(*args,n=20,seed=104,on_error='record');b=uncertainty(*args,n=20,seed=104,on_error='record')
        self.assertEqual(a,b);self.assertEqual(sum(v['count'] for v in a['summary'].values()),20);self.assertEqual(len(a['rows']),80)
        self.assertEqual(a['completed_samples']+a['failed_samples'],20)
        self.assertAlmostEqual(sum(v['frequency'] for v in a['summary'].values()),1)
        self.assertAlmostEqual(sum(v['valid_sample_frequency'] or 0 for v in a['summary'].values()),1)
    def test_all_failed_has_no_conditional_frequencies(self):
        r=uncertainty(self.p,self.b,.15,{'growth_end':[.1,.1]},n=2,on_error='record');self.assertEqual(r['run_status'],'all_failed');self.assertTrue(all(v['valid_sample_frequency'] is None for v in r['summary'].values()))
    def test_unrankable_is_not_failure(self):
        p=ModelParams(announcement_cost=0,network=1);b=DecisionBounds(announcement_upper=None,delay_upper=.1,scouting_points=21)
        r=uncertainty(p,b,.15,{'network':[1,1]},n=1,on_error='record');self.assertEqual(r['summary']['unrankable']['count'],1);self.assertEqual(r['failed_samples'],0)
    def test_cli_preflight_creates_no_directory(self):
        code,_,_,out=self.cli('sweep',{'axes':{'growth_end':[.1,.2]}});self.assertEqual(code,2);self.assertFalse(out.exists())
    def test_cli_record_status_and_manifest(self):
        code,out,_,directory=self.cli('sweep',{'axes':{'growth_end':[.1,.2]},'on_error':'record','bounds':{'scouting_points':21}});self.assertEqual(code,0);self.assertEqual(json.loads(out)['run_status'],'partial_failure');self.assertTrue(verify_manifest(directory,current_source_hashes())['valid'])
    def test_sweep_plot_gaps_and_reference(self):
        rows=sweep(self.p,self.b,.15,{'growth_end':[.2,.1,.3]},on_error='record')
        with patch('entrysignallab.plots.save_figure') as save:sweep_plot(self.root,rows,'growth_end',.5)
        fig=save.call_args.args[0];ax=fig.axes[0];self.assertTrue(np.isnan(ax.lines[0].get_ydata()[0]));self.assertEqual(list(ax.lines[4].get_ydata()),[.5,.5])
        import matplotlib.pyplot as plt;plt.close(fig)
    def test_regime_failure_is_separate_category(self):
        axes={'growth_end':[.3,.1,.2],'network':[.85,.5]};rows=sweep(self.p,self.b,.15,axes,on_error='record')
        with patch('entrysignallab.plots.save_figure') as save:regime_plot(self.root,rows,axes)
        fig=save.call_args.args[0];self.assertIn('invalid_configuration',[t.get_text() for t in fig.axes[1].get_yticklabels()])
        import matplotlib.pyplot as plt;plt.close(fig)
    def test_html_discloses_actual_policy(self):
        r=compare(self.p,self.b,tie_tolerance=0,outside_option=.4);html_report(self.root,r);text=(self.root/'report.html').read_text();self.assertIn('tolerance: 0',text);self.assertIn('reference of 0.4',text)

if __name__=='__main__':unittest.main()
