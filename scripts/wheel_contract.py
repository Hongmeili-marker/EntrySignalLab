"""Validate the current wheel's complete bytes and installation contract."""
from pathlib import Path
from email.parser import BytesParser
from email.policy import compat32
from configparser import ConfigParser,Error as ConfigError
import base64, csv, hashlib, io, json, os, shutil, subprocess, sys, tempfile, venv, zipfile
import importlib.metadata as metadata
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10; declared in the release lock.
    import tomli as tomllib
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version


def requirement_key(value):
    r=Requirement(value)
    return (canonicalize_name(r.name),tuple(sorted(r.extras)),str(r.specifier),
            str(r.marker) if r.marker else None,r.url)


def verify_wheel_contract(root):
    """Fail closed on metadata drift, malformed RECORD or unexpected tags."""
    root=Path(root);project=tomllib.loads((root/'pyproject.toml').read_text())['project']
    name=canonicalize_name(project['name']);version=Version(project['version'])
    wheel=root/'dist'/f'{name}-{version}-py3-none-any.whl'
    filename_name,filename_version,_,filename_tags=parse_wheel_filename(wheel.name)
    with zipfile.ZipFile(wheel) as z:
        names=z.namelist()
        if len(set(names))!=len(names):raise ValueError('wheel contains duplicate archive members')
        dist=f'{name}-{version}.dist-info/'
        if {n.split('/')[0] for n in names if '.dist-info/' in n}!={dist[:-1]}:
            raise ValueError('wheel dist-info identity mismatch')
        def headers(part):return BytesParser(policy=compat32).parsebytes(z.read(dist+part))
        m=headers('METADATA');w=headers('WHEEL')
        for field in ['Name','Version','Requires-Python']:
            if len(m.get_all(field,[]))!=1:raise ValueError('wheel metadata missing or duplicate '+field)
        if canonicalize_name(m['Name'])!=name or filename_name!=name:raise ValueError('wheel Name mismatch')
        if Version(m['Version'])!=version or filename_version!=version:raise ValueError('wheel Version mismatch')
        if SpecifierSet(m['Requires-Python'])!=SpecifierSet(project['requires-python']):
            raise ValueError('wheel Requires-Python mismatch')
        if Version('.'.join(map(str,sys.version_info[:3]))) not in SpecifierSet(m['Requires-Python']):
            raise ValueError('wheel does not support the verification Python')
        expected=[requirement_key(x) for x in project.get('dependencies',[])]
        actual=[requirement_key(x) for x in m.get_all('Requires-Dist',[])]
        if sorted(actual,key=repr)!=sorted(expected,key=repr):raise ValueError('wheel Requires-Dist mismatch')
        if w.get('Wheel-Version')!='1.0' or w.get('Root-Is-Purelib')!='true':raise ValueError('wheel format or purelib mismatch')
        tags=set(w.get_all('Tag',[]))
        if tags!={str(t) for t in filename_tags} or tags!={'py3-none-any'}:raise ValueError('wheel tags mismatch')
        parser=ConfigParser(interpolation=None);parser.optionxform=str
        ep=dist+'entry_points.txt'
        if ep in names:
            try:parser.read_string(z.read(ep).decode('utf-8'))
            except ConfigError as error:raise ValueError('invalid wheel entry point metadata') from error
        entries={section:dict(parser[section]) for section in parser.sections()}
        expected_entries={'console_scripts':project.get('scripts',{})} if project.get('scripts') else {}
        if entries!=expected_entries:raise ValueError('wheel console_scripts mismatch')
        records=list(csv.reader(io.StringIO(z.read(dist+'RECORD').decode())))
        indexed={row[0]:row[1:] for row in records if len(row)==3}
        if len(indexed)!=len(records) or set(indexed)!=set(names):raise ValueError('wheel RECORD inventory mismatch')
        for path,(digest,size) in indexed.items():
            if path==dist+'RECORD':
                if digest or size:raise ValueError('wheel RECORD self hash must be empty')
                continue
            data=z.read(path)
            expected_hash='sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            if digest!=expected_hash or size!=str(len(data)):raise ValueError('wheel RECORD hash mismatch: '+path)
    return {'wheel':wheel.name,'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'name':name,'version':str(version),'requires_python':m['Requires-Python'],
            'requires_dist':m.get_all('Requires-Dist',[]),'entry_points':entries,
            'tags':sorted(tags),'record_members':len(indexed),'all_pass':True}


