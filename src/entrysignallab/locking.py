"""Local same-user leases for disjoint experiment directory trees.

A coordinator registers OS-held leases before output writes. Persistent lock
files are never unlinked. Stale entries are checked by OS acquisition, not PID.
"""
from pathlib import Path
from hashlib import sha256
import errno,getpass,json,os,tempfile,threading,time

_guard=threading.Lock()
_owners={}
_BUSY=(errno.EACCES,errno.EAGAIN,errno.EDEADLK)


def _namespace():
    identity=str(os.getuid()) if hasattr(os,'getuid') else getpass.getuser()
    return Path(tempfile.gettempdir())/('entrysignallab-leases-v2-'+sha256(identity.encode()).hexdigest()[:16])


def _open_lock(path):
    f=path.open('a+b');f.seek(0,os.SEEK_END)
    if f.tell()==0:f.write(b'\0');f.flush()
    f.seek(0)
    return f


def _acquire(f):
    f.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)


def _release(f):
    f.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def _overlap(a,b):
    a=Path(a);b=Path(b)
    return a==b or a in b.parents or b in a.parents


def _experiment(path):
    if (path/'checkpoint.sqlite').exists():return True
    manifest=path/'manifest.json'
    if manifest.is_file():
        try:return json.loads(manifest.read_text()).get('software')=='EntrySignalLab'
        except (ValueError,AttributeError):return True
    return False


def _check_existing(directory):
    if any(_experiment(parent) for parent in directory.parents):
        raise ValueError('nested experiment directory: ancestor contains an experiment')
    if directory.is_dir():
        for name in ('checkpoint.sqlite','manifest.json'):
            for marker in directory.rglob(name):
                if marker.parent!=directory and _experiment(marker.parent):
                    raise ValueError('nested experiment directory: descendant contains an experiment')


def _after_fork():
    # Close without LOCK_UN: children neither retain nor release the parent.
    global _guard,_owners
    for owner in list(_owners.values()):
        for attr in ('_file','_registry_file','_gate_file'):
            f=getattr(owner,attr,None)
            if f is not None:f.close()
    _owners={};_guard=threading.Lock()


if hasattr(os,'register_at_fork'):os.register_at_fork(after_in_child=_after_fork)


class DirectoryLock:
    """Hold through execution, custom exports, plots and final manifest.

    Cooperating processes share a local user/temp namespace and advisory-lock
    filesystem. Completed or interrupted experiment trees cannot nest.
    """
    def __init__(self,directory):
        self.directory=Path(directory).resolve()
        self.path=self.directory.with_name('.'+self.directory.name+'.entrysignal.lock')
        self._key=os.path.normcase(str(self.directory))
        self._file=None;self._registry_file=None;self._gate_file=None;self._holder=None

    def assert_owned(self,directory):
        with _guard:owned=_owners.get(self._key) is self
        if (not owned or self._file is None or self._file.closed or self._registry_file is None
            or self._registry_file.closed or self._holder!=(os.getpid(),threading.get_ident())
            or os.path.normcase(str(Path(directory).resolve()))!=self._key):
            raise ValueError('batch directory lock is not held by this caller')

    def __enter__(self):
        with _guard:
            if any(_overlap(self._key,key) for key in _owners):
                raise ValueError('batch directory is already in use or nested in an active experiment')
            _owners[self._key]=self
        try:
            namespace=_namespace();namespace.mkdir(mode=0o700,parents=True,exist_ok=True)
            self._gate_file=_open_lock(namespace/'coordinator.lock')
            deadline=time.monotonic()+10
            while True:
                try:_acquire(self._gate_file);break
                except OSError as error:
                    if error.errno not in _BUSY or time.monotonic()>=deadline:raise
                    time.sleep(.01)
            try:
                catalog=namespace/'catalog.json'
                active={};records=json.loads(catalog.read_text()) if catalog.exists() else {}
                if not isinstance(records,dict):raise ValueError('invalid directory lease catalog')
                for key,path in records.items():
                    if not isinstance(path,str) or not Path(path).is_absolute() or sha256(path.encode()).hexdigest()!=key:
                        raise ValueError('invalid directory lease catalog entry')
                    probe=_open_lock(namespace/(key+'.lock'))
                    try:
                        try:_acquire(probe)
                        except OSError as error:
                            if error.errno not in _BUSY:raise
                            active[key]=path
                            if _overlap(self._key,path):raise ValueError('batch directory is already in use or nested in an active experiment')
                        else:_release(probe)
                    finally:probe.close()
                _check_existing(self.directory)
                key=sha256(self._key.encode()).hexdigest()
                self._registry_file=_open_lock(namespace/(key+'.lock'));_acquire(self._registry_file)
                # Check hierarchy before creating a sibling file inside a parent.
                self.path.parent.mkdir(parents=True,exist_ok=True)
                self._file=_open_lock(self.path);_acquire(self._file)
                active[key]=self._key
                temporary=namespace/'catalog.json.tmp';temporary.write_text(json.dumps(active,sort_keys=True))
                os.replace(temporary,catalog)
                self._holder=(os.getpid(),threading.get_ident())
            finally:
                _release(self._gate_file);self._gate_file.close();self._gate_file=None
            return self
        except BaseException as error:
            for attr in ('_file','_registry_file','_gate_file'):
                f=getattr(self,attr)
                if f is not None:f.close();setattr(self,attr,None)
            with _guard:_owners.pop(self._key,None)
            if isinstance(error,OSError) and error.errno in _BUSY:
                raise ValueError('batch directory is already in use') from None
            raise

    def __exit__(self,*exc):
        self.assert_owned(self.directory)
        try:
            for f in (self._file,self._registry_file):
                try:_release(f)
                finally:f.close()
        finally:
            self._file=None;self._registry_file=None;self._holder=None
            with _guard:_owners.pop(self._key,None)
