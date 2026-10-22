"""Bounded-memory case execution with transactional checkpoints and exact resume."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
import csv,json,os,sqlite3,sys,platform
import numpy,scipy
from .locking import DirectoryLock
from .sampling import SAMPLER_VERSION
from .model import payoff
from .solver import optimize
from .workflow import (canonical_hash,current_source_hashes,execute_case,read_json,write_json,
                       summarize_sweep,summarize_uncertainty,csv_export_row)
from . import __version__

class CachedFirstOptimizer:
    """Reuse RF/DF controls under additive first-entrant deployment-cost changes."""
    def __init__(self,limit=1024):self.cache={};self.limit=limit;self.hits=0;self.searches=0
    def __call__(self,p,strategy,bounds,rival):
        if strategy.endswith('L'):return optimize(p,strategy,bounds,rival)
        params=asdict(p);params.pop('deployment_cost');params.pop('learning_rate')
        key=canonical_hash({'params':params,'strategy':strategy,'bounds':asdict(bounds),'rival':rival})
        if key in self.cache:
            self.hits+=1;result=dict(self.cache[key]);result['cache_source_evaluations']=result['evaluations'];result['evaluations']=0;result['reused_search']=True
            if result['payoff'] is not None:result['payoff']=payoff(p,strategy,result['delay'],result['announcement'])
            return result
        result=optimize(p,strategy,bounds,rival);self.searches+=1
        if len(self.cache)>=self.limit:self.cache.pop(next(iter(self.cache)))
        self.cache[key]=dict(result);return {**result,'reused_search':False}

_worker_optimizer=None

def _worker_case(arguments):
    global _worker_optimizer
    if _worker_optimizer is None:_worker_optimizer=CachedFirstOptimizer()
    p,b,rival,task,meta=arguments
    return execute_case(p,b,rival,task,meta,_worker_optimizer)


def _ordered_parallel(p,bounds,rival,tasks,meta,workers):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending=deque();iterator=iter(tasks)
        for _ in range(2*workers):
            task=next(iterator,None)
            if task is None:break
            pending.append(pool.submit(_worker_case,(p,bounds,rival,task,meta)))
        while pending:
            yield pending.popleft().result()
            task=next(iterator,None)
            if task is not None:pending.append(pool.submit(_worker_case,(p,bounds,rival,task,meta)))


def atomic_json(path,obj):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    write_json(temporary,obj);os.replace(temporary,path)

class CheckpointStore:
    def __init__(self,path,recipe,resume=False):
        path=Path(path);exists=path.exists();signature=canonical_hash(recipe)
        if resume and not exists:raise ValueError('resume requires checkpoint.sqlite')
        if not resume and exists:raise ValueError('checkpoint already exists; use explicit resume')
        self.db=sqlite3.connect(path)
        try:
            self.db.execute('PRAGMA journal_mode=TRUNCATE');self.db.execute('PRAGMA synchronous=FULL')
            if exists:
                stored=self.db.execute('SELECT payload FROM recipe').fetchone()
                if stored is None or json.loads(stored[0])!=recipe:self.db.close();raise ValueError('checkpoint recipe/source/version mismatch')
                if self.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':self.db.close();raise ValueError('invalid checkpoint integrity')
            else:
                self.db.execute('CREATE TABLE recipe(payload TEXT NOT NULL)');self.db.execute('INSERT INTO recipe VALUES (?)',(json.dumps(recipe,sort_keys=True,allow_nan=False),))
                self.db.execute('CREATE TABLE cases(case_index INTEGER PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL)');self.db.commit()
            self.signature=signature
            for index,payload,digest in self.db.execute('SELECT case_index,payload,sha256 FROM cases ORDER BY case_index'):
                value=json.loads(payload)
                if canonical_hash(value)!=digest or value['case_index']!=index:self.db.close();raise ValueError('checkpoint case content mismatch')
        except (sqlite3.Error,ValueError,TypeError,KeyError) as error:
            self.db.close();raise ValueError('invalid checkpoint: '+str(error)) from None
    def indices(self):return [row[0] for row in self.db.execute('SELECT case_index FROM cases ORDER BY case_index')]
    def add(self,case):self.db.execute('INSERT INTO cases VALUES (?,?,?)',(case['case_index'],json.dumps(case,sort_keys=True,allow_nan=False),canonical_hash(case)))
    def commit(self):self.db.commit()
    def cases(self):
        for payload, in self.db.execute('SELECT payload FROM cases ORDER BY case_index'):yield json.loads(payload)
    def close(self):self.db.close()


def _export_csv(directory,operation,store):
    names=[]
    for case in store.cases():
        for row in case['rows']:
            for name in row:
                if name not in names:names.append(name)
    temporary=directory/(operation+'.csv.tmp')
    with temporary.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=names);writer.writeheader()
        for case in store.cases():writer.writerows(csv_export_row(row) for row in case['rows'])
    os.replace(temporary,directory/(operation+'.csv'))


def runtime_fingerprint():
    return {'python':platform.python_version(),'implementation':sys.implementation.name,
            'numpy':numpy.__version__,'scipy':scipy.__version__,'platform':sys.platform,
            'machine':platform.machine(),'sampler_version':SAMPLER_VERSION}


def run_batch(directory,p,bounds,rival,meta,tasks_factory,config,resume=False,progress_callback=None,lock=None):
    """Execute under ownership; pass an outer DirectoryLock for custom publication."""
    if lock is not None:
        if not isinstance(lock,DirectoryLock):raise ValueError('lock must be an acquired DirectoryLock')
        lock.assert_owned(directory)
        return _run_batch_locked(directory,p,bounds,rival,meta,tasks_factory,config,resume,progress_callback)
    with DirectoryLock(directory):
        return _run_batch_locked(directory,p,bounds,rival,meta,tasks_factory,config,resume,progress_callback)


def _run_batch_locked(directory,p,bounds,rival,meta,tasks_factory,config,resume,progress_callback):
    """Preflight belongs to prepare_*; interrupted runs have no final manifest."""
    directory=Path(directory)
    recipe={'version':__version__,'source_sha256':current_source_hashes(),'runtime':runtime_fingerprint(),'config':config,'meta':meta,
            'params':asdict(p),'bounds':asdict(bounds),'rival':rival}
    if resume:
        if not directory.is_dir() or (directory/'manifest.json').exists():raise ValueError('resume requires an incomplete batch directory')
    else:
        if directory.exists() and any(directory.iterdir()):raise ValueError('output directory must be empty')
        directory.mkdir(parents=True,exist_ok=True)
    store=CheckpointStore(directory/'checkpoint.sqlite',recipe,resume)
    operation=meta['operation'];total=meta['requested_cases'];done=store.indices()
    if done!=list(range(len(done))) or len(done)>total:store.close();raise ValueError('checkpoint case indices are not an exact prefix')
    completed=len(done);resume_prefix=completed
    def progress(state,error=None):
        atomic_json(directory/'batch_progress.json',{'version':__version__,'operation':operation,'state':state,'processed_cases':completed,
            'requested_cases':total,'resume_prefix_cases':resume_prefix,'recipe_sha256':store.signature,'error':error})
    try:
        atomic_json(directory/'config.json',config);progress('running')
        def checked_tasks():
            expected=None
            for task in tasks_factory():
                index=task.get('case_index') if isinstance(task,dict) else None
                if isinstance(index,bool) or not isinstance(index,int) or index<0:
                    raise ValueError('case factory index must be a nonnegative Python integer')
                if index>=total:raise ValueError('case factory exceeds requested_cases')
                if expected is None:
                    if index not in (0,resume_prefix):raise ValueError('case factory must start at zero or the committed resume prefix')
                    expected=index
                if index!=expected:raise ValueError('case factory indices must be contiguous and nonrepeating')
                expected+=1
                if index<resume_prefix:continue
                yield task
        tasks=checked_tasks()
        optimizer=CachedFirstOptimizer()
        cases=_ordered_parallel(p,bounds,rival,tasks,meta,meta['batch']['workers']) if meta['batch']['workers']>1 else (execute_case(p,bounds,rival,task,meta,optimizer) for task in tasks)
        for case in cases:
            if completed>=total:raise ValueError('case factory exceeds requested_cases')
            if case['case_index']!=completed:raise ValueError('case sequence changed during execution')
            store.add(case);completed+=1
            if completed%meta['batch']['checkpoint_every']==0:store.commit();progress('running')
            if progress_callback:progress_callback(completed)
        if completed!=total:raise ValueError('case factory ended before requested_cases were completed')
        store.commit();_export_csv(directory,operation,store)
        if operation=='uncertainty':summary=summarize_uncertainty(store.cases(),meta)
        else:
            # One representative row per case is sufficient for exact sweep counts.
            summary=summarize_sweep([case['rows'][0] for case in store.cases()])
            summary['domain_preflight_issues']=meta['domain_preflight_issues'];summary['parameter_order']=meta['parameter_order']
        summary['batch_execution']={'workers':meta['batch']['workers'],'checkpoint_every':meta['batch']['checkpoint_every'],
            'resume_prefix_cases':resume_prefix,'processed_cases':completed,'checkpoint':'checkpoint.sqlite',
            'runtime':recipe['runtime'],'directory_ownership':'Exclusive non-nested experiment directory lease v2; CLI retains ownership through plots and final manifest.',
            'first_control_cache_hits_this_process':optimizer.hits if meta['batch']['workers']==1 else None,
            'cache_scope':'Worker-local bounded cache; reuse is indicated on each RF/DF row. Cached values are reevaluated under the actual costs.'}
        atomic_json(directory/(operation+'_summary.json'),summary);progress('completed');return summary
    except BaseException as error:
        store.commit();progress('interrupted',type(error).__name__+': '+str(error));raise
    finally:store.close()