def fresh_install_smoke(root):
    """Install the wheel into an isolated venv with locked dependencies copied.

    No network or source checkout is put on sys.path. Dependencies come from
    the actual verification environment; the current project is pip-installed
    from the wheel and its declared console commands are executed directly.
    """
    root=Path(root);contract=verify_wheel_contract(root)
    project=tomllib.loads((root/'pyproject.toml').read_text())['project']
    with tempfile.TemporaryDirectory(prefix='entrysignal-install-') as directory:
        env=Path(directory)/'venv';venv.EnvBuilder(with_pip=True,system_site_packages=False).create(env)
        site=env/'Lib/site-packages' if os.name=='nt' else next(env.glob('lib/python*/site-packages'))
        bindir=env/('Scripts' if os.name=='nt' else 'bin');dependencies={}
        for line in (root/'requirements-lock.txt').read_text().splitlines():
            if not line.strip() or line.startswith('#'):continue
            spec=Requirement(line)
            if spec.marker and not spec.marker.evaluate():continue
            d=metadata.distribution(spec.name)
            if Version(d.version) not in spec.specifier:raise ValueError('unlocked smoke dependency: '+spec.name)
            dependencies[canonicalize_name(spec.name)]=d.version
            for part in d.files or []:
                if '..' in part.parts:continue
                source=Path(d.locate_file(part));dest=site/part
                if source.is_file():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        py=bindir/('python.exe' if os.name=='nt' else 'python')
        clean_env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME'}}
        clean_env['PIP_DISABLE_PIP_VERSION_CHECK']='1'
        install=subprocess.run([str(py),'-m','pip','install','--no-deps','--no-index',str(root/'dist'/contract['wheel'])],cwd=directory,env=clean_env,capture_output=True,text=True,timeout=60)
        if install.returncode:raise ValueError('fresh wheel installation failed: '+install.stderr[-1500:])
        dependency_check=subprocess.run([str(py),'-m','pip','check'],cwd=directory,env=clean_env,capture_output=True,text=True,timeout=60)
        if dependency_check.returncode:raise ValueError('fresh wheel dependency check failed: '+dependency_check.stdout[-1500:])
        commands=[]
        for name in project.get('scripts',{}):
            command=bindir/(name+'.exe' if os.name=='nt' else name)
            if not command.is_file():raise ValueError('fresh installation missing command: '+name)
            run=subprocess.run([str(command),'--help'],cwd=directory,env=clean_env,capture_output=True,text=True,timeout=60)
            if run.returncode:raise ValueError('fresh console command failed: '+name+' '+run.stderr[-1000:])
            if not run.stdout.strip():raise ValueError('fresh console command produced no help: '+name)
            commands.append({'name':name,'exit':run.returncode,'help_nonempty':bool(run.stdout.strip())})
        isolated=subprocess.run([str(py),'-c','import sys,json,entrysignallab;print(json.dumps({"isolated":sys.prefix!=sys.base_prefix,"module":entrysignallab.__file__}))'],cwd=directory,env=clean_env,capture_output=True,text=True,check=True,timeout=60)
        state=json.loads(isolated.stdout)
        if not state['isolated'] or str(site) not in state['module']:raise ValueError('fresh install did not use isolated wheel')
    return {'all_pass':True,'install_exit':install.returncode,'dependency_check_exit':dependency_check.returncode,'commands':commands,
            'isolated_venv':True,'network_used':False,'dependency_provisioning':'copies of locked verification distributions',
            'dependencies':dependencies,'scope':'Current wheel installed with pip --no-deps --no-index; declared console commands run from a fresh unrelated directory.'}
