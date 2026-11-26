"""Maintain typed business relations in the existing Lifecycle record. 作者：Jeff.Liu"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

if __package__:
    from . import lifecycle_record as records
else:
    import lifecycle_record as records

TYPES = records.RELATION_TYPES
SYMMETRIC = records.SYMMETRIC_RELATIONS
validate_relations = records.validate_relations


def _require_record(data):
    checked = records.check_record(data)
    if not checked['valid']:
        raise ValueError('invalid Lifecycle record: ' + '; '.join(checked['errors']))
    return validate_relations(data)


def query(data, identity, relation=None, direction='both'):
    graph = _require_record(data)
    if identity not in {node['id'] for node in data['artifacts']}:
        raise ValueError('unknown artifact ID')
    if relation is not None and relation not in TYPES:
        raise ValueError('unknown relation type')
    if direction not in ('incoming','outgoing','both'):
        raise ValueError('unknown relation direction')
    edges = [edge for edge in graph['edges'] if (relation is None or edge['type'] == relation)
             and ((edge['type'] in SYMMETRIC and identity in (edge['source'],edge['target']))
                  or (direction in ('outgoing','both') and edge['source'] == identity)
                  or (direction in ('incoming','both') and edge['target'] == identity))]
    return dict(id=identity, edges=edges, stale=[edge for edge in graph['stale'] if edge in edges],
                scope='declared_relations_only')


def impact(data, identity):
    graph = query(data, identity)
    relations = validate_relations(data)
    edges = relations['edges']
    selected, pending = {identity}, {identity}
    direct = sorted({e['source'] for e in edges if e['type']=='depends_on' and e['target']==identity})
    while pending:
        pending = {e['source'] for e in edges if e['type']=='depends_on' and e['target'] in pending} - selected
        selected.update(pending)
    return dict(id=identity, direct=direct, indirect=sorted(selected-{identity}-set(direct)), affected=sorted(selected),
                context=[e for e in edges if e['type']!='depends_on' and (e['source'] in selected or e['target'] in selected)],
                stale=[e for e in relations['stale'] if e['source'] in selected or e['target'] in selected], scope=graph['scope'], business_authorization=False)


def orphans(data):
    graph = validate_relations(data)
    checked = records.check_record(data)
    connected = {e[key] for e in graph['edges'] for key in ('source','target')}
    artifacts = data.get('artifacts', []) if isinstance(data,dict) else []
    nodes = {n['id'] for n in artifacts if isinstance(n,dict) and isinstance(n.get('id'),str)} if isinstance(artifacts,list) else set()
    return dict(valid=checked['valid'], dangling=graph['dangling'], isolated=sorted(nodes-connected), errors=checked['errors'],
                scope='declared_relations_only')


def _candidate(before, source, relation, target, remove):
    candidate = copy.deepcopy(before)
    nodes = {node['id']:node for node in candidate['artifacts']}
    if source not in nodes or target not in nodes or source == target or relation not in TYPES:
        raise ValueError('unknown endpoint/type or self relation')
    # Symmetric edges have one storage owner; reverse operations edit that same owner.
    owner, destination = source, target
    if relation in SYMMETRIC and any(ref['id']==source for ref in nodes[target].get('relations',{}).get(relation,[])):
        owner, destination = target, source
    node = nodes[owner]
    refs = node['depends_on'] if relation=='depends_on' else node.setdefault('relations',{}).setdefault(relation,[])
    wanted = next((copy.deepcopy(ref) for ref in refs if ref['id']==destination), {'id':destination})
    wanted['version'] = nodes[destination]['version']
    old = copy.deepcopy(refs)
    if remove:
        refs[:] = [ref for ref in refs if ref['id'] != destination]
    elif any(ref['id']==destination for ref in refs):
        refs[:] = [wanted if ref['id']==destination else ref for ref in refs]
    else:
        refs.append(wanted)
    if refs == old or (remove and not old):
        return before
    node['version'] += 1
    candidate['revision'] += 1
    candidate['updated_at'] = datetime.now(timezone.utc).isoformat()
    _require_record(candidate)
    return candidate


def set_relation(path, source, relation, target, expected_revision, *, remove=False):
    """CAS mutation, exact replay via existing immutable history, no operation ledger."""
    if type(expected_revision) is not int or expected_revision <= 0 or type(remove) is not bool:
        raise ValueError('expected_revision must be a positive integer and remove a boolean')
    path = Path(path).resolve(strict=True)
    with records._record_lock(path):
        current = json.loads(path.read_bytes())
        _require_record(current)
        if current['revision'] != expected_revision:
            history = path.with_name(f'{path.name}.rev-{expected_revision}.json')
            if not history.is_file() or current['revision'] < expected_revision:
                raise ValueError('record revision conflict')
            before = json.loads(history.read_bytes())
            _require_record(before)
            candidate = _candidate(before,source,relation,target,remove)
            if candidate == before:
                raise ValueError('record revision conflict')
            saved = current if current['revision']==expected_revision+1 else json.loads(
                path.with_name(f'{path.name}.rev-{expected_revision+1}.json').read_bytes())
            _require_record(saved)
            candidate['updated_at'] = saved['updated_at']
            if json.dumps(candidate,sort_keys=True) != json.dumps(saved,sort_keys=True) or any(before[k]!=current[k] for k in ('project_ref','subject_ref')):
                raise ValueError('record revision conflict')
            return dict(status='resumed', revision=current['revision'])
        candidate = _candidate(current,source,relation,target,remove)
        if candidate == current:
            return dict(status='unchanged', revision=current['revision'])
        records._update_record_locked(path,candidate,expected_revision)
        return dict(status='applied', revision=candidate['revision'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    for name in ('set','query','impact','orphans','validate'):
        command = commands.add_parser(name)
        command.add_argument('--record',type=Path,required=True)
        if name=='set':
            command.add_argument('--source',required=True)
            command.add_argument('--type',choices=TYPES,required=True)
            command.add_argument('--target',required=True)
            command.add_argument('--expected-revision',type=int,required=True)
            command.add_argument('--remove',action='store_true')
        if name in ('query','impact'):
            command.add_argument('--id',required=True)
        if name=='query':
            command.add_argument('--type',choices=TYPES)
            command.add_argument('--direction',choices=('incoming','outgoing','both'),default='both')
    args = parser.parse_args()
    try:
        if args.command=='set':
            result=set_relation(args.record,args.source,args.type,args.target,args.expected_revision,remove=args.remove)
        else:
            data = json.loads(args.record.read_bytes())
            if args.command=='query':result=query(data,args.id,args.type,args.direction)
            elif args.command=='impact':result=impact(data,args.id)
            elif args.command=='orphans':result=orphans(data)
            else:result=records.check_record(data)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return int(result.get('valid') is False or (args.command=='validate' and bool(result['needs_review'])))
    except (OSError,ValueError,TypeError,KeyError) as error:
        print(json.dumps(dict(valid=False,errors=[str(error)]),ensure_ascii=False))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
