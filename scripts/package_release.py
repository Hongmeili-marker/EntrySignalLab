"""Package a local release with optional recorded results. MIT License."""
from pathlib import Path
import argparse, hashlib, json, zipfile, shutil

def included(path, root, publication):
    rel=path.relative_to(root)
    # Only the explicit, verified build paths below supply mutable evidence.
    # A source tree may retain older local validation outputs.
    if rel.parts[0] in {'results','validation'}:return False
    if rel.as_posix()=="SHA256SUMS.txt":return False
    if rel.parts[0]=="dist" and rel.as_posix()!="dist/entrysignallab-0.25.0-py3-none-any.whl":return False
    if any(p in {"build","__pycache__",".git"} or p.endswith(".egg-info") for p in rel.parts):return False
    if path.suffix in {".pyc",".aux",".out"}:return False
    if path.suffix==".log" and rel.parts[0] not in {"validation","audit"}:return False
    if path.name=="manuscript_latex_input.md":return False
    if not publication and rel.parts[0]=="publication":return False
    if not publication and rel.parts[0] in {"results","validation","audit"}:return False
    if not publication and rel.as_posix() in {"scripts/build_release.py","scripts/check_release.py"}:return False
    return path.is_file()

def write_archive(path, records, prefix="EntrySignalLab-0.25.0/"):
    records={name:data for name,data in records.items() if name!="SHA256SUMS.txt"}
    hashes="".join(hashlib.sha256(data).hexdigest()+"  "+name+"\n" for name,data in sorted(records.items()))
    records=dict(records);records["SHA256SUMS.txt"]=hashes.encode()
    temporary=path.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(records.items()):
            info=zipfile.ZipInfo(prefix+name,date_time=(2026,10,20,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,data)
    temporary.replace(path)
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise RuntimeError("Archive CRC validation failed")
        for name,data in records.items():
            if z.read(prefix+name)!=data:raise RuntimeError("Archive content mismatch: "+name)
        listed={}
        for line in z.read(prefix+"SHA256SUMS.txt").decode().splitlines():
            expected,name=line.split("  ",1)
            if name in listed or name=="SHA256SUMS.txt":raise RuntimeError("Invalid checksum inventory")
            if hashlib.sha256(z.read(prefix+name)).hexdigest()!=expected:raise RuntimeError("Checksum mismatch: "+name)
            listed[name]=expected
        if set(listed)!=set(records)-{"SHA256SUMS.txt"}:raise RuntimeError("Incomplete checksum inventory")
    return {"name":path.name,"bytes":path.stat().st_size,"files":len(records),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--results",type=Path,required=True);ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--validation",type=Path,default=Path(__file__).resolve().parents[1]/"validation")
    args=ap.parse_args();root=Path(__file__).resolve().parents[1]
    args.out.mkdir(parents=True,exist_ok=True)
    common={str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*") if included(p,root,False)}
    software=write_archive(args.out/"EntrySignalLab_v0.25.0_Software.zip",common)
    complete={str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*") if included(p,root,True)}
    complete.update({"results/"+str(p.relative_to(args.results)):p.read_bytes() for p in args.results.rglob("*") if p.is_file()})
    complete.update({"validation/"+str(p.relative_to(args.validation)):p.read_bytes() for p in args.validation.rglob("*") if p.is_file()})
    full=write_archive(args.out/"EntrySignalLab_v0.25.0_Complete.zip",complete)
    publication=root/'publication'
    flat_names=['manuscript.tex','manuscript.pdf','supplementary.tex','supplementary.pdf',
                'references.json','word_count.json','SUBMISSION_READINESS.md',
                'architecture.pdf','demand_trajectories.pdf','sensitivity.pdf','benchmark.pdf','strategy_regions.pdf']
    flat={name:(publication/name).read_bytes() for name in flat_names}
    flat['README.md']=b"""# EntrySignalLab 0.25.0 SoftwareX manuscript sources

Extract every file into one fresh directory. Compile locally with:

```sh
pdflatex -interaction=nonstopmode -halt-on-error manuscript.tex
pdflatex -interaction=nonstopmode -halt-on-error manuscript.tex
pdflatex -interaction=nonstopmode -halt-on-error supplementary.tex
```

All five vector figures are at the same level as the TeX sources. No original project path is needed. The bundled PDFs are reference renderings; a rebuild can change PDF metadata without changing the page images. SHA256SUMS.txt checks the supplied bytes before rebuilding. The complete release includes the shared Markdown source, editable Word manuscript, software, experiments and audit evidence.

Letter article format is a portable review format. The current official SoftwareX template and editorial word-count interpretation remain unverified. Complete human authorship, source bibliography and public archival links before submission. See SUBMISSION_READINESS.md.
"""
    latex=write_archive(args.out/'EntrySignalLab_v0.25.0_LaTeX.zip',flat,prefix='')
    documents=[]
    for name in ['EntrySignalLab_SoftwareX_v0.25.0.docx','EntrySignalLab_v0.25.0_Audit_Response_zh.docx']:
        target=args.out/name;shutil.copyfile(publication/name,target)
        documents.append({'name':name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    print(json.dumps([full,software,documents[0],latex,documents[1]],indent=2))

if __name__=="__main__":main()
