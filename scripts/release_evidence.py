"""Shared release input and publication integrity checks. MIT License."""
from pathlib import Path
from entrysignallab import __version__
from entrysignallab.workflow import (read_json,sha256,verify_manifest,current_source_hashes,
                                   verify_validation,verify_test_evidence)
from sync_api_docs import synchronize
from wheel_contract import verify_wheel_contract

def verify_experiment_spec(root,name,record,spec):
    """Bind an experiment to its shipped recipe before synchronizing outputs."""
    inputs={}
    if 'config_path' in spec:
        config_path=spec['config_path'];expected_config=read_json(Path(root)/config_path)
        inputs[config_path]=sha256(Path(root)/config_path)
    else:expected_config=spec['config']
    if record['operation']!=spec['operation']:raise ValueError('experiment operation mismatch: '+name)
    if record['config']!=expected_config:raise ValueError('experiment configuration mismatch: '+name)
    if record['seed']!=expected_config.get('seed',104):raise ValueError('experiment seed mismatch: '+name)
    return inputs

def release_inputs(root,results,validation):
    root=Path(root);results=Path(results);validation=Path(validation)
    synchronize(root,check=True)
    contract=read_json(root/'scripts/release_contract.json')
    if contract['version']!=__version__:raise ValueError('release contract version mismatch')
    expected=set(contract['experiments'])
    specs=contract['experiment_specs']
    if set(specs)!=expected:raise ValueError('experiment specification inventory mismatch')
    actual={p.name for p in results.iterdir() if p.is_dir()}
    if expected!=actual:raise ValueError('result directory inventory mismatch; missing='+str(sorted(expected-actual))+'; extra='+str(sorted(actual-expected)))
    hashes={};records={};checks=[]
    for name in contract['experiments']:
        check=verify_manifest(results/name,current_source_hashes())
        if not check['valid']:raise ValueError('invalid experiment '+name+': '+'; '.join(check['errors']))
        m=read_json(results/name/'manifest.json')
        if m['version']!=__version__:raise ValueError('experiment version mismatch: '+name)
        hashes.update(verify_experiment_spec(root,name,m,specs[name]))
        hashes['results/'+name+'/manifest.json']=sha256(results/name/'manifest.json')
        records[name]=m;checks.append('experiment:'+name)
    for name,spec in contract['validators'].items():
        check=verify_validation(validation/name,root/'scripts'/spec['script'],spec['seed'])
        if not check['valid']:raise ValueError('invalid validator '+name+': '+'; '.join(check['errors']))
        hashes['validation/'+name+'/manifest.json']=sha256(validation/name/'manifest.json')
        checks.append('validator:'+name)
    check=verify_test_evidence(validation/'tests',root/'scripts/run_tests.py',root/'tests')
    if not check['valid']:raise ValueError('invalid tests: '+'; '.join(check['errors']))
    hashes['validation/tests/manifest.json']=sha256(validation/'tests/manifest.json');checks.append('tests')
    for name in ['scripts/release_contract.json','scripts/release_evidence.py','publication/sync_evidence.py',
                 'publication/manuscript.template.md','publication/references.json','publication/supplementary.tex',
                 'publication/build_documents.py','publication/build_figures.py','publication/count_words.py',
                 'audit/v0.4.0/strict_audit_zh.md','audit/v0.4.0/baseline_probes.json','audit/v0.4.0/baseline_identity.json',
                 'audit/v0.5.0/strict_audit_zh.md','audit/v0.5.0/baseline_probes.json','audit/v0.5.0/baseline_identity.json',
                 'audit/v0.5.0/probe_baseline.py','audit/v0.5.0/latex_package_probe.json','audit/v0.5.0/template_access.json',
                 'audit/v0.6.0/strict_audit_zh.md','audit/v0.6.0/baseline_probes.json','audit/v0.6.0/baseline_identity.json',
                 'audit/v0.6.0/probe_baseline.py','examples/bounded_evaluation.json',
                 'audit/v0.7.0/strict_audit_zh.md','audit/v0.7.0/baseline_probes.json','audit/v0.7.0/baseline_identity.json','audit/v0.7.0/probe_baseline.py',
                 'audit/v0.8.0/strict_audit_zh.md','audit/v0.8.0/baseline_identity.json','audit/v0.8.0/requirements-lock.txt',
                 'audit/v0.8.0/EntrySignalLab_v0.8.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.8.0/probe_v080.py','audit/v0.8.0/probe_batch_v080.py',
                 'audit/v0.8.0/evidence/probe_results.json','audit/v0.8.0/evidence/batch_probe_results.json',
                 'audit/v0.9.0/baseline_identity.json','audit/v0.9.0/audit_report_source.md',
                 'audit/v0.10.0/EntrySignalLab_v0.10.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.9.0/EntrySignalLab_v0.9.0_Audit_Evidence_20261018.zip',
                 'audit/v0.9.0/probe_numerics.py','audit/v0.9.0/probe_batch.py','audit/v0.9.0/probe_resume_control.py',
                 'audit/v0.9.0/EntrySignalLab_v0.9.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.10.0/input_identity.json','audit/v0.10.0/audit_report_source.md',
                 'audit/v0.10.0/EntrySignalLab_v0.10.0_Complete.zip','audit/v0.10.0/EntrySignalLab_v0.10.0_Audit_Evidence_20261018.zip',
                 'audit/v0.10.0/probe_numerics.py','audit/v0.10.0/probe_contracts.py','docs/v0110_acceptance.md',
                 'audit/v0.11.0/input_identity.json','audit/v0.11.0/audit_report_source.md',
                 'audit/v0.11.0/EntrySignalLab_v0.11.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.11.0/EntrySignalLab_v0.11.0_Audit_Evidence_20261018.zip',
                 'audit/v0.11.0/probe_numerics.py','audit/v0.11.0/probe_contracts.py','docs/v0120_acceptance.md',
                 'audit/v0.12.0/input_identity.json','audit/v0.12.0/audit_report_source.md',
                 'audit/v0.12.0/EntrySignalLab_v0.12.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.12.0/EntrySignalLab_v0.12.0_Audit_Evidence_20261018.zip',
                 'audit/v0.12.0/probe_numerics.py','audit/v0.12.0/probe_research.py','docs/v0130_acceptance.md',
                 'audit/v0.13.0/input_identity.json','audit/v0.13.0/audit_report_source.md',
                 'audit/v0.13.0/EntrySignalLab_v0.13.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.13.0/EntrySignalLab_v0.13.0_Audit_Evidence_20261018.zip',
                 'audit/v0.13.0/probe_v0130.py','docs/v0140_acceptance.md',
                 'audit/v0.14.0/input_identity.json','audit/v0.14.0/probe_v0140.py',
                 'audit/v0.14.0/EntrySignalLab_v0.14.0_Strict_Audit_zh_20261018.docx',
                 'audit/v0.14.0/EntrySignalLab_v0.14.0_Audit_Evidence_20261018.zip',
                 'audit/v0.14.0/valid_stream_golden.json','tests/data/v0140_stream_golden.json',
                 'audit/v0.15.0/input_identity.json','audit/v0.15.0/probe_followup.py',
                 'audit/v0.15.0/EntrySignalLab_v0.14.0_Followup_Audit_zh_20261018.docx',
                 'audit/v0.15.0/EntrySignalLab_v0.14.0_Followup_Audit_Evidence_20261018.zip',
                 'audit/v0.15.0/baseline_observations/observations.json','audit/v0.15.0/wilson_ordinary_golden.json',
                 'tests/data/v0150_followup_observations.json','tests/data/v0150_wilson_ordinary_golden.json',
                 'audit/v0.16.0/input_identity.json','audit/v0.16.0/probe_round3.py',
                 'audit/v0.16.0/probe_numeric_controls.py',
                 'audit/v0.16.0/EntrySignalLab_v0.14.0_Second_Followup_Audit_zh_20261018.docx',
                 'audit/v0.16.0/EntrySignalLab_v0.14.0_Second_Followup_Audit_Evidence_20261018.zip',
                 'audit/v0.16.0/baseline_observations/observations.json',
                 'tests/data/v0160_round3_observations.json','scripts/probe_numeric_controls.py',
                 'docs/v0180_acceptance.md','tests/data/v0170_observations.json','tests/data/v0170_cancellation_corpus.json',
                 'audit/v0.17.0/input_identity.json','audit/v0.17.0/probe_original.py',
                 'audit/v0.17.0/EntrySignalLab_v0.17.0_Audit_zh_20261019.docx',
                 'audit/v0.17.0/EntrySignalLab_v0.17.0_Audit_Evidence_20261019.zip',
                 'audit/v0.17.0/baseline_observations/observations.json',
                 'docs/v0170_acceptance.md','docs/v0160_acceptance.md','docs/v0150_acceptance.md','docs/v0100_acceptance.md','docs/batch_ownership.md','docs/reproducibility.md','.github/workflows/tests.yml','scripts/workflow_performance.py',
                 'scripts/build_release.py','scripts/reproduce.py','scripts/unit_invariance.py',
                 'scripts/validation_portability.py','scripts/package_release.py','scripts/check_release.py','scripts/probe_release_gate.py',
                 'pyproject.toml','requirements-lock.txt','CITATION.cff.template','LICENSE',
                 'README.md','README_zh.md','CHANGELOG.md','docs/api.md','docs/model_contract.md',
                 'docs/source_audit.md','docs/joint_envelope.md','docs/related_software.md']:
        hashes[name]=sha256(root/name)
    for name in ['docs/v0190_acceptance.md', 'tests/data/v0180_comparison_observations.json', 'tests/data/v0180_comparison_corpus.json', 'audit/v0.18.0/input_identity.json', 'audit/v0.18.0/probe_original.py', 'audit/v0.18.0/EntrySignalLab_v0.18.0_Audit_zh_20261019.docx', 'audit/v0.18.0/EntrySignalLab_v0.18.0_Audit_Evidence_20261019.zip']:
        hashes[name]=sha256(root/name)
    frozen=read_json(root/'audit/v0.18.0/input_identity.json')['frozen_inputs']
    for relative,digest in frozen.items():
        name='audit/v0.18.0/'+relative
        if sha256(root/name)!=digest:raise ValueError('frozen v0.18.0 input changed: '+relative)
        hashes[name]=digest
    for name in ['docs/v0200_acceptance.md','tests/data/v0190_A13_boundary_corpus.json','tests/data/v0190_A14_observations.json','audit/v0.19.0/input_identity.json']:
        hashes[name]=sha256(root/name)
    frozen=read_json(root/'audit/v0.19.0/input_identity.json')['frozen_inputs']
    for relative,digest in frozen.items():
        name='audit/v0.19.0/'+relative
        if sha256(root/name)!=digest:raise ValueError('frozen v0.19.0 input changed: '+relative)
        hashes[name]=digest
    for name in ['docs/v0210_acceptance.md','tests/data/v0200_A15_boundary_corpus.json','audit/v0.20.0/input_identity.json']:
        hashes[name]=sha256(root/name)
    frozen=read_json(root/'audit/v0.20.0/input_identity.json')['frozen_inputs']
    for relative,digest in frozen.items():
        name='audit/v0.20.0/'+relative
        if sha256(root/name)!=digest:raise ValueError('frozen v0.20.0 input changed: '+relative)
        hashes[name]=digest
    for name in ['docs/v0220_acceptance.md','tests/data/v0210_A16_rational_corpus.json',
                 'tests/data/v0210_A16_underflow.json','tests/data/v0210_A16_corpus_identity.json','audit/v0.21.0/input_identity.json',
                 'scripts/sync_api_docs.py']:
        hashes[name]=sha256(root/name)
    frozen=read_json(root/'audit/v0.21.0/input_identity.json')['frozen_files']
    for relative,digest in frozen.items():
        name='audit/v0.21.0/'+relative
        if sha256(root/name)!=digest:raise ValueError('frozen v0.21.0 input changed: '+relative)
        hashes[name]=digest
    for name in ['docs/v0230_acceptance.md','audit/v0.22.0/input_identity.json','tests/data/v0220_corpus_identity.json']:
        hashes[name]=sha256(root/name)
    for name,digest in read_json(root/'tests/data/v0220_corpus_identity.json').items():
        path='tests/data/'+name
        if sha256(root/path)!=digest:raise ValueError('frozen v0.22.0 corpus changed: '+name)
        hashes[path]=digest
    for name,digest in read_json(root/'audit/v0.22.0/input_identity.json')['files'].items():
        path='audit/v0.22.0/'+name
        if sha256(root/path)!=digest:raise ValueError('frozen v0.22.0 input changed: '+name)
        hashes[path]=digest
    for name in ['docs/v0240_acceptance.md','tests/data/v0230_corpus_identity.json','audit/v0.23.0/frozen_identity.json']:
        hashes[name]=sha256(root/name)
    for name,digest in read_json(root/'tests/data/v0230_corpus_identity.json').items():
        path='tests/data/'+name
        if sha256(root/path)!=digest:raise ValueError('frozen v0.23.0 corpus changed: '+name)
        hashes[path]=digest
    for name,digest in read_json(root/'audit/v0.23.0/frozen_identity.json')['files'].items():
        path='audit/v0.23.0/'+name
        if sha256(root/path)!=digest:raise ValueError('frozen v0.23.0 audit changed: '+name)
        hashes[path]=digest
    for name in ['docs/v0250_acceptance.md','tests/data/v0240_corpus_identity.json','audit/v0.24.0/frozen_identity.json']:
        hashes[name]=sha256(root/name)
    for name,digest in read_json(root/'tests/data/v0240_corpus_identity.json').items():
        path='tests/data/'+name
        if sha256(root/path)!=digest:raise ValueError('frozen v0.24.0 corpus changed: '+name)
        hashes[path]=digest
    for name,digest in read_json(root/'audit/v0.24.0/frozen_identity.json')['files'].items():
        path='audit/v0.24.0/'+name
        if sha256(root/path)!=digest:raise ValueError('frozen v0.24.0 audit changed: '+name)
        hashes[path]=digest
    current_wheel=verify_wheel_contract(root)
    hashes['dist/'+current_wheel['wheel']]=current_wheel['sha256']
    hashes['scripts/wheel_contract.py']=sha256(root/'scripts/wheel_contract.py')
    checks.append('wheel:installation_metadata_and_record')
    return contract,hashes,checks

