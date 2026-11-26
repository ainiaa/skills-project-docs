"""Bind stage-content judgments and FR/AC coverage to current local evidence.

Checks evidence consistency, not the truth of a business decision. 作者：Jeff.Liu
"""
import argparse
from datetime import datetime
import hashlib
import json
import re
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


def _check_details(entry, root, trace=None, execution=None, project_checks=None):
    from lifecycle_checklist import load_catalog
    stage = entry['stage']
    catalog = load_catalog(stage)
    _require(all(item['check'] in STAGE_CHECKS[stage] for item in catalog['items']), 'unknown parent checklist question')
    coverage = entry.get('coverage')
    _require(isinstance(coverage, dict), 'detailed coverage must be an object')
    _require(coverage.get('catalog_sha256') == catalog['fingerprint'], 'checklist catalog changed')
    definitions = {item['id']: item for item in catalog['items']}
    expected = {key: item for key, item in (project_checks or {}).items() if item['stage'] == stage}
    definitions.update(expected)
    records = _list(coverage.get('items'), 'coverage.items')
    seen, gaps = set(), []

    def gap(identity, reason, **extra):
        gaps.append({'stage': stage, 'artifact': entry['artifact']['path'], 'item': identity, 'reason': reason, **extra})

    for record in records:
        _require(isinstance(record, dict), 'coverage item must be an object')
        identity = _text(record.get('id'), 'coverage.id')
        _require(identity not in seen, 'duplicate detailed checklist ID')
        seen.add(identity)
        if identity.startswith('PROJECT-'):
            _require(re.fullmatch(r'PROJECT-[A-Za-z0-9][A-Za-z0-9._-]{0,119}', identity), 'invalid project checklist ID')
            if project_checks is not None:
                _require(identity in expected, 'project check is absent from the frozen stage scope')
                frozen = expected[identity]
                for key in ('check', 'required', 'method'):
                    _require(key not in record or type(record[key]) is type(frozen[key]) and record[key] == frozen[key],
                             f'project check {key} differs from frozen scope')
                if 'source' in record:
                    _reference(root, record['source'], quoted=True)
                    _require({**record['source'], 'path': str(local_file(root, record['source']['path']))} == frozen['source'],
                             'project check source differs from frozen scope')
                definition = {'required': frozen['required'], 'verification': frozen['method']}
            else:
                _require(record.get('check') in STAGE_CHECKS[stage], 'project item needs a current stage question')
                _require(type(record.get('required')) is bool, 'project required must be boolean')
                _require(record.get('method') in ('review', 'test'), 'project verification method required')
                _reference(root, record.get('source'), quoted=True)
                definition = {'required': record['required'], 'verification': record['method']}
        else:
            _require(identity in definitions, f'unknown or cross-stage checklist item: {identity}')
            definition = definitions[identity]
        _text(record.get('reason'), 'applicability.reason')
        choice = record.get('applicability')
        _require(choice in ('applicable', 'not_applicable', 'undecided'), 'invalid applicability')
        _require(choice == 'applicable' or 'verification' not in record,
                 'inactive applicability cannot contain a verification mapping')
        evidence = _list(record.get('evidence'), 'applicability.evidence')
        for ref in evidence:
            _reference(root, ref, quoted=True)
        if choice == 'undecided':
            gap(identity, record['reason'], owner=_text(record.get('owner'), 'owner'),
                next_action=_text(record.get('next_action'), 'next_action'))
            continue
        if not evidence:
            gap(identity, 'applicability lacks current scope evidence')
        if choice == 'not_applicable':
            if definition['required']:
                gap(identity, 'mandatory checklist item cannot be waived')
            if identity == 'L6-AUTOMATED' and trace is not None and trace.get('tests'):
                gap(identity, 'declared automated scope cannot be marked not applicable')
            continue
        verification = record.get('verification')
        _require(isinstance(verification, dict), 'verification mapping required')
        _require(verification.get('kind') == definition['verification'], 'wrong checklist verification method')
        _require(verification.get('result') in ('passed', 'failed', 'not_run'), 'invalid verification result')
        refs = _list(verification.get('evidence'), 'verification.evidence')
        for ref in refs:
            _reference(root, ref, quoted=True)
        if verification['kind'] == 'test':
            tests = _list(verification.get('tests'), 'verification.tests', True)
            _require(all(isinstance(identity, str) and identity.strip() for identity in tests)
                     and len(tests) == len(set(tests)), 'test mappings must be unique nonempty IDs')
            if trace is not None:
                result = check_trace(trace, execution, root)
                _require(result['valid'], f"invalid detailed test evidence: {result['errors']}")
                declared = {item['id'] for item in trace['tests']}
                _require(set(tests) <= declared, 'checklist refers to undeclared tests')
        if verification['result'] != 'passed':
            gap(identity, 'verification is not passed', owner=_text(record.get('owner'), 'owner'),
                next_action=_text(record.get('next_action'), 'next_action'))
            continue
        if verification['kind'] == 'review':
            artifact = local_file(root, entry['artifact']['path'])
            if not refs or (artifact.suffix.lower() in ('.md', '.markdown')
                            and not any(local_file(root, ref['path']) == artifact for ref in refs)):
                gap(identity, 'review verification lacks a quotation from this artifact')
        else:
            if trace is None or execution is None:
                gap(identity, 'actual trace/execution required for test verification',
                    owner=_text(record.get('owner'), 'owner'),
                    next_action=_text(record.get('next_action'), 'next_action'))
                continue
            observed = {item['id']: item for item in execution['cases']}
            if not result['ready'] or any(t not in observed or observed[t]['status'] != 'passed' for t in tests):
                gap(identity, 'mapped tests did not actually pass in the current trace',
                    owner=_text(record.get('owner'), 'owner'),
                    next_action=_text(record.get('next_action'), 'next_action'))
            if identity in expected:
                mapped = set(tests)
                covered = {link['id'] for criterion in trace['acceptance']
                           if mapped.intersection(result['coverage'][criterion['id']])
                           for link in criterion['requirements']}
                missing = sorted(set(expected[identity]['requirements']) - covered)
                if missing:
                    gap(identity, 'mapped tests do not cover frozen project requirements', requirements=missing)
    for identity in sorted(set(definitions) - seen):
        gap(identity, 'applicability decision missing')
    return gaps


