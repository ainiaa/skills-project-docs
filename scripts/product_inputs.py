"""Freeze selected product inputs and verify their offline semantic identity. 作者：Jeff.Liu"""
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from validate_product_doc import approval_content, document_contract, field, prose


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _resource_path(source, reference, root, attachments):
    target = urlsplit(reference)
    if target.scheme == 'data' or not target.scheme and not target.netloc and not target.path:
        return None
    if reference in attachments:
        return attachments[reference]
    if target.scheme or target.netloc:
        raise ValueError(f'resource requires an explicit local snapshot: {reference}')
    path = Path(os.path.abspath(Path(source).parent / unquote(target.path)))
    if not path.is_relative_to(root):
        raise ValueError(f'input outside PRD directory requires an explicit snapshot: {reference}')
    return str(path)


def _rule_meaning(rule, requirement):
    from markdown_it import MarkdownIt
    tokens = MarkdownIt('commonmark').parse(rule)
    opaque = {line for token in tokens if token.type in {'fence', 'code_block', 'html_block'} and token.map
              for line in range(*token.map)}
    lines = rule.splitlines(keepends=True)
    boundary = next((token.map[0] for token in tokens if token.type == 'heading_open'
                     and token.level == 0 and token.tag == 'h4'), len(lines))
    metadata = {'状态': requirement['status'], '确认记录': requirement['confirmation']}
    result = []
    for number, line in enumerate(lines):
        match = re.fullmatch(r'(状态|确认记录)：[ \t]*(.*)', line.rstrip('\r\n'))
        if number < boundary and number not in opaque and match and metadata.get(match[1]) == match[2].strip():
            metadata.pop(match[1])
        else:
            result.append(line)
    return ''.join(result)


def _project_checks(documents, files, prd, tracking):
    """Project indexes live in the existing formal inputs, never in review results."""
    from markdown_it import MarkdownIt
    from lifecycle_quality import STAGE_CHECKS
    blocks, clean = [], {}
    for path in (prd, tracking):
        if path is None:
            continue
        text = documents[path]
        lines = text.splitlines(keepends=True)
        for token in MarkdownIt('commonmark').parse(text):
            if token.type == 'fence' and token.info.strip() == 'project-checks':
                blocks.append(json.loads(token.content))
                start, end = token.map
                lines[start:end] = [''] * (end - start)
        clean[path] = ''.join(lines)
    if not blocks:
        return {}, {}, clean
    if len(blocks) != 1 or not isinstance(blocks[0], dict) or set(blocks[0]) != {'items', 'changes'}:
        raise ValueError('one project-checks object with items and changes is required')
    index = blocks[0]
    if not all(isinstance(index[key], list) for key in ('items', 'changes')):
        raise ValueError('project-checks items and changes must be arrays')

    def source(value):
        if (not isinstance(value, dict) or set(value) != {'path', 'sha256', 'quote'}
                or not isinstance(value['path'], str) or not value['path'].strip()):
            raise ValueError('project check source requires path, sha256 and quote')
        path = _resource_path(prd, value['path'], Path(prd).parent, {})
        if (path not in files or value['sha256'] != files[path] or path not in documents
                or not isinstance(value['quote'], str) or not value['quote'].strip()
                or value['quote'] not in documents[path]):
            raise ValueError('project check source must quote a frozen Markdown input')
        return {**value, 'path': path}

    items, changes = {}, {}
    for item in index['items']:
        if not isinstance(item, dict) or set(item) != {'id', 'stage', 'check', 'required', 'method', 'requirements', 'source'}:
            raise ValueError('invalid project check definition')
        identity = item['id']
        if (not isinstance(identity, str) or not re.fullmatch(r'PROJECT-[A-Za-z0-9][A-Za-z0-9._-]{0,119}', identity)
                or identity in items or not isinstance(item['stage'], str) or item['stage'] not in STAGE_CHECKS
                or item['check'] not in STAGE_CHECKS[item['stage']] or type(item['required']) is not bool
                or item['method'] not in ('review', 'test')):
            raise ValueError('invalid or duplicate project check identity or method')
        links = item['requirements']
        if (not isinstance(links, list) or not links or any(not isinstance(key, str) for key in links)
                or len(links) != len(set(links))):
            raise ValueError('project check must bind existing unique requirements')
        items[identity] = {**item, 'source': source(item['source'])}
    for item in index['changes']:
        if (not isinstance(item, dict) or set(item) != {'id', 'reason', 'source', 'before', 'after'}
                or not isinstance(item['id'], str) or item['id'] in changes
                or not isinstance(item['reason'], str) or not item['reason'].strip()
                or not isinstance(item['before'], str) or not re.fullmatch('[a-f0-9]{64}', item['before'])
                or item['after'] is not None and (not isinstance(item['after'], str)
                                                or not re.fullmatch('[a-f0-9]{64}', item['after']))):
            raise ValueError('invalid project check change decision')
        changes[item['id']] = {**item, 'source': source(item['source'])}
    return items, changes, clean