def verify_publication(root,results,validation):
    """Require the complete input graph and exact sealed publication bytes."""
    root=Path(root);contract,inputs,checks=release_inputs(root,results,validation)
    pub=root/'publication';sync=read_json(pub/'evidence_sync.json')
    if sync.get('version')!=__version__ or sync.get('release_inputs_sha256')!=inputs:
        raise ValueError('publication inputs changed since synchronization')
    if sync.get('validated_experiments')!=contract['experiments']:
        raise ValueError('publication experiment inventory mismatch')
    if sync.get('generated_manuscript_sha256')!=sha256(pub/'manuscript.md'):
        raise ValueError('manuscript changed since synchronization')
    for name,digest in sync['main_figures_sha256'].items():
        if sha256(pub/'figures'/name)!=digest:raise ValueError('figure changed since synchronization: '+name)
    receipt=read_json(pub/'publication_receipt.json')
    if receipt.get('version')!=__version__ or receipt.get('evidence_sync_sha256')!=sha256(pub/'evidence_sync.json'):
        raise ValueError('publication receipt is stale')
    if receipt.get('sealer_sha256')!=sha256(pub/'seal_publication.py'):
        raise ValueError('publication sealer changed')
    required={'manuscript.md','manuscript.tex','manuscript.pdf','supplementary.tex','supplementary.pdf',
              'word_count.json','SUBMISSION_READINESS.md','revision_response_zh.md',
              'EntrySignalLab_SoftwareX_v'+__version__+'.docx',
              'EntrySignalLab_v'+__version__+'_Audit_Response_zh.docx','EntrySignalLab_v0.14.0_Followup_Audit_zh_20261018.docx'}
    required.add('EntrySignalLab_v0.14.0_Second_Followup_Audit_zh_20261018.docx')
    required.add('EntrySignalLab_v0.17.0_Audit_zh_20261019.docx')
    required.add('EntrySignalLab_v0.18.0_Audit_zh_20261019.docx')
    required.add('EntrySignalLab_v0.19.0_Audit_zh_20261019.docx')
    required.add('EntrySignalLab_v0.20.0_Audit_zh_20261019.docx')
    required.add('EntrySignalLab_v0.21.0_Audit_zh_20261019.docx')
    required.add('EntrySignalLab_v0.22.0_Audit_zh.docx')
    required.add('EntrySignalLab_v0.23.0_Audit_zh.docx')
    required.add('EntrySignalLab_v0.24.0_Audit_zh.docx')
    required|={'figures/'+name+'.'+suffix for name in ['architecture','demand_trajectories','sensitivity','benchmark','strategy_regions'] for suffix in ['png','pdf']}
    required|={name+'.pdf' for name in ['architecture','demand_trajectories','sensitivity','benchmark','strategy_regions']}
    if set(receipt.get('outputs_sha256',{}))!=required:raise ValueError('publication receipt output inventory mismatch')
    for name,digest in receipt['outputs_sha256'].items():
        if sha256(pub/name)!=digest:raise ValueError('sealed publication changed: '+name)
    return checks+['publication:inputs','publication:manuscript','publication:figures','publication:receipt','publication:outputs']
