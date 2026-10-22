import unittest,sys,math,json,tempfile,contextlib,io
from pathlib import Path
from dataclasses import replace
from fractions import Fraction as F
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from validate_v0180 import rational_reference,primitive_reference,source_reference
from entrysignallab import ModelParams,DecisionBounds,payoff,payoff_grid,compare,rescale_experiment,optimize
from entrysignallab.audit import source_audit
from entrysignallab.cli import main
from entrysignallab.research import default_research_kernel,optimize_research

ST=['RF','RL','DF','DL']
BOUNDS=DecisionBounds(delay_lower=0,delay_upper=0,announcement_upper=0)
def params(scale=1e14,cost=None):
    return ModelParams(growth=4*scale,network=0,growth_end=1,horizon=1,margin_x=1,
                       margin_y=1,deployment_cost=scale-.25 if cost is None else cost)

class NetPayoffAudit(unittest.TestCase):
    def test_positive_preference(self):
        r=compare(params(),BOUNDS,0);self.assertEqual(r['preferred_with_outside_option'],ST)
        self.assertTrue(all(x['payoff']==.25 for x in r['results']))
    def test_negative_preference(self):
        r=compare(params(1e12,1e12+.000244140625),BOUNDS,0)
        self.assertEqual(r['preferred_with_outside_option'],['no_entry'])
        self.assertTrue(all(x['payoff']==-.000244140625 for x in r['results']))
    def test_zero_preference(self):
        for s in [1e8,1e14]:
            r=compare(params(s,s),BOUNDS,0)
            self.assertEqual(r['preferred_with_outside_option'],ST+['no_entry'])
    def test_all_strategies_grid_and_scalar(self):
        for st in ST:
            self.assertEqual(payoff(params(),st,0),.25)
            self.assertEqual(float(payoff_grid(params(),st,[0],[0])[0,0]),.25)
    def test_exact_unit_transforms(self):
        p=params()
        for a,b in [(2,1),(1,4),(2,4),(16,8)]:
            q,d,r=rescale_experiment(p,BOUNDS,0,a,b)
            self.assertEqual(rational_reference(q,'DL',0,0),F(1,4))
            self.assertEqual(compare(q,d,r)['preferred_with_outside_option'],ST)
            self.assertEqual(payoff(q,'DL',0),.25)
    def test_nonzero_announcement_cost(self):
        p=ModelParams(growth=4,network=0,growth_end=1,horizon=1,margin_x=1e14,announcement_cost=2e14)
        for st in ['RF','RL']:
            self.assertEqual(payoff(p,st,0,1),0)
            self.assertEqual(payoff_grid(p,st,[0],[1])[0,0],0)
    def test_grid_broadcast(self):
        p=replace(params(),announcement_cost=.1)
        ts=[0,.125,.3];ds=[0,.25,1]
        grid=payoff_grid(p,'RL',ts,ds);self.assertEqual(grid.shape,(3,3))
        for i,d in enumerate(ds):
            for j,t in enumerate(ts):
                ref=float(rational_reference(p,'RL',t,d))
                self.assertLessEqual(abs(grid[i,j]-ref),max(8*math.ulp(ref),abs(ref)*1e-11))
    def test_discounted_cancellation(self):
        p=ModelParams(growth=4,network=.7,margin_x=1e14,discount=.5,deployment_cost=0)
        ref,rev,ann,decay=primitive_reference(p,'RL',.125,.2)
        p=replace(p,deployment_cost=float(rev/decay))
        ref=float(primitive_reference(p,'RL',.125,.2,800)[0])
        self.assertEqual(payoff(p,'RL',.125,.2),ref)
        self.assertEqual(payoff_grid(p,'RL',[.125],[.2])[0,0],ref)
    def test_learning_cancellation(self):
        p=ModelParams(growth=4,network=.7,margin_x=1e14,learning_rate=.7)
        _,rev,ann,decay=primitive_reference(p,'DL',.125,0)
        p=replace(p,deployment_cost=float(rev/decay))
        self.assertEqual(payoff(p,'DL',.125),float(primitive_reference(p,'DL',.125,0,800)[0]))
    def test_tiny_discount_signs(self):
        for rate in [1e-20,1e-100,1e-300,5e-324]:
            p=replace(params(1,1),discount=rate)
            reference=float(primitive_reference(p,'DL',0,0,1600)[0])
            self.assertEqual(payoff(p,'DL',0),reference)
            self.assertLess(payoff(p,'DL',0),0)
    def test_genuine_final_underflow(self):
        p=ModelParams(growth=16,network=0,growth_end=.5,horizon=.5,margin_x=1,deployment_cost=1,discount=5e-324)
        self.assertEqual(float(primitive_reference(p,'DL',0,0,1600)[0]),0)
        self.assertEqual(payoff(p,'DL',0),0)
    def test_two_rounded_zero_costs_can_sum(self):
        p=ModelParams(growth=0,growth_end=1,horizon=1,announcement_cost=5e-324,
                      deployment_cost=5e-324,learning_rate=math.log(2.5))
        self.assertEqual(payoff(p,'RL',1,.8),-5e-324)
        self.assertEqual(payoff_grid(p,'RL',[1],[.8])[0,0],-5e-324)
    def test_research_correspondence(self):
        for st in ST:
            r=optimize_research(default_research_kernel(),params(),st,BOUNDS,0)
            self.assertEqual(r['payoff'],.25);self.assertEqual(r['objective_consistency']['status'],'passed')
    def test_uncapped_envelope_precision(self):
        p=ModelParams(growth=4,network=.7,margin_x=1e14)
        t=F(.125);H,T=F(p.growth_end),F(p.horizon)
        rev=F(p.margin_x)*F(p.growth)*(H-t)*(2*T-H-t)/2
        p=replace(p,deployment_cost=float(rev))
        b=DecisionBounds(delay_lower=.125,announcement_upper=None)
        r=optimize(p,'RL',b)
        self.assertIsNone(r['payoff']);self.assertEqual(r['supremum'],float(rev-F(p.deployment_cost)))
        self.assertEqual(optimize_research(default_research_kernel(),p,'RL',b)['supremum'],r['supremum'])
    def test_evaluate_CLI(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            from dataclasses import asdict
            path.write_text(json.dumps({'params':asdict(params()),'bounds':asdict(BOUNDS),'rival_delay':0}))
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):code=main(['evaluate','--config',str(path),'--strategy','DL','--delay','0'])
            self.assertEqual(code,0);self.assertEqual(json.loads(stream.getvalue())['payoff_x'],.25)

