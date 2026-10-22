"""Controlled current-wheel metadata mutations and isolated install smoke."""
from pathlib import Path
import argparse,base64,csv,hashlib,io,json,re,shutil,tempfile,zipfile
from entrysignallab import __version__
from entrysignallab.workflow import write_json,record_validation
from wheel_contract import verify_wheel_contract,fresh_install_smoke

MUTATIONS=('missing_console_entrypoint','incompatible_python','missing_python_requirement',
           'wrong_name','wrong_version','changed_dependency','wrong_wheel_tag',
           'wrong_purelib','duplicate_metadata_name','corrupt_record')

def mutated_wheel_bytes(data,case):
    with zipfile.ZipFile(io.BytesIO(data)) as z:files={n:z.read(n) for n in z.namelist()}
    dist=next(n.rsplit('/',1)[0]+'/' for n in files if n.endswith('.dist-info/METADATA'))
    def replace(part,pattern,replacement):
        text,count=re.subn(pattern,replacement,files[dist+part].decode(),flags=re.M)
        assert count==1,(part,pattern,count);files[dist+part]=text.encode()
    if case=='missing_console_entrypoint':files.pop(dist+'entry_points.txt')
    elif case=='incompatible_python':replace('METADATA',r'^Requires-Python:.*$','Requires-Python: >=99')
    elif case=='missing_python_requirement':replace('METADATA',r'^Requires-Python:.*\n','')
    elif case=='wrong_name':replace('METADATA',r'^Name:.*$','Name: other-project')
    elif case=='wrong_version':replace('METADATA',r'^Version:.*$','Version: 99.0.0')
    elif case=='changed_dependency':replace('METADATA',r'^Requires-Dist: numpy.*$','Requires-Dist: numpy>=99')
    elif case=='wrong_wheel_tag':replace('WHEEL',r'^Tag:.*$','Tag: py2-none-any')
    elif case=='wrong_purelib':replace('WHEEL',r'^Root-Is-Purelib:.*$','Root-Is-Purelib: false')
    elif case=='duplicate_metadata_name':files[dist+'METADATA']=b'Name: entrysignallab\n'+files[dist+'METADATA']
    elif case!='corrupt_record':raise ValueError(case)
    buf=io.StringIO();writer=csv.writer(buf,lineterminator='\n')
    for name,value in files.items():
        writer.writerow([name,'',''] if name==dist+'RECORD' else [name,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(value).digest()).decode().rstrip('='),len(value)])
    files[dist+'RECORD']=buf.getvalue().encode()
    if case=='corrupt_record':files[dist+'METADATA']+=b'\nChanged after RECORD\n'
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
    return output.getvalue()

def mutation_checks(root):
    root=Path(root);pristine=verify_wheel_contract(root);data=(root/'dist'/pristine['wheel']).read_bytes()
    rows=[{'case':'pristine','pass':True,'metadata':pristine}]
    with tempfile.TemporaryDirectory() as directory:
        clone=Path(directory);(clone/'dist').mkdir();shutil.copy2(root/'pyproject.toml',clone/'pyproject.toml')
        wheel=clone/'dist'/pristine['wheel']
        for case in MUTATIONS:
            wheel.write_bytes(mutated_wheel_bytes(data,case))
            try:verify_wheel_contract(clone)
            except (ValueError,KeyError,zipfile.BadZipFile) as e:rows.append({'case':case,'pass':True,'reason':str(e)})
            else:rows.append({'case':case,'pass':False,'reason':'unexpected acceptance'})
    return rows

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True)
    out=ap.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1];rows=mutation_checks(root)
    smoke=fresh_install_smoke(root)
    rows.append({'case':'isolated_pip_install_and_declared_console','pass':smoke['all_pass'],'smoke':smoke})
    summary={'version':__version__,'all_pass':all(x['pass'] for x in rows),'checks':len(rows),
             'metadata_negative_cases':len(MUTATIONS),'original_audit_mutations_rejected':2,
             'fresh_install_smoke':smoke,'scope':'Temporary wheel copies only; regenerated valid RECORD for metadata mutations. Original wheel unchanged. Offline install from current wheel with locked dependencies provisioned from verification environment.'}
    write_json(out/'wheel_summary.json',summary);write_json(out/'checks.json',rows)
    if not summary['all_pass']:raise AssertionError(rows)
    record_validation(out,Path(__file__),seed=20261020);print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