def check_quality(value, root, stages=None, *, require_details=False, trace=None, execution=None,
                  project_inputs=None, expected_inputs=None, targets=None, independent_from=None, walkthrough=None,
                  _manual_handoff=False):
    result = {'valid': False, 'ready': False, 'errors': [], 'gaps': [],
              'verification': 'bound_content_review', 'business_authorization': False, 'details_ready': None}
    try:
        _identity(value)
        required_walkthrough = set(_list(walkthrough if walkthrough is not None else [], 'walkthrough policy'))
        _require(required_walkthrough <= {'source_coverage', 'counterexample', 'journey'}, 'unknown walkthrough policy')
        if independent_from is not None:
            _text(independent_from, 'producer identity')
            required_walkthrough.update(('source_coverage', 'counterexample'))
        project_checks = None
        _require((project_inputs is None) == (expected_inputs is None), 'project inputs and expected fingerprint must be paired')
        if project_inputs is not None:
            from product_inputs import require_current_inputs
            require_current_inputs(project_inputs, manual_handoff=_manual_handoff)
            _require(project_inputs['fingerprint'] == expected_inputs, 'caller project scope fingerprint differs')
            project_checks = project_inputs.get('project_checks', {})
        _require(type(require_details) is bool, 'require_details must be boolean')
        _require((trace is None) == (execution is None), 'trace and execution must be paired')
        if trace is not None:
            _require(isinstance(trace, dict) and all(trace.get(k) == value[k] for k in ('project_ref', 'subject_ref')),
                     'detailed test identity mismatch')
        detail_gaps, detail_entries = [], 0
        entries = _list(value.get('stages'), 'stages', True)
        by_stage, review_targets = {}, set()
        for entry in entries:
            _require(isinstance(entry, dict), 'stage review must be an object')
            stage = _text(entry.get('stage'), 'stage')
            _require(stage in STAGE_CHECKS, f'unknown stage: {stage}')
            artifact = entry.get('artifact')
            _require(isinstance(artifact, dict), 'artifact reference must be an object')
            target = (stage, _text(artifact.get('path'), 'artifact.path'))
            _require(target not in review_targets, f'duplicate stage/artifact review: {target}')
            review_targets.add(target)
            by_stage.setdefault(stage, []).append(entry)
        selected = list(by_stage) if stages is None else _list(stages, 'selected stages', True)
        _require(len(selected) == len(set(selected)), 'duplicate selected stages')
        for stage in selected:
            _require(stage in by_stage, f'missing stage review: {stage}')
        if targets is not None:
            _require(isinstance(targets, list) and bool(targets) and all(isinstance(t, tuple) and len(t) == 2 for t in targets),
                     'checkpoint needs caller stage/artifact targets')
            actual = {(stage, entry['artifact']['path']) for stage in selected for entry in by_stage[stage]}
            _require(len(targets) == len(set(targets)) and set(targets) == actual, 'caller stage/artifact targets differ')
            _require(project_inputs is not None or not any(
                str(item.get('id', '')).startswith('PROJECT-') for stage in selected for entry in by_stage[stage]
                for item in entry.get('coverage', {}).get('items', [])), 'checkpoint project checks require frozen inputs')
        for entry in [entry for stage in selected for entry in by_stage[stage]]:
            stage = entry['stage']
            _reference(root, entry.get('artifact'))
            artifact_path = local_file(root, entry['artifact']['path'])
            if targets is not None and project_inputs is not None and stage == 'L3':
                _require(str(artifact_path) in (project_inputs['prd'], project_inputs['tracking']),
                         'L3 artifact is not a frozen product input (PRD or tracking document)')
            _text(entry.get('reviewer'), 'reviewer')
            _require(entry.get('reviewer_kind') in ('model', 'human'), 'reviewer_kind must be model or human')
            _timestamp(entry.get('at'))
            if independent_from == entry['reviewer']:
                result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'],
                                       'reason': 'independent review cannot use the producer identity'})
            reports = _list(entry.get('walkthrough', []), 'walkthrough')
            report_ids = set()
            for report in reports:
                _require(isinstance(report, dict), 'walkthrough check must be an object')
                identity = report.get('id')
                _require(isinstance(identity, str) and identity in {'source_coverage', 'counterexample', 'journey'}
                         and identity not in report_ids, 'invalid or duplicate walkthrough check')
                report_ids.add(identity)
                _text(report.get('reason'), 'walkthrough.reason')
                _require(report.get('verdict') in ('pass', 'gap', 'not_applicable'), 'invalid walkthrough verdict')
                refs = _list(report.get('evidence'), 'walkthrough.evidence')
                for ref in refs:
                    _reference(root, ref, quoted=True)
                if report['verdict'] == 'gap' or report['verdict'] == 'pass' and not refs or (
                        identity in required_walkthrough and report['verdict'] != 'pass'):
                    result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'],
                                           'check': identity, 'reason': report['reason']})
            for identity in sorted(required_walkthrough - report_ids):
                result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'],
                                       'check': identity, 'reason': 'required content walkthrough missing'})
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
                if (verdict != 'gap' and artifact_path.suffix.lower() in ('.md', '.markdown')
                        and not any(local_file(root, citation['path']) == artifact_path
                                    for citation in citations)):
                    result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'],
                                           'check': check['id'],
                                           'reason': 'review lacks a quotation from the current artifact'})
                if verdict == 'gap':
                    result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'],
                                           'check': check['id'], 'reason': check['reason']})
            if 'coverage' in entry:
                detail_entries += 1
                detail_gaps.extend(_check_details(entry, root, trace, execution, project_checks))
            elif require_details:
                detail_gaps.append({'stage': stage, 'artifact': entry['artifact']['path'],
                                    'reason': 'detailed checklist coverage missing'})
            for decision in _list(entry.get('open_decisions', []), 'open_decisions'):
                for key in ('question', 'owner', 'next_action'):
                    _text(decision.get(key), f'decision.{key}')
                result['gaps'].append({'stage': stage, 'artifact': entry['artifact']['path'], 'decision': decision})
        if require_details or detail_entries:
            result['details_ready'] = not detail_gaps and detail_entries == sum(len(by_stage[stage]) for stage in selected)
        result['gaps'].extend(detail_gaps)
        result.update(valid=True, ready=not result['gaps'])
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ImportError) as error:
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
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ImportError) as error:
        result.update(valid=False, ready=False)
        result['errors'].append(str(error))
    return result


