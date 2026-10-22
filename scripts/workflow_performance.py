"""Measured local runtime comparisons; operational vector path is separately checked."""
from pathlib import Path
from dataclasses import replace,asdict
import argparse,statistics,time
import numpy as np
from entrysignallab import ModelParams,DecisionBounds,optimize,payoff,payoff_grid
from entrysignallab.batch import CachedFirstOptimizer
from entrysignallab.workflow import read_json,write_json,manifest
from entrysignallab.provenance import environment_record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args();cfg=read_json(args.config)
    if args.out.exists():raise SystemExit('Choose a fresh output directory')
    repeats=cfg['repeats'];p=ModelParams(announcement_cost=.0002,deployment_cost=.012,learning_rate=12);b=DecisionBounds();ts=np.linspace(0,.3,81);ds=np.linspace(0,2,81)
    def scalar():return np.array([[payoff(p,'RL',float(t),float(d)) for t in ts] for d in ds])
    def vector():return payoff_grid(p,'RL',ts,ds)
    scalar();vector();records=[];outputs={}
    for name,fn in [('scalar_surface',scalar),('vector_surface',vector),('flat_profile',lambda:optimize(ModelParams(growth=0),'RL'))]:
        times=[]
        for i in range(repeats):
            start=time.perf_counter();answer=fn();elapsed=time.perf_counter()-start;times.append(elapsed);outputs[name]=answer
            records.append({'method':name,'repeat':i,'seconds':elapsed})
    params=[replace(p,deployment_cost=float(c)) for c in np.linspace(0,.02,40)]
    def raw():return [optimize(q,'RF',b,.15) for q in params]
    def cached():
        runner=CachedFirstOptimizer();return [runner(q,'RF',b,.15) for q in params],runner.hits
    raw();cached()
    for name,fn in [('uncached_first_controls',raw),('cached_first_controls',cached)]:
        for i in range(repeats):
            start=time.perf_counter();answer=fn();elapsed=time.perf_counter()-start;outputs[name]=answer;records.append({'method':name,'repeat':i,'seconds':elapsed})
    raw_results=outputs['uncached_first_controls'];cached_results,hits=outputs['cached_first_controls']
    error=float(np.max(abs(outputs['scalar_surface']-outputs['vector_surface'])));cache_error=max(abs(a['payoff']-b['payoff']) for a,b in zip(raw_results,cached_results))
    medians={name:statistics.median(x['seconds'] for x in records if x['method']==name) for name in sorted({x['method'] for x in records})}
    report={'repeats':repeats,'surface_shape':[81,81],'surface_max_absolute_error':error,'cached_first_cases':len(params),'cached_search_hits':hits,'cache_max_absolute_error':cache_error,'flat_profile_evaluations':outputs['flat_profile']['evaluations'],'median_seconds':medians,'environment':environment_record(),'all_pass':error<1e-12 and cache_error<1e-12 and hits==39 and outputs['flat_profile']['evaluations']==1,'scope':'Warm local timing, imports/setup excluded. Scientific-value correspondence is checked separately. No universal acceleration, constant-memory summary or remote-platform claim.'}
    args.out.mkdir(parents=True);write_json(args.out/'workflow_timings.json',records);write_json(args.out/'workflow_performance_summary.json',report);manifest(args.out,cfg,cfg['seed'],'workflow_benchmark');print(report)
    if not report['all_pass']:raise SystemExit('Workflow performance correspondence failed')
if __name__=='__main__':main()
