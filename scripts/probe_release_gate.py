"""Reject changed or missing release evidence in disposable copies."""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,shutil
from entrysignallab import __version__
from entrysignallab.workflow import read_json,write_json
from release_evidence import verify_publication

def main():
    root=Path(__file__).resolve().parents[1]
    ap=argparse.ArgumentParser();ap.add_argument('--results',type=Path,required=True);ap.add_argument('--validation',type=Path,required=True);args=ap.parse_args();rows=[]
    with TemporaryDirectory() as td:
        work=Path(td)/'release';shutil.copytree(root,work,ignore=shutil.ignore_patterns('__pycache__','build','results','validation'))
        shutil.copytree(args.results,work/'results');shutil.copytree(args.validation,work/'validation')
        results=work/'results';validation=work/'validation'
        verify_publication(work,results,validation);rows.append({'case':'pristine_copy','pass':True})
        def reject(name,change,restore):
            change()
            try:
                verify_publication(work,results,validation);accepted=True;reason='unexpectedly accepted'
            except (OSError,ValueError,KeyError,TypeError) as error:
                accepted=False;reason=str(error)
            finally:restore()
            rows.append({'case':name,'pass':not accepted,'reason':reason})
        from validate_wheel import mutated_wheel_bytes
        current=work/'dist'/f'entrysignallab-{__version__}-py3-none-any.whl'
        original_wheel=current.read_bytes()
        for case in ('missing_console_entrypoint','incompatible_python'):
            reject('current_wheel_'+case,
                   lambda case=case:current.write_bytes(mutated_wheel_bytes(original_wheel,case)),
                   lambda:current.write_bytes(original_wheel))
        edge=results/'edge_peak';held=work/'held_edge_peak' 
        reject('missing_required_experiment',lambda:edge.rename(held),lambda:held.rename(edge))
        extra=results/'extra';reject('unexpected_experiment',lambda:extra.mkdir(),lambda:extra.rmdir())
        def mutate_file(name,path,new_data):
            original=path.read_bytes();reject(name,lambda:path.write_bytes(new_data),lambda:path.write_bytes(original))
        p=results/'edge_peak/manifest.json';record=read_json(p);record['version']='9.9.9'
        mutate_file('wrong_experiment_version',p,json.dumps(record).encode())
        p=results/'baseline/manifest.json';record=read_json(p);record['operation']='audit'
        mutate_file('wrong_experiment_operation',p,json.dumps(record).encode())
        record=read_json(p);record['seed']+=1
        mutate_file('wrong_experiment_seed',p,json.dumps(record).encode())
        p=validation/'envelope/manifest.json';record=read_json(p);record['seed']=0
        mutate_file('wrong_validator_seed',p,json.dumps(record).encode())
        p=work/'tests/test_v040_audit.py';mutate_file('changed_test_suite',p,p.read_bytes()+b'\n# Changed suite\n')
        p=work/'scripts/run_tests.py';mutate_file('changed_test_runner',p,p.read_bytes()+b'\n# Changed runner\n')
        p=validation/'tests/unit_tests.log';mutate_file('changed_test_log',p,p.read_bytes()+b'FAILED\n')
        p=work/'examples/product_launch.json';record=read_json(p);record['params']['deployment_cost']=.5
        mutate_file('changed_example',p,json.dumps(record).encode())
        for name,path in [('changed_reproducer',work/'scripts/reproduce.py'),
                          ('changed_packager',work/'scripts/package_release.py'),
                          ('changed_build_orchestrator',work/'scripts/build_release.py'),
                          ('changed_dependency_lock',work/'requirements-lock.txt'),
                          ('changed_project_metadata',work/'pyproject.toml'),
                          ('changed_repair_validator',work/'scripts/validate_repairs.py'),
                          ('changed_v0100_validator',work/'scripts/validate_v0100.py'),
                          ('changed_v0110_validator',work/'scripts/validate_v0110.py'),
                          ('changed_v0120_validator',work/'scripts/validate_v0120.py'),
                          ('changed_v0130_validator',work/'scripts/validate_v0130.py'),
                          ('changed_v0140_validator',work/'scripts/validate_v0140.py'),
                          ('changed_v0150_validator',work/'scripts/validate_v0150.py'),
                          ('changed_v0160_validator',work/'scripts/validate_v0160.py'),
                          ('changed_v0170_validator',work/'scripts/validate_v0170.py'),
                          ('changed_v0180_validator',work/'scripts/validate_v0180.py'),
                          ('changed_v0190_validator',work/'scripts/validate_v0190.py'),
                          ('changed_v0200_validator',work/'scripts/validate_v0200.py'),
                          ('changed_v0210_validator',work/'scripts/validate_v0210.py'),
                          ('changed_v0250_validator',work/'scripts/validate_v0250.py'),
                          ('changed_v0250_contract',work/'docs/v0250_acceptance.md'),
                          ('changed_typed_fixture',work/'tests/data/v0240_ingress_observations.json'),
                          ('changed_profile_fixture',work/'tests/data/v0240_profile_cases.json'),
                          ('changed_probe_fixture',work/'tests/data/v0240_probe_baselines.json'),
                          ('changed_v0240_frozen_solver',work/'audit/v0.24.0/original/src/entrysignallab/solver.py'),
                          ('changed_v0240_frozen_wheel',work/'audit/v0.24.0/original/dist/entrysignallab-0.24.0-py3-none-any.whl'),
                          ('changed_v0240_frozen_audit',work/'audit/v0.24.0/EntrySignalLab_v0.24.0_Audit_Evidence.zip'),
                          ('changed_probe_example',work/'examples/recorded_probe_promoted.json'),
                          ('changed_v0240_validator',work/'scripts/validate_v0240.py'),
                          ('changed_wheel_validator',work/'scripts/validate_wheel.py'),
                          ('changed_wheel_contract',work/'scripts/wheel_contract.py'),
                          ('changed_v0240_contract',work/'docs/v0240_acceptance.md'),
                          ('changed_gross_fixture',work/'tests/data/v0230_cancellation_comparisons.json'),
                          ('changed_root_fixture',work/'tests/data/v0230_representable_root_edges.json'),
                          ('changed_node_fixture',work/'tests/data/v0230_evaluated_node_observations.json'),
                          ('changed_v0230_frozen_solver',work/'audit/v0.23.0/original/src/entrysignallab/solver.py'),
                          ('changed_v0230_frozen_wheel',work/'audit/v0.23.0/original/dist/entrysignallab-0.23.0-py3-none-any.whl'),
                          ('changed_v0230_frozen_audit',work/'audit/v0.23.0/EntrySignalLab_v0.23.0_Audit_Evidence.zip'),
                          ('changed_gross_example',work/'examples/gross_cancellation_ranking.json'),
                          ('changed_v0230_validator',work/'scripts/validate_v0230.py'),
                          ('changed_v0230_contract',work/'docs/v0230_acceptance.md'),
                          ('changed_A17_fixture',work/'tests/data/v0220_A17_stationarity.json'),
                          ('changed_A18_fixture',work/'tests/data/v0220_A18_effect.json'),
                          ('changed_A18_root_fixture',work/'tests/data/v0220_A18_roots.json'),
                          ('changed_legacy_fixture',work/'tests/data/v0220_D02_residual.json'),
                          ('changed_v0220_frozen_model',work/'audit/v0.22.0/original/src/entrysignallab/model.py'),
                          ('changed_v0220_frozen_wheel',work/'audit/v0.22.0/original/dist/entrysignallab-0.22.0-py3-none-any.whl'),
                          ('changed_v0220_frozen_audit',work/'audit/v0.22.0/EntrySignalLab_v0.22.0_Audit_Evidence.zip'),
                          ('changed_quality_warning_example',work/'examples/quality_warning_html.json'),
                          ('changed_v0220_validator',work/'scripts/validate_v0220.py'),
                          ('changed_v0220_contract',work/'docs/v0220_acceptance.md'),
                          ('changed_mesh_rational_corpus',work/'tests/data/v0210_A16_rational_corpus.json'),
                          ('changed_mesh_underflow_corpus',work/'tests/data/v0210_A16_underflow.json'),
                          ('changed_api_generator',work/'scripts/sync_api_docs.py'),
                          ('changed_api_guide',work/'docs/api.md'),
                          ('changed_v0210_frozen_solver',work/'audit/v0.21.0/original/src/entrysignallab/solver.py'),
                          ('changed_v0210_frozen_wheel',work/'audit/v0.21.0/original/dist/entrysignallab-0.21.0-py3-none-any.whl'),
                          ('changed_v0210_audit_archive',work/'audit/v0.21.0/EntrySignalLab_v0.21.0_Audit_Evidence_20261019.zip'),
                          ('changed_mesh_spread_example',work/'examples/mesh_spread_near_equal.json'),
                          ('changed_documented_uncertainty_example',work/'examples/documented_uncertainty_batch.json'),
                          ('changed_v0210_contract',work/'docs/v0210_acceptance.md'),
                          ('changed_candidate_corpus',work/'tests/data/v0200_A15_boundary_corpus.json'),
                          ('changed_v0200_frozen_solver',work/'audit/v0.20.0/original/src/entrysignallab/solver.py'),
                          ('changed_v0200_frozen_wheel',work/'audit/v0.20.0/original/wheel/entrysignallab-0.20.0-py3-none-any.whl'),
                          ('changed_v0200_audit_archive',work/'audit/v0.20.0/EntrySignalLab_v0.20.0_Audit_Evidence_20261019.zip'),
                          ('changed_underflow_profile_example',work/'examples/underflow_profile_search.json'),
                          ('changed_v0200_contract',work/'docs/v0200_acceptance.md'),
                          ('changed_extreme_decay_corpus',work/'tests/data/v0190_A13_boundary_corpus.json'),
                          ('changed_point_observations',work/'tests/data/v0190_A14_observations.json'),
                          ('changed_v0190_frozen_module',work/'audit/v0.19.0/original/src/entrysignallab/model.py'),
                          ('changed_v0190_frozen_wheel',work/'audit/v0.19.0/original/wheel/entrysignallab-0.19.0-py3-none-any.whl'),
                          ('changed_v0190_audit_archive',work/'audit/v0.19.0/EntrySignalLab_v0.19.0_Audit_Evidence_20261019.zip'),
                          ('changed_extreme_decay_example',work/'examples/extreme_decay_negative.json'),
                          ('changed_duplicate_example',work/'examples/duplicate_sensitivity.json'),
                          ('changed_v0190_contract',work/'docs/v0190_acceptance.md'),
                          ('changed_comparison_observations',work/'tests/data/v0180_comparison_observations.json'),
                          ('changed_comparison_corpus',work/'tests/data/v0180_comparison_corpus.json'),
                          ('changed_v0180_frozen_module',work/'audit/v0.18.0/original/src/entrysignallab/model.py'),
                          ('changed_v0180_frozen_wheel',work/'audit/v0.18.0/original/wheel/entrysignallab-0.18.0-py3-none-any.whl'),
                          ('changed_v0180_audit_archive',work/'audit/v0.18.0/EntrySignalLab_v0.18.0_Audit_Evidence_20261019.zip'),
                          ('changed_outside_example',work/'examples/near_outside_positive.json'),
                          ('changed_singleton_example',work/'examples/singleton_surface.json'),
                          ('changed_v0180_contract',work/'docs/v0180_acceptance.md'),
                          ('changed_v0170_observations',work/'tests/data/v0170_observations.json'),
                          ('changed_cancellation_corpus',work/'tests/data/v0170_cancellation_corpus.json'),
                          ('changed_v0170_audit_inputs',work/'audit/v0.17.0/input_identity.json'),
                          ('changed_v0170_audit_archive',work/'audit/v0.17.0/EntrySignalLab_v0.17.0_Audit_Evidence_20261019.zip'),
                          ('changed_net_cancellation_example',work/'examples/net_cancellation_positive.json'),
                          ('changed_round3_baseline',work/'tests/data/v0160_round3_observations.json'),
                          ('changed_round3_inputs',work/'audit/v0.16.0/input_identity.json'),
                          ('changed_round3_archive',work/'audit/v0.16.0/EntrySignalLab_v0.14.0_Second_Followup_Audit_Evidence_20261018.zip'),
                          ('changed_rational_probe',work/'scripts/probe_numeric_controls.py'),
                          ('changed_v0170_contract_document',work/'docs/v0170_acceptance.md'),
                          ('changed_small_scale_example',work/'examples/small_scale_regions.json'),
                          ('changed_source_scale_example',work/'examples/source_audit_small_scale.json'),
                          ('changed_followup_audit_inputs',work/'audit/v0.15.0/input_identity.json'),
                          ('changed_v0160_contract_document',work/'docs/v0160_acceptance.md'),
                          ('changed_ordinary_interval_fixture',work/'tests/data/v0150_wilson_ordinary_golden.json'),
                          ('changed_v0140_audit_inputs',work/'audit/v0.14.0/input_identity.json'),
                          ('changed_v0150_contract_document',work/'docs/v0150_acceptance.md'),
                          ('changed_v0140_stream_fixture',work/'tests/data/v0140_stream_golden.json'),
                          ('changed_v0130_audit',work/'audit/v0.13.0/audit_report_source.md'),
                          ('changed_v0140_contract_document',work/'docs/v0140_acceptance.md'),
                          ('changed_v0120_audit',work/'audit/v0.12.0/audit_report_source.md'),
                          ('changed_v0130_contract_document',work/'docs/v0130_acceptance.md'),
                          ('changed_v0110_audit',work/'audit/v0.11.0/audit_report_source.md'),
                          ('changed_v0120_contract_document',work/'docs/v0120_acceptance.md'),
                          ('changed_v0100_audit',work/'audit/v0.10.0/audit_report_source.md'),
                          ('changed_subnormal_example',work/'examples/subnormal_payoffs.json'),
                          ('changed_quality_example',work/'examples/unassessed_quality.json'),
                          ('changed_v090_audit',work/'audit/v0.9.0/audit_report_source.md'),
                          ('changed_joint_domain_example',work/'examples/equal_joint_domain.json'),
                          ('changed_ownership_documentation',work/'docs/batch_ownership.md'),
                          ('changed_exhaustion_example',work/'examples/sampling_exhaustion.json')]:
            mutate_file(name,path,path.read_bytes()+b'\n# Changed input\n')
        for name,path in [
            ('changed_markdown',work/'publication/manuscript.md'),
            ('changed_png',work/'publication/figures/architecture.png'),
            ('changed_vector_figure',work/'publication/figures/architecture.pdf'),
            ('changed_flat_vector_figure',work/'publication/architecture.pdf'),
            ('changed_word',work/'publication'/f'EntrySignalLab_SoftwareX_v{__version__}.docx'),
            ('changed_latex',work/'publication/manuscript.tex'),
            ('changed_compiled_pdf',work/'publication/manuscript.pdf')]:
            mutate_file(name,path,path.read_bytes()+b'\n')
        p=work/'publication/publication_receipt.json';record=read_json(p);record['evidence_sync_sha256']='0'*64
        mutate_file('conflicting_publication_receipt',p,json.dumps(record).encode())
        verify_publication(work,results,validation);rows.append({'case':'restored_copy','pass':True})
    report={'version':__version__,'cases':len(rows),'negative_cases':len(rows)-2,'all_pass':all(x['pass'] for x in rows),'checks':rows,
            'scope':'Disposable-copy correspondence probes; does not establish authenticity or actual execution.'}
    write_json(args.validation/'release_gate_probe.json',report);print(json.dumps(report,indent=2))
    if not report['all_pass']:raise SystemExit('Release gate failed adversarial probes')

if __name__=='__main__':main()