def _handoff_document(text):
    # Plain legacy handoffs can still be checked without the Markdown parser.
    if not any(marker in text for marker in ('>', '#', '[', '<')):
        return text, []
    from validate_product_doc import prose
    return prose(text)


def _structured_prd(clean):
    return re.search(r'(?m)^(?:>[ \t]*产品版本[：:]|#{1,6}[ \t]+(?:FR|AC)-)', clean) is not None


def _handoff_trace_scope(trace, root, primary, text, snapshot):
    from validate_product_doc import DECLARATION, prose

    declarations = {}
    if snapshot:
        for path in (snapshot['prd'], snapshot['tracking']):
            if path is not None:
                for line in prose(snapshot['documents'][path])[0].splitlines():
                    if match := DECLARATION.fullmatch(line):
                        declarations[match[2]] = Path(path)
    for group in ('requirements', 'acceptance'):
        for item in trace[group]:
            identity = item['id']
            source = local_file(root, item['source']['path'])
            if snapshot is None:
                if source != primary:
                    return f'trace must reference the handoff PRD: {identity}'
                if not re.search(r'(?<![\w-])' + re.escape(identity) + r'(?![\w-])', text):
                    return f'trace ID is not declared in the handoff PRD: {identity}'
                continue
            if identity not in snapshot[group]:
                return f'trace ID is not declared in the frozen scope: {identity}'
            if source != declarations.get(identity):
                return f'trace source differs from the frozen declaration: {identity}'
            if group == 'acceptance' and {ref['id'] for ref in item['requirements']} != {
                    snapshot[group][identity]['requirement']}:
                return f'trace acceptance owner differs from the frozen scope: {identity}'
    return None


