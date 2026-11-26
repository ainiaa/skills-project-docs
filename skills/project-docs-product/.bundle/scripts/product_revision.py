"""Compare frozen product versions and invalidate declared Lifecycle dependents. 作者：Jeff.Liu"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from lifecycle_record import check_record, update_record, _same_json
from product_inputs import digest, require_current_inputs, validate_snapshot


def _difference(before, after):
    return {'added': sorted(after.keys() - before.keys()), 'removed': sorted(before.keys() - after.keys()),
            'modified': sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
            'unchanged': sorted(key for key in before.keys() & after.keys() if before[key] == after[key])}


def _check_rules(snapshot):
    # File hashes prove the source is current. Only the cited rule affects scope.
    return {key: {**item, 'source': {k: v for k, v in item['source'].items() if k != 'sha256'}}
            for key, item in snapshot.get('project_checks', {}).items()}


def _plan(before, after, record_path, record, bindings, prepared_at):
    validate_snapshot(before)
    validate_snapshot(after)
    stamp = datetime.fromisoformat(prepared_at)
    if stamp.utcoffset() is None:
        raise ValueError('revision preparation timestamp requires a timezone')
    changes = {key: _difference(before[key], after[key]) for key in ('requirements', 'acceptance')}
    project_changes = _difference(_check_rules(before), _check_rules(after))
    scope_gaps = []
    for identity in project_changes['removed'] + project_changes['modified']:
        decision = after.get('project_check_changes', {}).get(identity, {})
        new_definition = after.get('project_checks', {}).get(identity)
        if (decision.get('before') != digest(before['project_checks'][identity])
                or decision.get('after') != (digest(new_definition) if new_definition is not None else None)):
            scope_gaps.append({'id': identity, 'reason': 'project check change requires a decision bound to both definitions'})
    if 'project_checks' in before or 'project_checks' in after:
        changes['project_checks'] = project_changes
    changes['files'] = _difference(*({item['path']: item['sha256'] for item in s['files']} for s in (before, after)))
    changed = sorted({key for kind in ('added', 'removed', 'modified') for key in changes['requirements'][kind]})
    acceptance = sorted({ac for snapshot in (before, after) for ac, item in snapshot['acceptance'].items()
                         if item['requirement'] in changed})
    affected, update = [], None
    if record is not None:
        if not isinstance(record_path, str) or not Path(record_path).is_absolute() or os.path.abspath(record_path) != record_path:
            raise ValueError('Lifecycle record path must be absolute and canonical')
        checked = check_record(record)
        if not checked['valid']:
            raise ValueError('invalid Lifecycle record: ' + '; '.join(checked['errors']))
        expected = before['requirements'].keys() | after['requirements'].keys()
        nodes = {node['id']: node for node in record['artifacts']}
        if (not isinstance(bindings, dict) or set(bindings) != expected
                or any(not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in nodes for i in ids)
                       or len(ids) != len(set(ids)) for ids in bindings.values())):
            raise ValueError('every old/new requirement must explicitly map to existing unique artifact IDs')
        pending = {node for key in changed for node in bindings[key]}
        selected = set()
        while pending:
            selected.update(pending)
            pending = {node['id'] for node in nodes.values() if node['id'] not in selected
                       and any(ref['id'] in selected for ref in node['depends_on'])}
        affected = sorted(selected)
        if affected:
            candidate = copy.deepcopy(record)
            candidate.update(revision=record['revision'] + 1, updated_at=prepared_at)
            for node in candidate['artifacts']:
                if node['id'] in selected:
                    node.update(version=node['version'] + 1, status='pending_confirmation',
                                reason=f"product revision {before['product_version']} → {after['product_version']}",
                                recovery='Review changed requirements and dependencies; rebind versions and obtain new evidence.')
            update = {'path': record_path, 'before': record, 'candidate': candidate}
    elif record_path is not None or bindings is not None:
        raise ValueError('record and requirement bindings must be supplied together')
    result = {'schema_version': 1, 'before': before, 'after': after, 'changes': changes,
              'version_changed': before['product_version'] != after['product_version'],
              'affected_requirements': changed, 'affected_acceptance': acceptance, 'affected_artifacts': affected,
              'impact_scope': 'declared_dependencies' if record is not None else 'requirements_only',
              'record_path': record_path, 'record_before': record, 'bindings': bindings,
              'record_update': update, 'prepared_at': prepared_at,
              'business_authorization': False, 'deployment_verified': False}
    if 'project_checks' in changes:
        result.update(scope_ready=not scope_gaps, scope_gaps=scope_gaps)
    return {**result, 'fingerprint': digest(result)}


def plan_revision(before, after, *, record_path=None, bindings=None):
    path = str(Path(record_path).expanduser().resolve()) if record_path is not None else None
    record = json.loads(Path(path).read_text()) if path is not None else None
    return _plan(before, after, path, record, bindings, datetime.now(timezone.utc).isoformat())


def validate_revision(report):
    try:
        expected = _plan(*(report[key] for key in ('before', 'after', 'record_path', 'record_before', 'bindings', 'prepared_at')))
        if not _same_json(report, expected):
            raise ValueError('revision report identity or derived impact differs')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid revision report') from error
    return report


def apply_impact(report):
    validate_revision(report)
    if not report.get('scope_ready', True):
        raise ValueError('project scope has unresolved changes')
    require_current_inputs(report['after'])
    update = report['record_update']
    if update is None:
        return {'status': 'not_needed', 'affected_artifacts': report['affected_artifacts']}
    path = Path(update['path'])
    if path.resolve() != path:
        raise ValueError('Lifecycle record location changed to a symlink')
    candidate = update['candidate']
    current = json.loads(path.read_text())
    if not check_record(current)['valid']:
        raise ValueError('current Lifecycle record is invalid')
    if any(current[key] != update['before'][key] for key in ('project_ref', 'subject_ref')):
        raise ValueError('Lifecycle record identity changed since revision preparation')
    if _same_json(current, candidate):
        return {'status': 'resumed', 'path': str(path)}
    if check_record(current)['valid'] and current['revision'] > candidate['revision']:
        history = path.with_name(f"{path.name}.rev-{candidate['revision']}.json")
        if history.is_file() and _same_json(json.loads(history.read_text()), candidate):
            return {'status': 'resumed', 'path': str(path)}
    if not _same_json(current, update['before']):
        raise ValueError('Lifecycle record changed since revision preparation')
    update_record(path, candidate, update['before']['revision'])
    require_current_inputs(report['after'])
    return {'status': 'applied', 'path': str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('before', 'after', 'record', 'bindings', 'report', 'expected-impact'):
        parser.add_argument('--' + name)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.report:
            if args.before or args.after or args.record or args.bindings:
                raise ValueError('saved report cannot be combined with new revision inputs')
            report = validate_revision(json.loads(Path(args.report).read_text()))
        else:
            if not args.before or not args.after or args.apply or args.expected_impact:
                raise ValueError('supply --before and --after to prepare; use saved --report to apply')
            snapshots = [json.loads(Path(path).read_text()) for path in (args.before, args.after)]
            if any(not isinstance(value, dict) for value in snapshots):
                raise ValueError('before and after snapshots must be JSON objects')
            before, after = [value.get('input_snapshot', value) for value in snapshots]
            bindings = json.loads(Path(args.bindings).read_text()) if args.bindings else None
            report = plan_revision(before, after, record_path=args.record, bindings=bindings)
        if args.apply and args.expected_impact != report['fingerprint']:
            raise ValueError('application requires the unchanged revision fingerprint')
        print(json.dumps(apply_impact(report) if args.apply else report, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({'valid': False, 'applied': False, 'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