class SourceBoundAudit(unittest.TestCase):
    def test_rounding_equality_is_not_bound(self):
        a=source_audit(ModelParams(growth=1,network=1e20))['checks'][-1]
        self.assertFalse(a['pass']);self.assertEqual(a['observed'],a['market_revenue_bound'])
        self.assertEqual(a['decision_basis'],'analytic_positive_excess')
    def test_high_scale_intermediate_overflow(self):
        p=ModelParams(growth=2.5e307,network=3.2e-308,growth_end=1)
        a=source_audit(p)['checks'][-1];P,B=source_reference(p)
        self.assertEqual(a['observed'],float(P));self.assertEqual(a['market_revenue_bound'],float(B))
        self.assertGreater(a['observed'],5*a['market_revenue_bound']);self.assertFalse(a['pass'])
    def test_small_scale_intermediate_overflow(self):
        p=ModelParams(growth=1e-150,network=1e300,growth_end=1)
        a=source_audit(p)['checks'][-1]
        self.assertEqual(a['observed'],float(source_reference(p)[0]));self.assertGreater(a['observed'],0)
    def test_bound_underflow_is_descriptive(self):
        p=ModelParams(growth=1e-308,network=1e308,growth_end=5e-324)
        a=source_audit(p)['checks'][-1]
        self.assertFalse(a['pass']);self.assertEqual(a['market_revenue_bound'],0)
        self.assertEqual(a['bound_representation'],'underflow');self.assertGreater(a['observed'],0)
    def test_candidate_underflow_is_descriptive(self):
        p=ModelParams(growth=1e16,network=1e308,growth_end=5e-324)
        a=source_audit(p)
        self.assertEqual(a['printed_candidates']['delay_RL'],0)
        self.assertEqual(a['candidate_representations']['delay_RL'],'underflow')
        self.assertFalse(a['checks'][-1]['pass'])
    def test_true_output_overflow_rejected(self):
        for s,n in [(1e-200,1e-200),(1e200,1e200)]:
            with self.assertRaisesRegex(ValueError,'floating-point range'):source_audit(ModelParams(growth=s,network=n))
    def test_preconditions_unchanged(self):
        for changes in [{'discount':.1},{'deployment_cost':1},{'growth':0},{'growth_end':0},{'network':0}]:
            with self.assertRaises(ValueError):source_audit(ModelParams(**changes))
    def test_six_check_identifiers(self):
        a=source_audit(ModelParams())
        self.assertEqual([x['id'] for x in a['checks']],['RF_INTENSITY_DOMAIN','RL_DELAY_DOMAIN','DF_DL_DELAY_DOMAIN','RL_DELAY_DERIVATIVE','DF_INTEGRAL_IDENTITY','RL_REVENUE_BOUND'])
        self.assertFalse(a['checks'][-2]['pass']);self.assertFalse(a['checks'][-1]['pass'])

if __name__=='__main__':unittest.main()
