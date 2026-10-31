"""Bind stage-content judgments and FR/AC coverage to current local evidence.

Checks evidence consistency, not the truth of a business decision. 作者：Jeff.Liu
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile

STAGE_CHECKS = {
    'L0': ('problem_source', 'scope_impact'),
    'L1': ('current_state', 'causes_evidence'),
    'L2': ('options_decision', 'value_scope'),
    'L3': ('rules_exceptions', 'acceptance'),
    'L4': ('design_dependencies', 'failure_recovery'),
    'L5': ('test_first', 'change_build'),
    'L6': ('ac_coverage', 'execution_results'),
    'L7': ('business_scenarios', 'confirmation_scope'),
    'L8': ('build_environment', 'authorization_recovery'),
    'L9': ('deployed_checks', 'failure_result'),
    'L10': ('handover_owner', 'outcome_observation'),
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def runner_identity():
    runner = Path(__file__).with_name('lifecycle_test_runner.py')
    return hashlib.sha256(runner.read_bytes() + Path(__file__).read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, location):
    _require(isinstance(value, str) and bool(value.strip()), f'{location}: nonempty string required')
    return value


def _list(value, location, nonempty=False):
    _require(isinstance(value, list) and (bool(value) or not nonempty), f'{location}: array required')
    return value


def local_file(root, relative):
    _text(relative, 'path')
    _require(not Path(relative).is_absolute(), 'path must be relative')
    root = Path(root).resolve()
    path = (root / relative).resolve()
    _require(path.is_relative_to(root) and path.is_file(), f'missing or external file: {relative}')
    return path


def reference(root, relative, quote=None):
    value = {'path': relative, 'sha256': hashlib.sha256(local_file(root, relative).read_bytes()).hexdigest()}
    if quote is not None:
        value['quote'] = quote
    return value


def _reference(root, value, quoted=False):
    _require(isinstance(value, dict), 'artifact reference must be an object')
    path = local_file(root, value.get('path'))
    _require(value.get('sha256') == hashlib.sha256(path.read_bytes()).hexdigest(), f'stale source: {value.get("path")}')
    if quoted:
        quote = _text(value.get('quote'), 'evidence.quote')
        _require(quote in path.read_text(encoding='utf-8'), f'quote not in source: {value["path"]}')
    return value


def _identity(value):
    _require(isinstance(value, dict) and type(value.get('schema_version')) is int and value['schema_version'] == 1,
             'supported contract schema_version is 1')
    for key in ('project_ref', 'subject_ref'):
        _text(value.get(key), key)


def _timestamp(value):
    parsed = datetime.fromisoformat(_text(value, 'at'))
    _require(parsed.utcoffset() is not None, 'at: timezone required')


def check_quality(value, root, stages=None):
    result = {'valid': False, 'ready': False, 'errors': [], 'gaps': [],
              'verification': 'bound_content_review', 'business_authorization': False}
    try:
        _identity(value)
        entries = _list(value.get('stages'), 'stages', True)
        by_stage, targets = {}, set()
        for entry in entries:
            _require(isinstance(entry, dict), 'stage review must be an object')
            stage = _text(entry.get('stage'), 'stage')
            _require(stage in STAGE_CHECKS, f'unknown stage: {stage}')
            artifact = entry.get('artifact')
            _require(isinstance(artifact, dict), 'artifact reference must be an object')
            target = (stage, _text(artifact.get('path'), 'artifact.path'))
            _require(target not in targets, f'duplicate stage/artifact review: {target}')
            targets.add(target)
            by_stage.setdefault(stage, []).append(entry)
        selected = list(by_stage) if stages is None else _list(stages, 'selected stages', True)
        _require(len(selected) == len(set(selected)), 'duplicate selected stages')
        for stage in selected:
            _require(stage in by_stage, f'missing stage review: {stage}')
        for entry in [entry for stage in selected for entry in by_stage[stage]]:
            stage = entry['stage']
            _reference(root, entry.get('artifact'))
            _text(entry.get('reviewer'), 'reviewer')
            _require(entry.get('reviewer_kind') in ('model', 'human'), 'reviewer_kind must be model or human')
            _timestamp(entry.get('at'))
            checks = _list(entry.get('checks'), 'checks', True)
            identities = [_text(check.get('id'), 'check.id') for check in checks]
            _require(len(identities) == len(set(identities)) and set(identities) == set(STAGE_CHECKS[stage]),
                     f'{stage}: all defined questions must be answered once')
            for check in checks:
                _text(check.get('reason'), 'check.reason')
                verdict = check.get('verdict')
                _require(verdict in ('pass', 'gap', 'not_applicable'), 'unknown review verdict')
                citations = _list(check.get('evidence'), 'check.evidence', verdict != 'gap')
                for citation in citations:
                    _reference(root, citation, quoted=True)
                if verdict == 'gap':
                    result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'],
                                           'check': check['id'], 'reason': check['reason']})
            for decision in _list(entry.get('open_decisions', []), 'open_decisions'):
                for key in ('question', 'owner', 'next_action'):
                    _text(decision.get(key), f'decision.{key}')
                result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'], 'decision': decision})
        result.update(valid=True, ready=not result['gaps'])
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        result['errors'].append(str(error))
    return result


def _indexed(items, name, root):
    result = {}
    for item in _list(items, name, True):
        _require(isinstance(item, dict), f'{name}: object required')
        identity = _text(item.get('id'), f'{name}.id')
        _require(identity not in result, f'duplicate {name}: {identity}')
        _require(type(item.get('version')) is int and item['version'] > 0, f'{identity}: positive version required')
        _reference(root, item.get('source'))
        result[identity] = item
    return result


def _links(items, targets, location):
    linked = []
    for link in _list(items, location, True):
        _require(isinstance(link, dict), f'{location}: version reference required')
        identity = _text(link.get('id'), location)
        _require(identity in targets and type(link.get('version')) is int and link['version'] == targets[identity]['version'],
                 f'{location}: missing/stale version {identity}')
        _require(identity not in linked, f'{location}: duplicate reference {identity}')
        linked.append(identity)
    return linked


def check_trace(value, execution, root):
    result = {'valid': False, 'ready': False, 'errors': [], 'gaps': [], 'coverage': {},
              'verification': 'bound_test_execution', 'business_authorization': False}
    try:
        _identity(value)
        build = _reference(root, value.get('build'))
        for key in ('environment', 'scope'):
            _text(value.get(key), key)
        requirements = _indexed(value.get('requirements'), 'requirements', root)
        acceptance = _indexed(value.get('acceptance'), 'acceptance', root)
        tests = _indexed(value.get('tests'), 'tests', root)
        requirements_covered, mandatory_requirements = set(), set()
        coverage = {identity: [] for identity in acceptance}
        for identity, criterion in acceptance.items():
            _require(type(criterion.get('required')) is bool, f'{identity}: required must be boolean')
            linked = _links(criterion.get('requirements'), requirements, f'{identity}.requirements')
            requirements_covered.update(linked)
            if criterion['required']:
                mandatory_requirements.update(linked)
        _require(requirements_covered == set(requirements), 'each requirement must have acceptance criteria')
        _require(mandatory_requirements == set(requirements), 'each in-scope requirement must have mandatory acceptance criteria')
        for identity, test in tests.items():
            for ac in _links(test.get('covers'), acceptance, f'{identity}.covers'):
                coverage[ac].append(identity)
        for ac, criteria in acceptance.items():
            if criteria['required']:
                _require(bool(coverage[ac]), f'mandatory acceptance has no test: {ac}')
        _require(any(ac['required'] for ac in acceptance.values()), 'at least one mandatory acceptance is required')
        result['coverage'] = coverage
        result['valid'] = True
        if execution is None:
            result['gaps'].append('actual execution receipt missing')
            return result
        _require(isinstance(execution, dict) and type(execution.get('schema_version')) is int and execution['schema_version'] == 1, 'invalid execution receipt')
        _require(execution.get('trace_sha256') == fingerprint(value), 'trace changed after execution')
        _require(execution.get('runner_sha256') == runner_identity(), 'test runner identity changed')
        _require(execution.get('build') == build['sha256'], 'wrong tested build')
        for key in ('environment', 'scope'):
            _require(execution.get(key) == value[key], f'execution {key} mismatch')
        _timestamp(execution.get('at'))
        _require(execution.get('source_unchanged') is True, 'sources changed while testing')
        _require(not execution.get('duplicate_cases'), 'duplicate test execution IDs')
        observed = {}
        for case in _list(execution.get('cases'), 'executed cases'):
            identity = _text(case.get('id'), 'executed case.id')
            if 'binding_error' in case:
                reason = _text(case['binding_error'], 'test binding_error')
                if identity in tests and case.get('status') == 'passed':
                    result['gaps'].append({'test': identity, 'reason': reason})
            _require(identity not in observed, f'duplicate executed case: {identity}')
            _require(case.get('status') in ('passed', 'failed', 'error', 'skipped', 'blocked', 'not_run', 'expected_failure', 'unexpected_success'),
                     'unknown test execution status')
            observed[identity] = case
        for ac, criterion in acceptance.items():
            for test_id in coverage[ac]:
                case = observed.get(test_id)
                if case is not None:
                    _reference(root, case.get('source'))
                    _require(case['source'] == tests[test_id]['source'], f'test source/version changed: {test_id}')
                if criterion['required'] and (case is None or case['status'] != 'passed'):
                    result['gaps'].append({'acceptance': ac, 'test': test_id, 'status': case['status'] if case else 'not_run'})
        if execution.get('exit_code') != 0 or type(execution.get('exit_code')) is not int:
            result['gaps'].append('test command did not pass')
        result['ready'] = not result['gaps']
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        result.update(valid=False, ready=False)
        result['errors'].append(str(error))
    return result



def check_handoff(packet, root, purpose='tested'):
    """Verify a transfer package, optionally requiring a passed automated checkpoint."""
    result = {'valid': False, 'ready': False, 'errors': [], 'verification': 'bound_handoff_context',
              'business_authorization': False, 'purpose': purpose, 'gaps': []}
    try:
        _require(purpose in ('tested', 'transfer'), 'unknown handoff purpose')
        _identity(packet)
        files = {}
        for item in _list(packet.get('files'), 'handoff.files', True):
            _reference(root, item)
            _require(item['path'] not in files, 'duplicate handoff file')
            files[item['path']] = item['sha256']
        loaded = {}
        has_tests = 'trace' in packet or 'execution' in packet
        _require(not has_tests or ('trace' in packet and 'execution' in packet), 'trace and execution must be supplied together')
        _require(purpose != 'tested' or has_tests, 'tested handoff requires automated trace and execution')
        for key in ('record', 'prd', 'quality') + (('trace', 'execution') if has_tests else ()):
            ref = _reference(root, packet.get(key))
            _require(files.get(ref['path']) == ref['sha256'], f'handoff inventory missing {key}')
            if key != 'prd':
                loaded[key] = json.loads(local_file(root, ref['path']).read_text())
        from lifecycle_record import check_record
        state = loaded['record']
        record_check = check_record(state)
        _require(record_check['valid'], 'invalid lifecycle record')
        result['needs_review'] = record_check['needs_review']
        if purpose == 'tested':
            _require(not record_check['needs_review'], 'handoff contains stale lifecycle dependencies')
        _require(type(packet.get('record_revision')) is int and packet['record_revision'] == state['revision'],
                 'handoff record revision conflict')
        for value in [state, loaded['quality']] + ([loaded['trace']] if has_tests else []):
            _require(all(value.get(key) == packet[key] for key in ('project_ref', 'subject_ref')), 'handoff identity conflict')
        for assertion in state['assertions']:
            if assertion['confirmation'] == 'conflicted':
                result['gaps'].append({'assertion': assertion['text'], 'confirmation': 'conflicted',
                                       'classification': assertion['classification'], 'source': assertion['source'],
                                       'owner': assertion['owner']})
        _require(any(node['stage'] == 'L3' and node['source'] == packet['prd']['path'] for node in state['artifacts']),
                 'handoff PRD is not the recorded primary requirement')
        for node in state['artifacts']:
            if node['status'] in ('blocked', 'pending_confirmation'):
                result['gaps'].append({'id': node['id'], 'stage': node['stage'], 'version': node['version'],
                                       'artifact': node['source'], 'status': node['status'], 'owner': node['owner'],
                                       'reason': node['reason'], 'recovery': node['recovery']})
            refs = [node['source']] if node['status'] == 'completed' else []
            refs.extend(item['source'] for item in node['evidence'])
            _require(all(path in files for path in refs), 'handoff omits a recorded artifact/evidence')

        def included(value):
            if isinstance(value, dict):
                if 'path' in value and 'sha256' in value:
                    _require(files.get(value['path']) == value['sha256'], f'handoff omits bound source: {value["path"]}')
                for child in value.values():
                    included(child)
            elif isinstance(value, list):
                for child in value:
                    included(child)

        included([loaded['quality'], loaded.get('trace'), loaded.get('execution')])
        quality_check = check_quality(loaded['quality'], root)
        _require(quality_check['valid'], f"invalid handoff content review: {quality_check['errors']}")
        reviewed = {(entry['stage'], entry['artifact']['path']) for entry in loaded['quality']['stages']}
        _require({(node['stage'], node['source']) for node in state['artifacts'] if node['status'] == 'completed'}
                 <= reviewed, 'handoff omits completed stage reviews for specific artifacts')
        result.update(quality_ready=quality_check['ready'], tests_ready=None)
        result['gaps'].extend(quality_check['gaps'])
        if purpose == 'tested':
            _require(quality_check['ready'], 'handoff content reviews are not ready')
        if has_tests:
            trace_check = check_trace(loaded['trace'], loaded['execution'], root)
            _require(trace_check['valid'], f"invalid handoff test evidence: {trace_check['errors']}")
            result['tests_ready'] = trace_check['ready']
            result['gaps'].extend(trace_check['gaps'])
            if purpose == 'tested':
                _require(trace_check['ready'], 'handoff test evidence is not ready')
            tested = []
            for node in state['artifacts']:
                if node['stage'] != 'L6':
                    continue
                receipts = [e for e in node['evidence'] if e['kind'] == 'executed'
                            and e['source'] == packet['execution']['path']
                            and e['subject'] == {'id': node['id'], 'version': node['version']}]
                if receipts:
                    tested.append((node, receipts))
            _require(bool(tested), 'handoff execution is not linked to an L6 artifact')
            context = dict(build=loaded['trace']['build']['sha256'],
                           environment=loaded['trace']['environment'], scope=loaded['trace']['scope'])
            for node, receipts in tested:
                if purpose == 'tested':
                    _require(node['status'] == 'completed', 'handoff L6 is not completed')
                _require(all(node.get(key) == value for key, value in context.items()),
                         'handoff L6 build/environment/scope differs from trace')
                _require(all(e.get(key) == value for e in receipts for key, value in context.items()),
                         'handoff L6 evidence build/environment/scope differs from trace')
        action = packet.get('next_action')
        _require(isinstance(action, dict) and action.get('stage') in STAGE_CHECKS, 'invalid next stage')
        for key in ('action', 'owner', 'expected_result', 'authorized_scope'):
            _text(action.get(key), f'next_action.{key}')
        result.update(valid=True, ready=True, project_ref=packet['project_ref'], subject_ref=packet['subject_ref'],
                      record_revision=state['revision'], next_action=action)
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        result['errors'].append(str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('quality', 'trace', 'handoff'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--execution', type=Path)
    parser.add_argument('--stage', action='append')
    parser.add_argument('--purpose', choices=('tested', 'transfer'), default='tested')
    args = parser.parse_args()
    try:
        value = json.loads(local_file(args.root, str(args.contract)).read_text())
        if args.mode == 'handoff':
            result = check_handoff(value, args.root, args.purpose)
        elif args.mode == 'quality':
            result = check_quality(value, args.root, args.stage)
        else:
            receipt = json.loads(local_file(args.root, str(args.execution)).read_text()) if args.execution else None
            result = check_trace(value, receipt, args.root)
    except (ValueError, OSError) as error:
        result = {'valid': False, 'ready': False, 'errors': [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    with tempfile.TemporaryDirectory(prefix='lifecycle-imports-') as import_cache:
        sys.pycache_prefix = import_cache
        raise SystemExit(main())
