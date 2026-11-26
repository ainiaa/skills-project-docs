#!/usr/bin/env python3
"""Read the repository checklist and verify its recorded local provenance. 作者：Jeff.Liu"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'skills/project-docs-lifecycle/references/checklist-catalog.json'
KINDS = {'local_method', 'adapted_method', 'lineage_record', 'local_regression'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def load_catalog(stage=None, *, verify_sources=False):
    raw = CATALOG.read_bytes()
    data = json.loads(raw)
    _require(isinstance(data, dict) and type(data.get('schema_version')) is int
             and data['schema_version'] == 1, 'unsupported checklist catalog')
    items = data.get('items')
    _require(isinstance(items, list) and bool(items), 'catalog items required')
    seen = set()
    for item in items:
        _require(isinstance(item, dict), 'catalog item must be an object')
        identity = item.get('id')
        _require(isinstance(identity, str) and re.fullmatch(r'L(?:10|[0-9])-[A-Z0-9-]+', identity)
                 and identity not in seen, 'duplicate or invalid checklist ID')
        seen.add(identity)
        _require(isinstance(item.get('stage'), str) and item['stage'] in {f'L{i}' for i in range(11)}, 'invalid catalog stage')
        _require(identity.startswith(item['stage'] + '-'), 'checklist ID/stage mismatch')
        _require(type(item.get('required')) is bool, 'required must be boolean')
        _require(item.get('verification') in ('review', 'test'), 'invalid verification method')
        for key in ('check', 'question', 'when', 'evidence_expected'):
            _require(isinstance(item.get(key), str) and bool(item[key].strip()), f'catalog {key} required')
    _require(stage is None or isinstance(stage, str) and stage in {item['stage'] for item in items}, 'unknown checklist stage')
    selected = [item for item in items if stage is None or item['stage'] == stage]
    for item in selected:
        sources = item.get('sources')
        _require(isinstance(sources, list) and bool(sources), 'checklist provenance required')
        for source in sources:
            _require(isinstance(source, dict) and isinstance(source.get('kind'), str) and source['kind'] in KINDS, 'invalid provenance kind')
            relative = source.get('path')
            _require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
                     and '..' not in Path(relative).parts, 'relative provenance path required')
            quote = source.get('quote')
            digest = source.get('sha256')
            _require(isinstance(quote, str) and bool(quote.strip()), 'provenance quote missing')
            _require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'invalid provenance SHA-256')
            if verify_sources:
                path = (ROOT / relative).resolve()
                _require(path.is_relative_to(ROOT) and path.is_file(), 'missing or external provenance')
                content = path.read_bytes()
                _require(digest == hashlib.sha256(content).hexdigest(), f'stale provenance: {relative}')
                _require(quote in content.decode('utf-8'), 'provenance quote missing')
        _require(not any(s['kind'] == 'adapted_method' for s in sources)
                 or any(s['kind'] == 'lineage_record' for s in sources), 'adapted method needs recorded lineage')
    rules = [{key: item[key] for key in ('id', 'stage', 'check', 'required', 'verification',
                                        'question', 'when', 'evidence_expected')} for item in selected]
    material = {'schema_version': data['schema_version'], 'items': rules}
    return {**data, 'items': selected, 'fingerprint': hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=[f'L{i}' for i in range(11)])
    parser.add_argument('--verify-sources', action='store_true', help='audit provenance in the source checkout')
    args = parser.parse_args()
    try:
        print(json.dumps(load_catalog(args.stage, verify_sources=args.verify_sources), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({'valid': False, 'errors': [str(error)]}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
