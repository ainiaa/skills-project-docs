"""Read original Converge evidence and link executed selectors to PRD acceptance. 作者：Jeff.Liu"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from product_inputs import freeze_inputs, require_current_inputs, validate_snapshot


# Validate with the explicitly selected provider's own receipt and selector rules.
VERIFY = '''import json,sys
sys.path.insert(0, sys.argv[1])
from evidence_contract import validate_observed_evidence_receipt, workspace_source
from tdd_impact_guard import runner_selector_matches
receipt=json.load(sys.stdin)
validate_observed_evidence_receipt(receipt)
if receipt['source'] != workspace_source(sys.argv[2], sys.argv[3]):
    raise ValueError('evidence does not bind current project source')
if not runner_selector_matches(receipt['argv'], sys.argv[4]):
    raise ValueError('test selector does not match executed command')
counts=receipt.get('test_check', {})
if receipt['exit_code'] != 0 or counts.get('passed',0) <= 0 or any(
    counts.get(key,0) for key in ('failed','errors','skipped','xfailed','xpassed')):
    raise ValueError('required tests did not all execute and pass')
print(json.dumps(counts))
'''


def verification_code_fingerprint(provider):
    scripts = Path(provider).resolve() / 'scripts'
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in scripts.glob('*.py')
             if not path.name.startswith('test_')}
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def verify_receipt(receipt, selector, provider, workspace, baseline, expected_code_fingerprint=None):
    scripts = Path(provider).resolve() / 'scripts'
    if expected_code_fingerprint is not None and verification_code_fingerprint(provider) != expected_code_fingerprint:
        raise ValueError('selected provider changed while checking test evidence')
    if not all((scripts / name).is_file() for name in ('evidence_contract.py', 'tdd_impact_guard.py')):
        raise ValueError('selected Converge provider is unavailable')
    result = subprocess.run([sys.executable, '-B', '-c', VERIFY, str(scripts), str(workspace), baseline, selector],
                            input=json.dumps(receipt), capture_output=True, text=True, timeout=30)
    if expected_code_fingerprint is not None and verification_code_fingerprint(provider) != expected_code_fingerprint:
        raise ValueError('selected provider changed while checking test evidence')
    if result.returncode != 0:
        reason = result.stderr.strip().splitlines()
        raise ValueError('provider rejected evidence: ' + (reason[-1] if reason else f'exit {result.returncode}'))
    return json.loads(result.stdout)


def check(prd, links, provider, workspace, baseline):
    result = {'valid': False, 'ready': False, 'coverage': {}, 'gaps': [],
              'verification': 'provider_test_execution', 'business_authorization': False,
              'tdd_verified': False, 'deployment_verified': False}
    try:
        prd = Path(prd).resolve()
        frozen = links.get('inputs') if isinstance(links, dict) else None
        if frozen is not None:
            validate_snapshot(frozen)
        snapshot = freeze_inputs(prd, tracking=frozen['tracking'] if frozen else None,
                                 attachments=frozen['attachments'] if frozen else None)
        if frozen is not None and frozen != snapshot:
            raise ValueError('mapping product inputs changed')
        if frozen is None and len(snapshot['files']) != 1:
            raise ValueError('mapping must freeze all product inputs, including attachments')
        version, acceptance = snapshot['product_version'], snapshot['acceptance']
        prd_sha = next(item['sha256'] for item in snapshot['files'] if item['path'] == str(prd))
        bound = {'path': str(prd), 'version': version, 'sha256': prd_sha}
        if not isinstance(links, dict) or set(links) != ({'prd', 'acceptance', 'inputs'} if frozen is not None else {'prd', 'acceptance'}) or links['prd'] != bound:
            raise ValueError('mapping must freeze the current PRD path, version and SHA-256')
        links = links['acceptance']
        if not isinstance(links, dict) or set(links) - set(acceptance):
            raise ValueError('mapping contains acceptance not declared in the formal PRD')
        provider = Path(provider).resolve()
        provider_fingerprint = verification_code_fingerprint(provider)
        result.update(valid=True, product_version=version, prd_sha256=prd_sha, input_fingerprint=snapshot['fingerprint'],
                      provider_root=str(provider), verification_code_fingerprint=provider_fingerprint)
        bound_evidence = None
        for criterion in acceptance:
            entries = links.get(criterion)
            if not isinstance(entries, list) or not entries:
                result['gaps'].append({'acceptance': criterion, 'reason': 'test evidence missing'})
                continue
            selectors = []
            for entry in entries:
                try:
                    if not isinstance(entry, dict) or set(entry) != {'receipt', 'selector'}:
                        raise ValueError('each mapping requires only receipt and selector')
                    selector = entry['selector']
                    if not isinstance(selector, str) or not selector.strip() or selector in selectors:
                        raise ValueError('test selector must be nonempty and unique per acceptance')
                    receipt = json.loads(Path(entry['receipt']).read_text())
                    verify_receipt(receipt, selector, provider, workspace, baseline, provider_fingerprint)
                    if bound_evidence and receipt['source'] != bound_evidence[0]['source']:
                        raise ValueError('all acceptance evidence must bind the same project source')
                    bound_evidence = (receipt, selector)
                    selectors.append(selector)
                except (OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
                    result['gaps'].append({'acceptance': criterion, 'reason': str(error)})
            result['coverage'][criterion] = selectors
        if bound_evidence:
            verify_receipt(*bound_evidence, provider, workspace, baseline, provider_fingerprint)
        if verification_code_fingerprint(provider) != provider_fingerprint:
            raise ValueError('selected provider changed while checking test evidence')
        require_current_inputs(snapshot)
        result['ready'] = not result['gaps']
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        result.update(valid=False, ready=False)
        result['gaps'].append({'reason': str(error)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prd', 'mapping', 'provider-root', 'workspace', 'baseline'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try:
        mapping_path = Path(args.mapping).resolve()
        mapping = json.loads(mapping_path.read_text())
        if isinstance(mapping, dict) and isinstance(mapping.get('prd'), dict):
            if isinstance(mapping['prd'].get('path'), str):
                mapping['prd']['path'] = str((mapping_path.parent / mapping['prd']['path']).resolve())
        if isinstance(mapping, dict) and isinstance(mapping.get('acceptance'), dict):
            for entries in mapping['acceptance'].values():
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and isinstance(entry.get('receipt'), str):
                            entry['receipt'] = str((mapping_path.parent / entry['receipt']).resolve())
        result = check(args.prd, mapping, args.provider_root, args.workspace, args.baseline)
    except (OSError, ValueError) as error:
        result = {'valid': False, 'ready': False, 'gaps': [{'reason': str(error)}]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