def _describe(base, *, manual_handoff=False):
    if base['schema_version'] != 1:
        raise ValueError('unsupported input snapshot')
    prd, tracking, attachments = base['prd'], base['tracking'], base['attachments']
    if (not isinstance(prd, str) or not Path(prd).is_absolute()
            or tracking is not None and (not isinstance(tracking, str) or Path(tracking).parent != Path(prd).parent or tracking == prd)):
        raise ValueError('invalid formal document paths')
    if not isinstance(attachments, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str)
                                               or not Path(v).is_absolute() for k, v in attachments.items()):
        raise ValueError('attachments must map references to explicit local files')
    files = {}
    for item in base['files']:
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256'} or not isinstance(item['path'], str)
                or not Path(item['path']).is_absolute() or not isinstance(item['sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', item['sha256']) or item['path'] in files):
            raise ValueError('invalid or duplicate frozen file')
        files[item['path']] = item['sha256']
    documents = base['documents']
    if not isinstance(documents, dict) or prd not in documents or tracking and tracking not in documents:
        raise ValueError('formal input text is missing')
    expected_documents = {path for path in files if path in {prd, tracking} or Path(path).suffix.lower() in {'.md', '.markdown'}}
    if set(documents) != expected_documents:
        raise ValueError('every frozen Markdown input must retain its original text')
    for path, text in documents.items():
        if not isinstance(text, str) or files.get(path) != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError('stored document bytes do not match frozen input')
    if any(path not in files for path in attachments.values()):
        raise ValueError('attachment is not frozen')
    edges = []
    for source, text in sorted(documents.items()):
        for ref in prose(text, omit_web_reading=manual_handoff and source == prd)[1]:
            path = _resource_path(source, ref, Path(prd).parent, attachments)
            if path is not None:
                if path not in files:
                    raise ValueError(f'referenced input was not frozen: {ref}')
                edges.append({'source': source, 'reference': ref, 'path': path})
    pending = {prd, *([tracking] if tracking else []), *attachments.values()}
    reachable = set()
    while pending:
        source = pending.pop()
        if source not in reachable:
            reachable.add(source)
            pending.update(edge['path'] for edge in edges if edge['source'] == source)
    if reachable != files.keys():
        raise ValueError('snapshot contains inputs outside the selected reference closure')
    main = documents[prd]
    main_prose = prose(main)[0]
    version = field(main_prose, '产品版本', quoted=True)
    titles = re.findall(r'(?m)^#[ \t]+([^\n]*)$', main_prose)
    if len(titles) != 1 or not titles[0].strip() or not version or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version):
        raise ValueError('main document must declare its own title and product version')
    if field(main_prose, '状态', quoted=True) != '已确认':
        raise ValueError('formal PRD must be confirmed')
    companion = documents[tracking] if tracking else None
    resources = prose(main)[1] + (prose(companion)[1] if companion is not None else [])
    internal = [e['reference'] for e in edges if e['source'] in {prd, tracking} and e['path'] in {prd, tracking}]
    if tracking:
        if (field(prose(companion)[0], '追踪版本', quoted=True) != version
                or not any(e['source'] == prd and e['path'] == tracking for e in edges)):
            raise ValueError('tracking version or main document link differs')
        parsed = (prose(main)[0] + '\n\n## 文档边界\n\n' + prose(companion)[0], resources)
    else:
        parsed = None
    project_checks, project_changes, clean = _project_checks(documents, files, prd, tracking)
    meaning = approval_content(clean[prd], clean.get(tracking), internal)
    errors, version, requirements, scenarios, _ = document_contract(
        main + ('\n\n' + companion if companion is not None else ''), parsed=parsed, meaning=meaning,
        confirmation_resources=[ref for ref in resources if ref not in internal])
    if errors:
        raise ValueError('; '.join(errors))
    if any(set(item['requirements']) - requirements.keys() for item in project_checks.values()):
        raise ValueError('project check must bind existing requirements')
    owners, fingerprints = {}, {}
    explicit_shared = set(attachments.values()) - {e['path'] for e in edges}
    for identifier in requirements:
        rule, sources, shared, refs = meaning[identifier]
        pending = set(explicit_shared)
        for ref in refs:
            pending.update(e['path'] for e in edges if e['source'] in {prd, tracking} and e['reference'] == ref)
        selected = set()
        while pending:
            path = pending.pop()
            if path in selected or path in {prd, tracking}:
                continue
            selected.add(path)
            pending.update(e['path'] for e in edges if e['source'] == path)
        owners[identifier] = sorted(selected)
        normalized_rule = _rule_meaning(rule, requirements[identifier])
        fingerprints[identifier] = digest([normalized_rule, sources, shared, [(p, files[p]) for p in sorted(selected)]])
        scoped = [item for item in project_checks.values() if identifier in item['requirements']]
        if scoped:
            fingerprints[identifier] = digest([fingerprints[identifier], scoped])
    from markdown_it import MarkdownIt
    acceptance = {}
    for source in (main, companion):
        if source is None:
            continue
        lines = source.splitlines()
        tokens = MarkdownIt('commonmark').parse(source)
        headings = [(token.map[0], int(token.tag[1:])) for token in tokens if token.type == 'heading_open' and token.level == 0]
        for index, (start, level) in enumerate(headings):
            match = re.match(r'^####\s+(AC-\d+)\s+', lines[start]) if level == 4 else None
            if match:
                end = next((line for line, depth in headings[index + 1:] if depth <= 4), len(lines))
                ac = match[1]
                acceptance[ac] = {'requirement': scenarios[ac], 'fingerprint': digest('\n'.join(lines[start:end]))}
    if set(acceptance) != set(scenarios):
        raise ValueError('acceptance source positions are unavailable')
    result = {**base, 'product_version': version, 'requirements': fingerprints, 'acceptance': acceptance,
              'resources': edges, 'inputs_by_requirement': owners}
    if project_checks or project_changes:
        result.update(project_checks=project_checks, project_check_changes=project_changes)
    return {**result, 'fingerprint': digest(result)}


