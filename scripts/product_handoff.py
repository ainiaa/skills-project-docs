#!/usr/bin/env python3
"""Inspect or bind a confirmed PRD to an existing native Converge work item. 作者：Jeff.Liu"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from product_inputs import freeze_inputs, input_references, require_current_inputs
from product_revision import apply_impact, validate_revision


BIND = '''import hashlib,json,subprocess,sys
from pathlib import Path
r=json.load(sys.stdin)
provider=Path(sys.argv[1]).parent
def check_provider():
 paths=[p for p in (provider/'scripts').glob('*.py') if not p.name.startswith('test_')]
 paths.extend(provider/p for p in r['provider_sources'])
 files={str(p.relative_to(provider)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
 fingerprint=hashlib.sha256(json.dumps(files,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 if fingerprint!=r['provider_source_fingerprint']:
  raise ValueError('provider changed before native execution')
check_provider()
sys.path.insert(0,sys.argv[1])
from reference_receipt import freeze_receipt
from work_item import resume_or_create,work_item_path
from delivery_lease import lock_record
references=[{'reference':item['path'],'status':'read','content_fingerprint':item['sha256']} for item in r['input_snapshot']['files']]
reference=freeze_receipt(references)
arguments=dict(state_root=r['state_root'],workspace=r['project'],baseline=r['baseline'],
 target=r['target'],requirements=r['requirements'],acceptance=r['acceptance'])
path=Path(r['revision']['path']) if r.get('revision') else work_item_path(r['state_root'],r['project'],r['baseline'],r['target'],r['requirements'],r['acceptance'])
with lock_record(path.parent/'prd-handoff'):
 check_provider()
 for item in r['input_snapshot']['files']:
  input_path=Path(item['path'])
  if input_path.resolve()!=input_path or hashlib.sha256(input_path.read_bytes()).hexdigest()!=item['sha256']:
   raise ValueError('product input changed before native write')
 baseline=subprocess.check_output(['git','-C',r['project'],'rev-parse','HEAD^{commit}'],text=True).strip()
 if baseline!=r['baseline']:
  raise ValueError('project baseline changed before native write')
 if r.get('revision'):
  from work_item import revise_work_item
  arguments.pop('state_root')
  result=revise_work_item(path,**arguments,decisions=['PRD version: '+r['product_version']],
   reference_receipt=reference,expected_state_fingerprint=r['revision']['expected_state_fingerprint'],reason=r['revision']['reason'])
 else:
  if r.get('iteration'):
   arguments['predecessor_completion']=r['iteration']['completion']
  result=resume_or_create(**arguments,decisions=['PRD version: '+r['product_version']],
   reference_receipt=reference,continuation=True,exclusive_target=True)
print(json.dumps(result))
'''


PROBE = '''import inspect,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import work_item,reference_receipt,delivery_lease
adopt=dict.fromkeys(('state_root','workspace','baseline','target','requirements','acceptance','decisions',
                     'reference_receipt','continuation','exclusive_target'))
revise=dict.fromkeys(('workspace','baseline','target','requirements','acceptance','decisions',
                      'reference_receipt','expected_state_fingerprint','reason'))
specs={'adopt':[(work_item,'resume_or_create',(),adopt),
                (work_item,'work_item_path',(None,)*6,{}),
                (reference_receipt,'freeze_receipt',([],),{}),(delivery_lease,'lock_record',('state.json',),{})],
       'revise':[(work_item,'revise_work_item',('state.json',),revise)],
       'iterate':[(work_item,'resume_or_create',(),{**adopt,'predecessor_completion':None}),
                  (work_item,'read_completion',('completion.json',),{}),
                  (work_item,'completion_path',('state.json',),{})]}
missing={}
for capability,checks in specs.items():
 errors=[]
 for module,name,args,kwargs in checks:
  try:
   function=getattr(module,name)
   if not callable(function):raise TypeError('not callable')
   inspect.signature(function).bind(*args,**kwargs)
  except (AttributeError,TypeError,ValueError) as error:errors.append(name+': '+str(error))
 missing[capability]=errors
missing['revise']+=missing['adopt']
missing['iterate']+=missing['adopt']
version=Path(sys.argv[1]).parent/'VERSION'
print(json.dumps({'protocol':'project-docs-native-capabilities-v1','version':version.read_text().strip() if version.is_file() else 'unknown',
                  'capabilities':{key:not value for key,value in missing.items()},'missing':missing}))
'''


def provider_capabilities(converge_root, capability='adopt'):
    """Check call compatibility without a product document or state writes."""
    if capability not in ('adopt', 'revise', 'iterate'):
        raise ValueError('unknown native capability')
    root = Path(converge_root).expanduser().resolve()
    result = subprocess.run([sys.executable, '-I', '-B', '-c', PROBE, str(root / 'scripts')],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        return {'ready': False, 'capability': capability, 'capabilities': {},
                'missing': {capability: ['cannot load selected native API: ' + result.stderr.strip()]}}
    report = json.loads(result.stdout)
    return {**report, 'capability': capability, 'ready': report['capabilities'][capability]}


def _require_capability(root, capability):
    report = provider_capabilities(root, capability)
    if not report['ready']:
        raise ValueError('selected Converge lacks ' + capability + ' API; update the selected suite: '
                         + '; '.join(report['missing'][capability]))


def _read_completion(root, item_path):
    code = ('import json,sys;sys.path.insert(0,sys.argv[1]);'
            'from work_item import completion_path,read_completion;'
            'p=completion_path(sys.argv[2]);'
            'print(json.dumps({"path":str(p),"completion":read_completion(p)}))')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(Path(root) / 'scripts'), str(item_path)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('predecessor completion is unavailable; complete or reconcile the original work item: '
                         + result.stderr.strip())
    return json.loads(result.stdout)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _business_target(handoff):
    return (handoff.get('iteration', {}).get('business_target')
            or handoff.get('revision', {}).get('business_target') or handoff['target'])


def prepare(prd, converge_root, project, target, state_root, *, tracking=None, attachments=None):
    prd, converge_root, project, state_root = (
        Path(path).expanduser().resolve() for path in (prd, converge_root, project, state_root))
    if not project.is_dir():
        raise ValueError('project directory is unavailable')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', target):
        raise ValueError('invalid target identity')
    snapshot = freeze_inputs(prd, tracking=tracking, attachments=attachments)
    prd_sha = next(item['sha256'] for item in snapshot['files'] if item['path'] == str(prd))
    baseline = subprocess.run(['git', '-C', str(project), 'rev-parse', '--verify', 'HEAD^{commit}'],
                              capture_output=True, text=True, timeout=10)
    top = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True, timeout=10)
    if baseline.returncode or top.returncode or Path(top.stdout.strip()).resolve() != project:
        raise ValueError('project must be a Git root with an existing baseline commit')
    metadata = subprocess.run(['git', '-C', str(project), 'rev-parse', '--absolute-git-dir', '--git-common-dir'],
                              capture_output=True, text=True, timeout=10)
    if metadata.returncode:
        raise ValueError('project Git metadata is unavailable')
    git_directories = [(project / path).resolve() for path in metadata.stdout.splitlines()]
    if state_root.is_relative_to(project) and not any(state_root.is_relative_to(path) for path in git_directories):
        raise ValueError('state root must be outside tested source or inside actual Git metadata')
    scripts = converge_root / 'scripts'
    needed = [scripts / name for name in ('delivery_engine.py', 'work_item.py', 'reference_receipt.py')]
    if not all(path.is_file() for path in needed):
        raise ValueError('selected native Converge is unavailable')
    _require_capability(converge_root, 'adopt')
    binding = subprocess.run([sys.executable, '-B', str(needed[0]), 'freeze-binding',
                              '--mode', 'native', '--kind', 'feature'],
                             capture_output=True, text=True, timeout=30)
    if binding.returncode:
        raise ValueError(binding.stderr.strip() or 'native provider binding failed')
    native = json.loads(binding.stdout)
    if native['binding']['workflow_provider']['id'] != 'native-v1':
        raise ValueError('selected workflow must be native-v1')
    workflow = native['binding']['workflow_provider']
    provider_sources = sorted({str(Path(workflow['manifest']).relative_to(converge_root)),
                               *(item['relative_path'] for item in workflow['sources'])})
    paths = [path for path in scripts.glob('*.py') if not path.name.startswith('test_')]
    paths.extend(converge_root / path for path in provider_sources)
    fingerprints = {str(path.relative_to(converge_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in paths}
    result = {'prd': str(prd), 'converge_root': str(converge_root), 'project': str(project),
              'target': target, 'state_root': str(state_root), 'baseline': baseline.stdout.strip(),
              'product_version': snapshot['product_version'], 'prd_sha256': prd_sha,
              'input_snapshot': snapshot,
              'provider': 'native-v1', 'provider_fingerprint': digest([native, fingerprints]),
              'provider_sources': provider_sources, 'provider_source_fingerprint': digest(fingerprints),
              'requirements': sorted(snapshot['requirements']), 'acceptance': sorted(snapshot['acceptance']),
              'implementation_started': False}
    require_current_inputs(snapshot)
    return {**result, 'contract_fingerprint': digest(result)}


def prepare_revision(previous, current, impact):
    _require_capability(current['converge_root'], 'revise')
    validate_revision(impact)
    if not impact.get('scope_ready', True):
        raise ValueError('project scope has unresolved changes')
    if not isinstance(previous, dict) or previous.get('adopted') is not True:
        raise ValueError('revision requires the previous adopted handoff')
    if any(previous.get(key) != current.get(key) for key in ('project', 'baseline', 'target', 'state_root', 'converge_root')):
        raise ValueError('revision must preserve project, baseline, target and selected provider location')
    if impact['before'] != previous.get('input_snapshot') or impact['after'] != current.get('input_snapshot'):
        raise ValueError('impact report must bind both exact handoff input snapshots')
    if not impact['version_changed']:
        raise ValueError('explicit revision requires a new confirmed product version')
    path = Path(previous['native_result']['path']).resolve()
    if not path.is_relative_to(Path(current['state_root'])):
        raise ValueError('previous native work item is outside the selected state root')
    state = json.loads(path.read_text())
    old = {key: previous[key] for key in ('baseline', 'target', 'requirements', 'acceptance')}
    old.update(workspace=previous['project'], decisions=['PRD version: ' + previous['product_version']])
    if (not isinstance(state, dict) or any(state.get(key) != value for key, value in old.items())
            or state.get('reference_receipt', {}).get('references') != input_references(impact['before'])):
        raise ValueError('previous handoff no longer describes the actual native contract; reconcile before preparing')
    revision = {'path': str(path), 'expected_state_fingerprint': digest(state), 'impact': impact,
                'reason': f"product revision {previous['product_version']} → {current['product_version']}"}
    if _business_target(previous) != previous['target']:
        revision['business_target'] = _business_target(previous)
    result = {key: value for key, value in current.items() if key != 'contract_fingerprint'}
    result['revision'] = revision
    return {**result, 'contract_fingerprint': digest(result)}


def _validate_iteration(current, iteration):
    _require_capability(current['converge_root'], 'iterate')
    if not isinstance(iteration, dict) or set(iteration) != {'previous', 'business_target', 'completion', 'impact'}:
        raise ValueError('invalid prepared iteration')
    previous = iteration['previous']
    if not isinstance(previous, dict) or set(previous) != {
            'path', 'baseline', 'target', 'product_version', 'requirements', 'acceptance'}:
        raise ValueError('invalid predecessor contract')
    impact = validate_revision(iteration['impact'])
    if not impact.get('scope_ready', True):
        raise ValueError('project scope has unresolved changes')
    if (impact['after'] != current['input_snapshot'] or not impact['version_changed']
            or impact['before']['product_version'] != previous['product_version']
            or current['product_version'] == previous['product_version'] or current['target'] == previous['target']):
        raise ValueError('iteration requires a new product version and a new execution target')
    path = Path(previous['path'])
    if (not path.is_absolute() or path.resolve() != path or not path.is_relative_to(Path(current['state_root']))
            or path.exists() or path.is_symlink()):
        raise ValueError('predecessor must be completed in the selected state root')
    if not isinstance(iteration['business_target'], str) or not re.fullmatch(
            r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', iteration['business_target']):
        raise ValueError('invalid business target')
    archived = _read_completion(current['converge_root'], path)
    completed = archived['completion']
    state = completed['work_item']
    expected = {key: previous[key] for key in ('baseline', 'target', 'requirements', 'acceptance')}
    expected.update(workspace=current['project'], decisions=['PRD version: ' + previous['product_version']])
    if (any(state.get(key) != value for key, value in expected.items())
            or state['reference_receipt']['references'] != input_references(impact['before'])
            or completed['work_item_path'] != str(path)
            or iteration['completion'] != {'path': archived['path'], 'fingerprint': completed['completion_fingerprint']}):
        raise ValueError('predecessor completion does not match the previous product contract')


def prepare_iteration(previous, current, impact):
    if not isinstance(previous, dict) or previous.get('adopted') is not True:
        raise ValueError('iteration requires the previous adopted handoff')
    if any(previous.get(key) != current.get(key) for key in ('project', 'state_root', 'converge_root')):
        raise ValueError('iteration must preserve project and selected provider/state locations')
    if impact['before'] != previous.get('input_snapshot'):
        raise ValueError('iteration impact must bind the previous handoff inputs')
    _require_capability(current['converge_root'], 'iterate')
    prior_path = previous['native_result']['path']
    archived = _read_completion(current['converge_root'], prior_path)
    iteration = {'previous': {**{key: previous[key] for key in (
        'baseline', 'target', 'product_version', 'requirements', 'acceptance')}, 'path': prior_path},
        'business_target': _business_target(previous),
        'completion': {'path': archived['path'], 'fingerprint': archived['completion']['completion_fingerprint']},
        'impact': impact}
    _validate_iteration(current, iteration)
    result = {key: value for key, value in current.items() if key != 'contract_fingerprint'}
    result['iteration'] = iteration
    return {**result, 'contract_fingerprint': digest(result)}


def recheck(request):
    if not isinstance(request, dict):
        raise ValueError('prepared request must be a JSON object')
    if not isinstance(request.get('input_snapshot'), dict):
        raise ValueError('legacy or invalid prepared request lacks a complete input snapshot; prepare again without replacing the existing work item')
    current = prepare(*(request[key] for key in ('prd', 'converge_root', 'project', 'target', 'state_root')),
                      tracking=request['input_snapshot']['tracking'], attachments=request['input_snapshot']['attachments'])
    if 'revision' in request:
        _require_capability(current['converge_root'], 'revise')
        revision = request['revision']
        fields = {'path', 'expected_state_fingerprint', 'impact', 'reason'}
        if not isinstance(revision, dict) or set(revision) not in (fields, fields | {'business_target'}):
            raise ValueError('invalid prepared revision')
        if 'business_target' in revision and (not isinstance(revision['business_target'], str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', revision['business_target'])):
            raise ValueError('invalid revision business target')
        report = validate_revision(revision['impact'])
        if (report['after'] != current['input_snapshot'] or not report['version_changed']
                or not isinstance(revision['reason'], str) or not revision['reason'].strip()
                or not isinstance(revision['expected_state_fingerprint'], str)
                or not re.fullmatch('[a-f0-9]{64}', revision['expected_state_fingerprint'])
                or str(Path(revision['path']).resolve()) != revision['path']
                or not Path(revision['path']).is_relative_to(Path(current['state_root']))):
            raise ValueError('revision does not bind the selected input, state location or prior contract')
        current.pop('contract_fingerprint')
        current['revision'] = revision
        current['contract_fingerprint'] = digest(current)
    if 'iteration' in request:
        if 'revision' in request:
            raise ValueError('active revision and completed iteration are mutually exclusive')
        _validate_iteration(current, request['iteration'])
        current.pop('contract_fingerprint')
        current['iteration'] = request['iteration']
        current['contract_fingerprint'] = digest(current)
    if current != request:
        raise ValueError('prepared PRD, project or provider changed; prepare again')
    return current


def adopt(request):
    current = recheck(request)
    change = current.get('revision') or current.get('iteration')
    impact_result = apply_impact(change['impact']) if change else None
    result = subprocess.run([sys.executable, '-I', '-B', '-c', BIND,
                             str(Path(current['converge_root']) / 'scripts')],
                            input=json.dumps(current), capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'native adoption exit {result.returncode}')
    native = json.loads(result.stdout)
    if not isinstance(native, dict) or not isinstance(native.get('path'), str):
        raise ValueError('native result must identify a work item')
    path = Path(native['path']).resolve()
    statuses = {'revised', 'resumed'} if 'revision' in current else {'created', 'resumed'}
    if native.get('status') not in statuses or not path.is_relative_to(Path(current['state_root'])):
        raise ValueError('native result does not identify a work item')
    state = json.loads(path.read_text())
    expected = {key: current[key] for key in ('baseline', 'target', 'requirements', 'acceptance')}
    expected['workspace'] = current['project']
    expected['decisions'] = ['PRD version: ' + current['product_version']]
    if 'revision' in current and str(path) != current['revision']['path']:
        raise ValueError('revision must retain the existing work item path')
    references = input_references(current['input_snapshot'])
    reference = state.get('reference_receipt') if isinstance(state, dict) else None
    if (not isinstance(state, dict) or state != native.get('work_item') or any(state.get(key) != value for key, value in expected.items())
            or not isinstance(reference, dict) or reference.get('references') != references):
        raise ValueError('native work item does not preserve the frozen PRD input')
    require_current_inputs(current['input_snapshot'])
    result = {**current, 'adopted': True, 'native_result': native}
    return {**result, 'impact_result': impact_result} if impact_result is not None else result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prd', 'converge-root', 'project', 'target', 'state-root'):
        parser.add_argument('--' + name)
    parser.add_argument('--adopt', action='store_true')
    parser.add_argument('--tracking', help='explicit sibling tracking document')
    parser.add_argument('--attachments', help='JSON mapping resource references to local snapshot files')
    parser.add_argument('--previous-handoff', help='previous adopted handoff for an explicit revision')
    parser.add_argument('--impact-report', help='frozen product_revision report for both input versions')
    parser.add_argument('--previous-iteration', help='previous completed adopted handoff; requires an impact report')
    parser.add_argument('--check-provider', action='store_true', help='read-only native API compatibility check')
    parser.add_argument('--capability', choices=('adopt', 'revise', 'iterate'), default='adopt')
    parser.add_argument('--prepared', help='saved prepared request; replay the same request after interruption')
    parser.add_argument('--expected-contract', help='contract_fingerprint from the inspected request')
    args = parser.parse_args()
    try:
        if args.check_provider:
            if not args.converge_root or args.adopt or args.prepared or args.prd:
                raise ValueError('provider check requires a Converge root and cannot adopt or mix product inputs')
            report = provider_capabilities(args.converge_root, args.capability)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report['ready'] else 1
        if args.prepared:
            if any(getattr(args, key) is not None for key in ('prd', 'converge_root', 'project', 'target', 'state_root', 'tracking', 'attachments', 'previous_handoff', 'impact_report', 'previous_iteration')):
                raise ValueError('saved request cannot be combined with new handoff inputs')
            request = json.loads(Path(args.prepared).read_text())
            if request.get('adopted') is True:
                raise ValueError('use the saved prepared request, not an already adopted result')
            request.pop('adopted', None)
            recheck(request)
        else:
            if not all(getattr(args, key) for key in ('prd', 'converge_root', 'project', 'target', 'state_root')):
                raise ValueError('PRD, Converge root, project, target and state root are required')
            request = prepare_cli(args)
        if args.adopt and args.expected_contract != request['contract_fingerprint']:
            raise ValueError('adoption requires the unchanged contract_fingerprint from preparation')
        print(json.dumps(adopt(request) if args.adopt else {**request, 'adopted': False}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, AttributeError, subprocess.SubprocessError) as error:
        print(json.dumps({'adopted': False, 'implementation_started': False, 'error': str(error)}, ensure_ascii=False))
        return 1


def prepare_cli(args):
    attachments = None
    if args.attachments:
        source = Path(args.attachments).resolve()
        attachments = json.loads(source.read_text())
        if not isinstance(attachments, dict) or any(not isinstance(v, str) or not v for v in attachments.values()):
            raise ValueError('attachments must map references to nonempty file paths')
        attachments = {key: str((source.parent / value).resolve()) for key, value in attachments.items()}
    request = prepare(args.prd, args.converge_root, args.project, args.target, args.state_root,
                      tracking=args.tracking, attachments=attachments)
    if args.previous_handoff and args.previous_iteration:
        raise ValueError('choose active revision or completed iteration')
    if bool(args.previous_handoff or args.previous_iteration) != bool(args.impact_report):
        raise ValueError('explicit revision or iteration requires both previous handoff and impact report')
    if args.previous_handoff:
        request = prepare_revision(json.loads(Path(args.previous_handoff).read_text()), request,
                                   json.loads(Path(args.impact_report).read_text()))
    if args.previous_iteration:
        request = prepare_iteration(json.loads(Path(args.previous_iteration).read_text()), request,
                                    json.loads(Path(args.impact_report).read_text()))
    return request


if __name__ == '__main__':
    raise SystemExit(main())
