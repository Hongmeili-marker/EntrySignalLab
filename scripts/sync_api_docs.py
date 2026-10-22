"""Generate the current release-count paragraph from its release contract."""
from pathlib import Path
import argparse,json

BEGIN='<!-- BEGIN GENERATED RELEASE CONTRACT -->'
END='<!-- END GENERATED RELEASE CONTRACT -->'

def expected_block(root):
    contract=json.loads((Path(root)/'scripts/release_contract.json').read_text())
    return (BEGIN+'\n'
        f"Publication synchronization requires valid receipts for all {len(contract['validators'])} independent verification directories and {len(contract['experiments'])} experiments declared in `scripts/release_contract.json` for version {contract['version']}. "
        'Regenerate this paragraph with `python scripts/sync_api_docs.py` after updating the contract; `--check` rejects stale text.\n'+END)

def synchronize(root,check=False):
    path=Path(root)/'docs/api.md';text=path.read_text()
    if text.count(BEGIN)!=1 or text.count(END)!=1:raise ValueError('API guide requires one generated release-contract block')
    start=text.index(BEGIN);end=text.index(END,start)+len(END)
    expected=expected_block(root)
    if check:
        if text[start:end]!=expected:raise ValueError('API guide release counts are stale; run scripts/sync_api_docs.py')
    else:path.write_text(text[:start]+expected+text[end:])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');args=ap.parse_args()
    synchronize(Path(__file__).resolve().parents[1],args.check)
    print('API_RELEASE_CONTRACT_OK')
