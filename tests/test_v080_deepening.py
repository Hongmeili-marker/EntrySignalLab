"""Reproduction, candidate quality, checkpoint recovery and research contracts."""
from dataclasses import asdict,replace
from pathlib import Path
from unittest.mock import patch
import contextlib,hashlib,io,json,math,sqlite3,tempfile,unittest,subprocess,sys
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,payoff
from entrysignallab.solver import compare_stability,NumericalError
from entrysignallab.workflow import (uncertainty,sweep,summarize_sweep,configured_feasibility,prepare_uncertainty,
    prepare_sweep,normalize_batch,canonical_hash)
from entrysignallab.sampling import SamplingPlan,indexed_rng,wilson_interval
from entrysignallab.batch import run_batch,CachedFirstOptimizer
from entrysignallab.research import (ModelCapabilities,ResearchKernel,evaluate_research,optimize_research,default_research_kernel)
from entrysignallab.cli import main

class DeepeningTests(unittest.TestCase):
    def setUp(self):
        self.p=ModelParams();self.b=DecisionBounds(scouting_points=9);self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def plan(self,ranges=None,**kwargs):return SamplingPlan(self.p,ranges or {'growth':[.1,.2]},104,**kwargs)
    def prepare(self,workers=1,n=5):return prepare_uncertainty(self.p,self.b,.15,{'growth':[.1,.2],'network':[.5,1.]},n=n,batch={'workers':workers,'checkpoint_every':2})
    def interrupt(self,count):
        if count==2:raise RuntimeError('injected interruption after committed prefix')
    def scientific_rows(self,path):
        with contextlib.closing(sqlite3.connect(path/'checkpoint.sqlite')) as db:cases=[json.loads(x[0]) for x in db.execute('SELECT payload FROM cases ORDER BY case_index')]
        return [{k:r.get(k) for k in ['sample','strategy','growth','network','payoff','delay','announcement','winner','participation']} for c in cases for r in c['rows']]
    def test_field_reorder_keeps_draws(self):
        a=SamplingPlan(self.p,{'network':[.5,1],'growth':[.1,.2]},104);b=SamplingPlan(self.p,{'growth':[.1,.2],'network':[.5,1]},104)
        self.assertEqual([a.draw(i) for i in range(10)],[b.draw(i) for i in range(10)])
    def test_saved_config_keeps_draws(self):
        ranges={'network':[.5,1],'growth':[.1,.2]};saved=json.loads(json.dumps(ranges,sort_keys=True));self.assertEqual(self.plan(ranges).draw(7),self.plan(saved).draw(7))
    def test_sample_prefix_is_invariant(self):
        a=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=3);b=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=5);self.assertEqual(a['rows'],b['rows'][:12])
    def test_unrelated_parameter_keeps_independent_draw(self):
        a=self.plan();b=self.plan({'growth':[.1,.2],'network':[.1,2.]});self.assertEqual(a.draw(1)['growth'],b.draw(1)['growth'])
    def test_rng_independent_transcription(self):
        words=[int.from_bytes(hashlib.sha256(b'parameter:growth').digest()[i:i+4],'little') for i in range(0,32,4)];r=np.random.Generator(np.random.PCG64(np.random.SeedSequence([104,7,0,*words]))).random()
        self.assertEqual(indexed_rng(104,7,'parameter:growth').random(),r)
    def test_rng_seed_changes_draw(self):self.assertNotEqual(self.plan().draw(0),SamplingPlan(self.p,{'growth':[.1,.2]},105).draw(0))
    def test_rng_attempt_changes_draw(self):self.assertNotEqual(self.plan().draw(0),self.plan().draw(0,1))
    def test_sampler_metadata_explicit(self):self.assertEqual(self.plan().metadata()['sampler_version'],'indexed-pcg64-v2')
    def test_negative_rng_index_rejected(self):
        with self.assertRaises(ValueError):indexed_rng(104,-1,'a')
    def test_triangular_bounds(self):
        p=SamplingPlan(self.p,{},104,marginals={'growth':{'distribution':'triangular','lower':.1,'upper':.2,'mode':.15}});self.assertTrue(all(.1<=p.draw(i)['growth']<=.2 for i in range(100)))
    def test_loguniform_bounds(self):
        p=SamplingPlan(self.p,{},104,marginals={'growth':{'distribution':'loguniform','lower':1e-8,'upper':1e8}});self.assertTrue(all(1e-8<=p.draw(i)['growth']<=1e8 for i in range(100)))
    def test_beta_bounds(self):
        p=SamplingPlan(self.p,{},104,marginals={'growth':{'distribution':'beta','lower':.1,'upper':.2,'alpha':2,'beta':5}});self.assertTrue(all(.1<=p.draw(i)['growth']<=.2 for i in range(100)))
    def test_bad_triangular_mode(self):
        with self.assertRaises(ValueError):SamplingPlan(self.p,{},104,marginals={'growth':{'distribution':'triangular','lower':.1,'upper':.2,'mode':.3}})
    def test_bad_loguniform_lower(self):
        with self.assertRaises(ValueError):SamplingPlan(self.p,{},104,marginals={'growth':{'distribution':'loguniform','lower':0,'upper':1}})
    def test_bad_beta_shape(self):
        with self.assertRaises(ValueError):SamplingPlan(self.p,{},104,marginals={'growth':{'distribution':'beta','lower':0,'upper':1,'alpha':0,'beta':2}})
    def test_duplicate_marginal(self):
        with self.assertRaises(ValueError):self.plan(marginals={'growth':{'lower':0,'upper':1}})
    def test_unknown_marginal(self):
        with self.assertRaises(ValueError):self.plan({'bad':[0,1]})
    def test_correlation_reorder_equivalent(self):
        ranges={'growth':[.1,.2],'network':[.5,1.]};a=self.plan(ranges,correlation={'names':['growth','network'],'matrix':[[1,.7],[.7,1]]});b=self.plan(ranges,correlation={'names':['network','growth'],'matrix':[[1,.7],[.7,1]]});self.assertEqual([a.draw(i) for i in range(5)],[b.draw(i) for i in range(5)])
    def test_correlation_nonsymmetric_rejected(self):
        with self.assertRaises(ValueError):self.plan({'growth':[.1,.2],'network':[.5,1]},correlation={'names':['growth','network'],'matrix':[[1,.1],[.5,1]]})
    def test_correlation_not_psd_rejected(self):
        with self.assertRaises(ValueError):self.plan({'growth':[.1,.2],'network':[.5,1],'discount':[0,1]},correlation={'names':['growth','network','discount'],'matrix':[[1,-.9,-.9],[-.9,1,-.9],[-.9,-.9,1]]})
    def test_singular_correlation_supported(self):
        p=self.plan({'growth':[0,1],'network':[0,1]},correlation={'names':['growth','network'],'matrix':[[1,1],[1,1]]});r=p.draw(1);self.assertAlmostEqual(r['growth'],r['network'])
    def test_unknown_correlation_name(self):
        with self.assertRaises(ValueError):self.plan(correlation={'names':['network'],'matrix':[[1]]})
    def test_wilson_reference(self):
        count,n=29,100;z=1.959963984540054;p=count/n;den=1+z*z/n;c=(p+z*z/(2*n))/den;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
        self.assertTrue(np.allclose(wilson_interval(count,n),[c-h,c+h],rtol=0,atol=1e-15))
    def test_zero_denominator_interval_none(self):self.assertIsNone(wilson_interval(0,0))
    def test_sampling_numerical_failure_recorded(self):
        with patch('entrysignallab.sampling.SamplingPlan.draw',side_effect=ValueError('inverse transform failed')):
            r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=2,on_error='record')
        self.assertEqual(r['summary']['numerical_error']['count'],2);self.assertEqual(len(r['rows']),8);self.assertTrue(all(x['growth'] is None and x['payoff'] is None for x in r['rows']))
    def test_recorded_constraint_counts(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=10,on_error='record',constraints=[{'left':'growth','relation':'ge','value':.15}]);self.assertEqual(r['failed_samples']+r['completed_samples'],10);self.assertGreater(r['failed_samples'],0)
    def test_resampling_feasible_and_disclosed(self):
        r=uncertainty(self.p,self.b,.15,{'growth_end':[.1,.2]},n=10,constraint_mode='resample',max_draw_attempts=100);self.assertEqual(r['failed_samples'],0);self.assertGreater(r['rejected_draw_attempts'],0);self.assertEqual(r['sampling']['constraint_mode'],'resample')
    def test_exhausted_resampling_recorded(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=5,on_error='record',constraints=[{'left':'growth','relation':'ge','value':.19999999}],constraint_mode='resample',max_draw_attempts=1);self.assertEqual(r['failed_samples'],5)
    def test_impossible_constraint_rejected(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},constraints=[{'left':'growth','relation':'ge','value':1}],constraint_mode='resample')
    def test_strict_constraint_preflight(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},constraints=[{'left':'growth','relation':'ge','value':.15}])
    def test_bad_constraint_relation(self):
        with self.assertRaises(ValueError):self.plan(constraints=[{'left':'growth','relation':'eq','value':.1}])
    def test_four_paired_rows_share_draw(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=1);self.assertEqual(len({x['growth'] for x in r['rows']}),1)
    def test_frequency_intervals_declared(self):
        r=uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=3);self.assertTrue(all(x['frequency_ci95'] is not None for x in r['summary'].values()));self.assertIn('Monte Carlo',r['interval_interpretation'])
    def test_sample_budget(self):
        with self.assertRaises(ValueError):prepare_uncertainty(self.p,self.b,.15,{'growth':[.1,.2]},n=5,batch={'max_cases':4})
    def test_cartesian_budget(self):
        with self.assertRaises(ValueError):prepare_sweep(self.p,self.b,.15,{'growth':[.1,.2],'network':[.1,.2]},batch={'max_cases':3})
    def test_unknown_batch_option(self):
        with self.assertRaises(ValueError):normalize_batch({'skip':True})
    def test_bad_worker_count(self):
        with self.assertRaises(ValueError):normalize_batch({'workers':True})
    def test_checkpoint_resume_matches_science(self):
        meta,tasks=self.prepare();a=self.root/'a';b=self.root/'b'
        with self.assertRaises(RuntimeError):run_batch(a,self.p,self.b,.15,meta,tasks,{},progress_callback=self.interrupt)
        self.assertFalse((a/'manifest.json').exists());self.assertEqual(json.loads((a/'batch_progress.json').read_text())['processed_cases'],2)
        result=run_batch(a,self.p,self.b,.15,meta,tasks,{},resume=True);run_batch(b,self.p,self.b,.15,meta,tasks,{})
        self.assertEqual(self.scientific_rows(a),self.scientific_rows(b));self.assertEqual(result['batch_execution']['resume_prefix_cases'],2)
    def test_resume_corrupt_database_is_controlled(self):
        meta,tasks=self.prepare();out=self.root/'a';out.mkdir();(out/'checkpoint.sqlite').write_bytes(b'not a SQLite database')
        with self.assertRaises(ValueError):run_batch(out,self.p,self.b,.15,meta,tasks,{},resume=True)
    def test_resume_configuration_mismatch(self):
        meta,tasks=self.prepare();a=self.root/'a'
        with self.assertRaises(RuntimeError):run_batch(a,self.p,self.b,.15,meta,tasks,{},progress_callback=self.interrupt)
        with self.assertRaises(ValueError):run_batch(a,self.p,self.b,.15,meta,tasks,{'seed':105},resume=True)
    def test_resume_source_mismatch(self):
        meta,tasks=self.prepare();a=self.root/'a'
        with self.assertRaises(RuntimeError):run_batch(a,self.p,self.b,.15,meta,tasks,{},progress_callback=self.interrupt)
        with patch('entrysignallab.batch.current_source_hashes',return_value={'wrong':'0'*64}),self.assertRaises(ValueError):run_batch(a,self.p,self.b,.15,meta,tasks,{},resume=True)
    def test_resume_tampered_case_rejected(self):
        meta,tasks=self.prepare();a=self.root/'a'
        with self.assertRaises(RuntimeError):run_batch(a,self.p,self.b,.15,meta,tasks,{},progress_callback=self.interrupt)
        with contextlib.closing(sqlite3.connect(a/'checkpoint.sqlite')) as db:
            db.execute('UPDATE cases SET payload=? WHERE case_index=0',('{"case_index":0}',));db.commit()
        with self.assertRaises(ValueError):run_batch(a,self.p,self.b,.15,meta,tasks,{},resume=True)
    def test_parallel_matches_serial_science(self):
        a=self.root/'a';b=self.root/'b';meta,tasks=self.prepare();run_batch(a,self.p,self.b,.15,meta,tasks,{})
        meta,tasks=self.prepare(workers=2);run_batch(b,self.p,self.b,.15,meta,tasks,{})
        self.assertEqual(self.scientific_rows(a),self.scientific_rows(b))
    def test_existing_batch_requires_explicit_resume(self):
        meta,tasks=self.prepare();a=self.root/'a';run_batch(a,self.p,self.b,.15,meta,tasks,{})
        with self.assertRaises(ValueError):run_batch(a,self.p,self.b,.15,meta,tasks,{})
    def test_two_axis_cli_closes_checkpoint_reader(self):
        from entrysignallab.workflow import verify_manifest,current_source_hashes
        cfg=self.root/'c.json';cfg.write_text(json.dumps({'bounds':{'scouting_points':9},'axes':{'growth':[.1,.2],'network':[.5,1.]}}));out=self.root/'out'
        proc=subprocess.run([sys.executable,'-m','entrysignallab.cli','sweep','--config',str(cfg),'--out',str(out)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr);self.assertEqual((out/'checkpoint.sqlite-journal').stat().st_size,0);self.assertTrue(verify_manifest(out,current_source_hashes())['valid'])
    def test_cli_archived_uncertainty_reproduces(self):
        cfg=self.root/'c.json';cfg.write_text(json.dumps({'bounds':{'scouting_points':9},'uncertainty':{'ranges':{'network':[.5,1],'growth':[.1,.2]},'samples':3}}));a=self.root/'a';b=self.root/'b'
        with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(main(['uncertainty','--config',str(cfg),'--out',str(a)]),0);self.assertEqual(main(['uncertainty','--config',str(a/'config.json'),'--out',str(b)]),0)
        self.assertEqual(self.scientific_rows(a),self.scientific_rows(b))
    def test_summary_inherits_actual_policy(self):
        rows=sweep(self.p,self.b,.15,{'growth_end':[.1,.2]},comparison={'tie_tolerance':0,'outside_option':1},on_error='record');r=summarize_sweep(rows);self.assertEqual(r['comparison'],{'tie_tolerance':0.,'outside_option':1.});self.assertEqual(r['on_error'],'record')
    def test_summary_rejects_disagreeing_policy(self):
        rows=sweep(self.p,self.b,.15,{'growth':[.1]},comparison={'tie_tolerance':0})
        with self.assertRaises(ValueError):summarize_sweep(rows,comparison={'tie_tolerance':1})
    def test_summary_rejects_mixed_policy(self):
        a=sweep(self.p,self.b,.15,{'growth':[.1]},comparison={'tie_tolerance':0});b=sweep(self.p,self.b,.15,{'growth':[.2]})
        with self.assertRaises(ValueError):summarize_sweep(a+b)
    def test_feasibility_rejects_bad_rival(self):
        for rival in [float('nan'),float('inf'),True,-1,1]:
            with self.subTest(rival=rival),self.assertRaises(ValueError):configured_feasibility(self.p,self.b,rival,'DF',.15,0)
    def test_coarse_probes_promote_candidate(self):
        p=ModelParams(growth=1,network=0,growth_end=1,horizon=2,margin_x=1,deployment_cost=.01,learning_rate=1000);r=optimize(p,'DL',DecisionBounds(scouting_points=3,tolerance=.1))
        self.assertGreater(r['payoff'],.740089501);self.assertGreater(r['delay'],0);self.assertGreater(r['probe_improvement_found'],0);self.assertFalse(r['local_quality_passed']);self.assertEqual(r['payoff'],payoff(p,'DL',r['delay'],0))
    def test_known_flat_profile_uses_one_evaluation(self):
        r=optimize(ModelParams(growth=0),'RL');self.assertEqual(r['evaluations'],1);self.assertEqual(r['delay_refinement_intervals'],0);self.assertTrue(r['delay_nonunique'])
    def test_evaluation_budget_enforced(self):
        fixed=DecisionBounds(delay_lower=.1,delay_upper=.1,max_evaluations=1)
        self.assertEqual(optimize(self.p,'RL',fixed)['evaluations'],1)
        narrow=DecisionBounds(delay_lower=.1,delay_upper=float(np.nextafter(.1,1.)),max_evaluations=2)
        self.assertEqual(optimize(self.p,'DL',narrow)['evaluations'],2)
        unbounded=DecisionBounds(announcement_upper=None,max_evaluations=1)
        self.assertEqual(optimize(self.p,'RL',unbounded)['status'],'no_finite_joint_optimum')
        with self.assertRaises(NumericalError):optimize(self.p,'RL',replace(self.b,max_evaluations=2))
    def test_negative_quality_tolerance_rejected(self):
        with self.assertRaises(ValueError):DecisionBounds(payoff_atol=-1).validate(self.p)
    def test_stability_reports_local_scope(self):
        r=compare_stability(self.p,self.b,factors=[1,2]);self.assertTrue(r['ranking_stable']);self.assertTrue(r['payoff_stable']);self.assertFalse(r['globally_certified'])
    def test_stability_rejects_duplicate_factors(self):
        with self.assertRaises(ValueError):compare_stability(self.p,self.b,factors=[1,1])
    def test_comparison_gap_matches_values(self):
        r=compare(self.p,self.b);vals=sorted([x['payoff'] for x in r['results']],reverse=True);self.assertEqual(r['entry_payoff_gap'],vals[0]-vals[1]);self.assertEqual(r['outside_option_gap'],vals[0])
    def test_cache_preserves_actual_cost_payoff(self):
        runner=CachedFirstOptimizer();a=runner(self.p,'RF',self.b,.15);p=replace(self.p,deployment_cost=.2,learning_rate=100);b=runner(p,'RF',self.b,.15);self.assertTrue(b['reused_search']);self.assertEqual(b['payoff'],optimize(p,'RF',self.b,.15)['payoff']);self.assertEqual(a['announcement'],b['announcement'])
    def test_cache_invalidated_on_ann_cost(self):
        runner=CachedFirstOptimizer();runner(self.p,'RF',self.b,.15);r=runner(replace(self.p,announcement_cost=.01),'RF',self.b,.15);self.assertFalse(r['reused_search'])
    def test_cache_does_not_reuse_followers(self):
        runner=CachedFirstOptimizer();runner(self.p,'RL',self.b,.15);r=runner(replace(self.p,deployment_cost=.02),'RL',self.b,.15);self.assertNotIn('reused_search',r)
    def test_default_kernel_correspondence(self):
        kernel=default_research_kernel();self.assertEqual(evaluate_research(kernel,self.p,'DL',.1)['payoff'],payoff(self.p,'DL',.1));r=optimize_research(kernel,self.p,'DL',self.b);self.assertEqual(r['payoff'],optimize(self.p,'DL',self.b)['payoff'])
    def test_extension_does_not_inherit_default_solver(self):
        kernel=ResearchKernel(ModelCapabilities('toy','1',False,False),lambda p,s,t,d:t,lambda p:None,lambda p,s,t,d:None)
        self.assertEqual(evaluate_research(kernel,{},'DL',.2)['payoff'],.2)
        with self.assertRaises(ValueError):optimize_research(kernel,{},'DL')
    def test_extension_bad_solver_objective_rejected(self):
        kernel=ResearchKernel(ModelCapabilities('toy','1',False,False),lambda p,s,t,d:t,lambda p:None,lambda p,s,t,d:None,lambda p,s,b,r:{'strategy':s,'payoff':5,'delay':.2,'announcement':0})
        with self.assertRaises(ValueError):optimize_research(kernel,{},'DL')
    def test_capabilities_are_boolean(self):
        with self.assertRaises(ValueError):ModelCapabilities('toy','1',1,False).validate()

class VectorGridTests(unittest.TestCase):
    def test_unrepresentable_gap_is_disclosed(self):
        from entrysignallab.solver import compare_results
        rows=[{'strategy':st,'payoff':1e308 if st=='RF' else -1e308} for st in ['RF','RL','DF','DL']]
        r=compare_results(rows,outside_option=-1e308);self.assertIsNone(r['entry_payoff_gap']);self.assertEqual(r['entry_payoff_gap_diagnostic']['representation'],'outside_float_range');json.dumps(r,allow_nan=False)
    def test_comparison_rejects_nonfinite_result(self):
        from entrysignallab.solver import compare_results
        rows=[{'strategy':st,'payoff':float('nan') if st=='RF' else 0} for st in ['RF','RL','DF','DL']]
        with self.assertRaises(ValueError):compare_results(rows)
    def test_grid_scalar_correspondence(self):
        from entrysignallab import payoff_grid
        for r in [0,.4]:
            p=ModelParams(discount=r,announcement_cost=.0002,deployment_cost=.012,learning_rate=12)
            for st in ['RF','RL','DF','DL']:
                ds=[0,.2,2] if st.startswith('R') else [0];ts=[0,.1,.3]
                expected=np.array([[payoff(p,st,t,d) for t in ts] for d in ds])
                self.assertTrue(np.allclose(payoff_grid(p,st,ts,ds),expected,rtol=1e-12,atol=1e-15))
    def test_grid_large_weighted_scale(self):
        from entrysignallab import payoff_grid
        p=ModelParams(growth=1,network=0,growth_end=1,horizon=1e308,margin_x=1e-308)
        self.assertTrue(np.allclose(payoff_grid(p,'DL',[0,.3],[0]),[[payoff(p,'DL',0),payoff(p,'DL',.3)]],rtol=1e-13))
    def test_grid_rejects_invalid_controls(self):
        from entrysignallab import payoff_grid
        for st,t,d in [('DL',[.1],[1]),('RF',[1],[0]),('RL',[True],[0])]:
            with self.subTest(strategy=st),self.assertRaises(ValueError):payoff_grid(ModelParams(),st,t,d)

if __name__=='__main__':unittest.main()
