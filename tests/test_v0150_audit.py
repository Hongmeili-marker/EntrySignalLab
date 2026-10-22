"""Behavioral regressions for the four v0.14.0 audit findings."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import json,math,subprocess,sys,unittest
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,compare,payoff,rescale_experiment
from entrysignallab.research import default_research_kernel,optimize_research
from entrysignallab.sampling import indexed_rng,SamplingPlan,SAMPLER_VERSION,INDEX_MAX

ROOT=Path(__file__).resolve().parents[1]
MINIMUM=float.fromhex('0x0.0000000000001p-1022')

class AttainmentTests(unittest.TestCase):
    def test_constant_cost_does_not_change_existence(self):
        for cost in [1.,1e8,1e100,1e300]:
            with self.subTest(cost=cost):
                r=optimize(ModelParams(margin_x=1e-20,deployment_cost=cost),'RL',DecisionBounds(announcement_upper=None),0)
                self.assertEqual(r['status'],'no_finite_joint_optimum')
                self.assertIsNone(r['payoff']);self.assertEqual(r['supremum_delay'],0.)
    def test_singleton_zero_uses_actual_finite_payoff(self):
        p=ModelParams(margin_x=1e-20,deployment_cost=1.)
        r=optimize(p,'RL',DecisionBounds(delay_upper=0,announcement_upper=None),0)
        self.assertEqual(r['attainment'],'attained');self.assertEqual(r['delay'],0.)
        self.assertEqual(r['payoff'],payoff(p,'RL',0,0))
    def test_singleton_maturity_is_attained(self):
        p=ModelParams(margin_x=1e-20,deployment_cost=1.)
        r=optimize(p,'RL',DecisionBounds(delay_lower=p.growth_end,announcement_upper=None),0)
        self.assertEqual(r['status'],'attained_joint_optimum');self.assertEqual(r['delay'],p.growth_end)
    def test_genuine_maturity_maximum_is_retained(self):
        r=optimize(ModelParams(deployment_cost=.05,learning_rate=1),'RL',DecisionBounds(announcement_upper=None),0)
        self.assertEqual(r['status'],'attained_joint_optimum');self.assertEqual(r['delay'],.3)
    def test_false_rankability_is_removed(self):
        r=compare(ModelParams(margin_x=1e-20,deployment_cost=1.),DecisionBounds(announcement_upper=None),0)
        self.assertFalse(r['all_rankable']);self.assertEqual(r['co_best'],[]);self.assertEqual(r['preferred_with_outside_option'],[])
    def test_actual_cli_keeps_unattained_schema(self):
        with TemporaryDirectory() as td:
            root=Path(td);config=root/'config.json'
            config.write_text(json.dumps({'params':{'margin_x':1e-20,'deployment_cost':1},'bounds':{'announcement_upper':None},'rival_delay':0}))
            answer=subprocess.run([sys.executable,'-m','entrysignallab.cli','optimize','--config',str(config),'--out',str(root/'output')],capture_output=True,text=True)
            self.assertEqual(answer.returncode,0,answer.stderr)
            result=json.loads((root/'output/comparison.json').read_text())
            self.assertFalse(result['all_rankable']);self.assertEqual(result['results'][1]['status'],'no_finite_joint_optimum')

def attainment_case(margin,cost,lower):
    def test(self):
        r=optimize(ModelParams(margin_x=margin,deployment_cost=cost),'RL',DecisionBounds(delay_lower=lower,announcement_upper=None),0)
        self.assertEqual(r['status'],'no_finite_joint_optimum');self.assertEqual(r['supremum_delay'],lower)
        self.assertIsNone(r['payoff']);self.assertIsNone(r['delay']);self.assertIsNone(r['announcement'])
    return test
for mi,margin in enumerate([1e-18,1e-20,1e-24]):
    for ci,cost in enumerate([1.,2.]):
        for li,lower in enumerate([0.,.05]):
            setattr(AttainmentTests,f'test_audit_{mi}_{ci}_{li}',attainment_case(margin,cost,lower))

class EnvelopeMetadataTests(unittest.TestCase):
    def setup_case(self,attained):
        p=ModelParams(margin_x=MINIMUM,deployment_cost=MINIMUM)
        b=DecisionBounds(delay_lower=p.growth_end,delay_upper=p.growth_end,announcement_upper=None) if attained else DecisionBounds(delay_upper=.2,announcement_upper=None)
        return p,b,optimize(p,'RL',b)
    def test_signed_zero_metadata_remains_valid(self):
        p=ModelParams();b=DecisionBounds(delay_lower=p.growth_end,announcement_upper=None)
        r=optimize(p,'RL',b);r['supremum']=-0.
        kernel=replace(default_research_kernel(),conditional_solver=lambda *a:r)
        self.assertEqual(optimize_research(kernel,p,'RL',b)['supremum'],0.)
    def test_finite_objective_zero_guard_remains_active(self):
        p=ModelParams(margin_x=1e-280,deployment_cost=1e-280);b=DecisionBounds()
        r=optimize(p,'DL',b);r['payoff']=0.
        kernel=replace(default_research_kernel(),conditional_solver=lambda *a:r)
        with self.assertRaisesRegex(ValueError,'payoff disagrees'):optimize_research(kernel,p,'DL',b)

def metadata_case(attained,value,valid):
    def test(self):
        p,b,r=self.setup_case(attained);r['supremum']=value
        kernel=replace(default_research_kernel(),conditional_solver=lambda *a:r)
        if valid:self.assertEqual(optimize_research(kernel,p,'RL',b)['supremum'],-MINIMUM)
        else:
            with self.assertRaisesRegex(ValueError,'configured feasibility'):optimize_research(kernel,p,'RL',b)
    return test
for attained in [False,True]:
    for name,value,valid in [('zero',0.,False),('sign',MINIMUM,False),('valid',-MINIMUM,True),('large',1e-11,False)]:
        setattr(EnvelopeMetadataTests,f'test_{attained}_{name}',metadata_case(attained,value,valid))

class UnitPrecisionTests(unittest.TestCase):
    def setUp(self):self.p=ModelParams(growth=1e307,margin_x=1e307,margin_y=1e307,growth_end=MINIMUM,horizon=2*MINIMUM)
    def test_audit_factor_point_six_rejected(self):
        with self.assertRaisesRegex(ValueError,'relative precision'):rescale_experiment(self.p,DecisionBounds(),0,time_factor=.6)
    def test_audit_factor_point_seven_five_rejected(self):
        with self.assertRaisesRegex(ValueError,'relative precision'):rescale_experiment(self.p,DecisionBounds(),0,time_factor=.75)
    def test_exact_extreme_scale_retained(self):
        q,b,r=rescale_experiment(self.p,DecisionBounds(),0,time_factor=2)
        for st in ['RF','RL','DF','DL']:self.assertLess(abs(payoff(q,st,0)/payoff(self.p,st,0)-1),1e-12)
    def test_normal_units_retained(self):
        p=ModelParams(announcement_cost=.0002,deployment_cost=.012,discount=.4,learning_rate=12)
        q,b,r=rescale_experiment(p,DecisionBounds(),.15,12,1000)
        for st in ['RF','RL','DF','DL']:
            ann=.2 if st.startswith('R') else 0.
            self.assertLess(abs(payoff(q,st,.15*12,ann*1000/12)-payoff(p,st,.15,ann)),1e-12)
    def test_positive_maturity_tail_cannot_collapse(self):
        p=ModelParams(growth_end=1,horizon=math.nextafter(1,2))
        with self.assertRaisesRegex(ValueError,'time separation'):
            rescale_experiment(p,DecisionBounds(tolerance=1,announcement_upper=None),.15,time_factor=1e-308)
    def test_positive_delay_interval_cannot_collapse(self):
        p=ModelParams(growth_end=1,horizon=1)
        b=DecisionBounds(delay_lower=.1,delay_upper=math.nextafter(.1,1),tolerance=1,announcement_upper=None)
        with self.assertRaisesRegex(ValueError,'collapses'):
            rescale_experiment(p,b,.15,time_factor=1e-307)
    def test_positive_rival_maturity_gap_cannot_collapse(self):
        p=ModelParams(growth_end=1,horizon=1)
        with self.assertRaisesRegex(ValueError,'time separation'):
            rescale_experiment(p,DecisionBounds(tolerance=1,announcement_upper=None),math.nextafter(1,0),time_factor=1e-308)
    def test_zero_fields_keep_their_domain(self):
        p=ModelParams(growth=0,network=0,margin_x=0,margin_y=0,growth_end=0)
        q,b,r=rescale_experiment(p,DecisionBounds(),0,12,1000)
        self.assertEqual((q.growth,q.network,q.margin_x,q.growth_end,r),(0,0,0,0,0))
    def test_original_objects_unchanged_on_rejection(self):
        b=DecisionBounds();before=(self.p,b)
        with self.assertRaises(ValueError):rescale_experiment(self.p,b,0,time_factor=.6)
        self.assertEqual(before,(self.p,b))

class IndexedDomainTests(unittest.TestCase):
    def test_all_72_frozen_v2_streams_retained(self):
        rows=json.loads((ROOT/'tests/data/v0140_stream_golden.json').read_text())['rows']
        self.assertEqual(len(rows),72)
        for row in rows:
            actual=indexed_rng(row['seed'],row['index'],row['stream'],row['attempt']).bit_generator.random_raw(8).tolist()
            self.assertEqual(actual,row['raw'])
        self.assertEqual(SAMPLER_VERSION,'indexed-pcg64-v2')
    def test_maximum_single_word_indices_retained(self):
        indexed_rng(104,INDEX_MAX,'parameter:network',INDEX_MAX)
    def test_seed_still_accepts_large_nonnegative_integer(self):indexed_rng(2**512+17,3,'parameter:growth')
    def test_large_sampling_plan_index_rejected(self):
        plan=SamplingPlan(ModelParams(),{'network':[.2,1.]},1)
        with self.assertRaisesRegex(ValueError,'sample index'):plan.draw(12884901890)
    def test_sampling_metadata_discloses_domain(self):
        m=SamplingPlan(ModelParams(),{'network':[.2,1.]}).metadata()
        self.assertEqual(m['sample_index_domain'],[0,4294967295]);self.assertEqual(m['draw_attempt_domain'],[0,4294967295])
    def test_ordinary_indices_remain_distinct(self):
        self.assertNotEqual(indexed_rng(104,0,'x').bit_generator.state,indexed_rng(104,1,'x').bit_generator.state)

def invalid_index_case(value,attempt):
    def test(self):
        with self.assertRaises(ValueError):indexed_rng(104,0 if attempt else value,'x',value if attempt else 0)
    return test
for attempt in [False,True]:
    for i,value in enumerate([4294967296,12884901890,2**100,np.uint64(2**32),-1,True]):
        setattr(IndexedDomainTests,f'test_invalid_{attempt}_{i}',invalid_index_case(value,attempt))

if __name__=='__main__':unittest.main()