def _handoff_inventory(root, files):
    return {(str(local_file(root, name)), digest) for name, digest in files.items()}


def _check_local_inputs(root, primary, files, resources):
    from urllib.parse import urlsplit
    from product_inputs import _resource_path

    if not resources:
        return
    root = Path(root).resolve()
    inventory = _handoff_inventory(root, files)
    pending, seen = [(primary, resources)], {primary}
    while pending:
        source, links = pending.pop()
        for link in links:
            if urlsplit(link).scheme in ('http', 'https', 'mailto'):
                continue
            name = _resource_path(source, link, root, {})
            if name is None:
                continue
            path = local_file(root, Path(name).relative_to(root).as_posix())
            if path in seen:
                continue
            seen.add(path)
            data = path.read_bytes()
            _require((str(path), hashlib.sha256(data).hexdigest()) in inventory,
                     f'handoff inventory omits or differs from local resource: {path.relative_to(root)}')
            if path.suffix.lower() in ('.md', '.markdown'):
                pending.append((path, _handoff_document(data.decode('utf-8'))[1]))


def _handoff_inputs(snapshot, expected, root, primary, files):
    from product_inputs import freeze_inputs, validate_snapshot

    _require(snapshot.get('fingerprint') == expected, 'frozen inputs differ from expected fingerprint')
    validate_snapshot(snapshot)
    relative_prd = primary.relative_to(Path(root).resolve())
    original_prd = Path(snapshot['prd'])
    origin = original_prd
    for _ in relative_prd.parts:
        origin = origin.parent
    _require(origin / relative_prd == original_prd, 'frozen inputs differ from the handoff PRD path')

    def received(path):
        relative = Path(path).relative_to(origin)
        _require('..' not in relative.parts, 'unsafe frozen input path')
        return local_file(root, relative.as_posix())

    frozen = [(str(received(item['path'])), item['sha256']) for item in snapshot['files']]
    _require(len({name for name, _ in frozen}) == len(frozen) and set(frozen) <= _handoff_inventory(root, files),
             'handoff inventory omits or differs from frozen product inputs')
    tracking = received(snapshot['tracking']) if snapshot['tracking'] else None
    local = freeze_inputs(primary, tracking=tracking,
                          attachments={ref: received(path) for ref, path in snapshot['attachments'].items()})
    _require({(item['path'], item['sha256']) for item in local['files']} == set(frozen),
             'received resource closure differs from frozen product inputs')
    return local