def freeze_inputs(prd, *, tracking=None, attachments=None, manual_handoff=False):
    prd = str(Path(prd).expanduser().resolve())
    tracking = str(Path(tracking).expanduser().resolve()) if tracking is not None else None
    if attachments is not None and not isinstance(attachments, dict):
        raise ValueError('attachments must be a reference-to-file mapping')
    mapped = {}
    for ref, value in (attachments or {}).items():
        if not isinstance(ref, str) or not ref or not isinstance(value, (str, Path)):
            raise ValueError('attachment reference and path must be nonempty')
        mapped[ref] = str((Path(prd).parent / Path(value).expanduser()).resolve())
    files, documents = {}, {}
    pending = [prd, *([tracking] if tracking else []), *mapped.values()]
    while pending:
        name = pending.pop()
        if name in files:
            continue
        path = Path(name)
        if path.resolve() != path or not path.is_file():
            raise ValueError(f'input is missing or is an undeclared symlink: {name}')
        data = path.read_bytes()
        files[name] = hashlib.sha256(data).hexdigest()
        if name in {prd, tracking} or path.suffix.lower() in {'.md', '.markdown'}:
            text = data.decode('utf-8')
            documents[name] = text
            for ref in prose(text, omit_web_reading=manual_handoff and name == prd)[1]:
                linked = _resource_path(name, ref, Path(prd).parent, mapped)
                if linked is not None:
                    pending.append(linked)
    snapshot = _describe({'schema_version': 1, 'prd': prd, 'tracking': tracking, 'attachments': mapped,
                          'files': [{'path': p, 'sha256': files[p]} for p in sorted(files)], 'documents': documents},
                         manual_handoff=manual_handoff)
    require_current_inputs(snapshot, manual_handoff=manual_handoff)
    return snapshot


def validate_snapshot(snapshot, *, manual_handoff=False):
    try:
        keys = ('schema_version', 'prd', 'tracking', 'attachments', 'files', 'documents')
        expected = _describe({key: snapshot[key] for key in keys}, manual_handoff=manual_handoff)
        if snapshot != expected:
            raise ValueError('input snapshot identity or semantic projection differs')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('invalid input snapshot') from error
    return snapshot


def require_current_inputs(snapshot, *, manual_handoff=False):
    validate_snapshot(snapshot, manual_handoff=manual_handoff)
    for item in snapshot['files']:
        path = Path(item['path'])
        if path.resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise ValueError(f'frozen input changed: {path}')


def input_references(snapshot):
    validate_snapshot(snapshot)
    return [{'reference': item['path'], 'status': 'read', 'content_fingerprint': item['sha256']}
            for item in snapshot['files']]