def check_handoff(packet, root, purpose='tested', *, require_details=False,
                  project_inputs=None, expected_inputs=None):
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
        primary = local_file(root, packet['prd']['path'])
        primary_text = primary.read_text(encoding='utf-8')
        _require((project_inputs is None) == (expected_inputs is None),
                 'project inputs and expected fingerprint must be paired')
        manual_handoff = False
        if project_inputs is not None:
            project_inputs = _handoff_inputs(project_inputs, expected_inputs, root, primary, files)
        else:
            from validate_product_doc import field

            document, resources = _handoff_document(primary_text)
            if _structured_prd(document) and (
                    has_tests or (require_details and field(document, '状态', quoted=True) == '已确认')):
                from product_inputs import freeze_inputs
                manual_handoff = not has_tests
                project_inputs = freeze_inputs(primary, manual_handoff=manual_handoff)
                _require({(item['path'], item['sha256']) for item in project_inputs['files']} <= _handoff_inventory(root, files),
                         'handoff inventory omits or differs from frozen product inputs')
            else:
                _check_local_inputs(root, primary, files, resources)
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
        quality_check = check_quality(loaded['quality'], root, require_details=require_details,
                                      trace=loaded.get('trace'), execution=loaded.get('execution'),
                                      project_inputs=project_inputs,
                                      expected_inputs=project_inputs['fingerprint'] if project_inputs is not None else None,
                                      _manual_handoff=manual_handoff)
        _require(quality_check['valid'], f"invalid handoff content review: {quality_check['errors']}")
        reviewed = {(entry['stage'], entry['artifact']['path']) for entry in loaded['quality']['stages']}
        _require({(node['stage'], node['source']) for node in state['artifacts'] if node['status'] == 'completed'}
                 <= reviewed, 'handoff omits completed stage reviews for specific artifacts')
        result.update(quality_ready=quality_check['ready'], tests_ready=None,
                      details_ready=quality_check['details_ready'])
        result['gaps'].extend(quality_check['gaps'])
        if purpose == 'tested':
            _require(quality_check['ready'], 'handoff content reviews are not ready')
        if has_tests:
            trace_check = check_trace(loaded['trace'], loaded['execution'], root)
            _require(trace_check['valid'], f"invalid handoff test evidence: {trace_check['errors']}")
            scope_gap = _handoff_trace_scope(loaded['trace'], root, primary, primary_text, project_inputs)
            if scope_gap:
                result['gaps'].append(scope_gap)
            result['tests_ready'] = trace_check['ready'] and not scope_gap
            result['gaps'].extend(trace_check['gaps'])
            _require(scope_gap is None, scope_gap)
            if purpose == 'tested':
                _require(result['tests_ready'], 'handoff test evidence is not ready')
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
    except (ValueError, TypeError, KeyError, AttributeError, OSError, ImportError) as error:
        result['errors'].append(str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('quality', 'trace', 'handoff', 'checkpoint'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--execution', type=Path)
    parser.add_argument('--trace', type=Path, help='existing trace paired with --execution for detailed test mapping')
    parser.add_argument('--require-details', action='store_true', help='require explicit detailed checklist coverage')
    parser.add_argument('--target', action='append', help='caller-frozen stage:artifact target for checkpoint')
    parser.add_argument('--inputs', type=Path, help='existing frozen product input snapshot')
    parser.add_argument('--expected-inputs', help='input fingerprint frozen by the caller')
    parser.add_argument('--no-project-inputs', action='store_true', help='caller explicitly declares no formal project input scope')
    parser.add_argument('--independent-from', help='producer context/person recorded by the caller')
    parser.add_argument('--walkthrough', action='append', choices=('source_coverage', 'counterexample', 'journey'))
    parser.add_argument('--stage', action='append')
    parser.add_argument('--purpose', choices=('tested', 'transfer'), default='tested')
    args = parser.parse_args()
    try:
        if args.target and args.mode != 'checkpoint':
            raise ValueError('--target requires checkpoint mode')
        if args.no_project_inputs and (args.mode != 'checkpoint' or args.inputs or args.expected_inputs):
            raise ValueError('--no-project-inputs is only for a checkpoint without formal inputs')
        if args.mode == 'checkpoint' and not args.inputs and not args.no_project_inputs:
            raise ValueError('checkpoint requires frozen inputs or explicit --no-project-inputs')
        if args.mode not in ('quality', 'checkpoint', 'handoff') and (args.inputs or args.expected_inputs):
            raise ValueError('project scope requires quality, checkpoint or handoff mode')
        if args.mode not in ('quality', 'checkpoint') and (args.independent_from or args.walkthrough):
            raise ValueError('project scope and review policies require quality or checkpoint mode')
        value = json.loads(local_file(args.root, str(args.contract)).read_text())
        inputs = json.loads(local_file(args.root, str(args.inputs)).read_text()) if args.inputs else None
        if args.mode == 'handoff':
            result = check_handoff(value, args.root, args.purpose, require_details=args.require_details,
                                   project_inputs=inputs, expected_inputs=args.expected_inputs)
        elif args.mode in ('quality', 'checkpoint'):
            trace = json.loads(local_file(args.root, str(args.trace)).read_text()) if args.trace else None
            execution = json.loads(local_file(args.root, str(args.execution)).read_text()) if args.execution else None
            targets = [tuple(t.split(':', 1)) for t in (args.target or [])] if args.mode == 'checkpoint' else None
            if args.mode == 'checkpoint' and (not targets or any(len(t) != 2 for t in targets)):
                raise ValueError('checkpoint requires --target stage:artifact')
            if args.no_project_inputs:
                from markdown_it import MarkdownIt
                for _, path in targets:
                    artifact = local_file(args.root, path)
                    if artifact.suffix.lower() in ('.md', '.markdown') and any(
                            token.type == 'fence' and token.info.strip() == 'project-checks'
                            for token in MarkdownIt('commonmark').parse(artifact.read_text())):
                        raise ValueError('artifact declares project-checks; frozen project inputs are required')
            stages = list(dict.fromkeys(t[0] for t in targets)) if targets else args.stage
            result = check_quality(value, args.root, stages, require_details=args.require_details or args.mode == 'checkpoint',
                                   trace=trace, execution=execution, project_inputs=inputs,
                                   expected_inputs=args.expected_inputs, targets=targets,
                                   independent_from=args.independent_from, walkthrough=args.walkthrough)
        else:
            receipt = json.loads(local_file(args.root, str(args.execution)).read_text()) if args.execution else None
            result = check_trace(value, receipt, args.root)
    except (ValueError, OSError, ImportError) as error:
        result = {'valid': False, 'ready': False, 'errors': [str(error)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ready'] else 1


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    with tempfile.TemporaryDirectory(prefix='lifecycle-imports-') as import_cache:
        sys.pycache_prefix = import_cache
        raise SystemExit(main())
