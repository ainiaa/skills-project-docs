"""Prepare a fresh offline review packet from an existing blind sample mapping."""
import argparse
import json
import re
from pathlib import Path

from interaction_evidence import collect, REVIEW_INSTRUCTIONS


def anonymize(text, root):
    # macOS CLI logs can use either /tmp/... or /private/tmp/... for the same file.
    real = root.resolve()
    aliases = {str(root.absolute()), str(real)}
    if real.is_relative_to('/private'):
        alias = Path('/') / real.relative_to('/private')
        if alias.exists() and alias.samefile(real):
            aliases.add(str(alias))
    for path in sorted(aliases, key=len, reverse=True):
        text = text.replace(path, '/capsule')
    return text


def write_evidence(root, target):
    raw = json.dumps(collect(root), ensure_ascii=False, indent=2)
    (target / 'interaction-evidence.json').write_text(anonymize(raw, root) + '\n')


def prepare(key, output, criteria=None):
    mapping = json.loads(key.read_text())
    samples = []
    for label, name in mapping.items():
        if not re.fullmatch(r'sample-\d+', label):
            raise ValueError('Invalid anonymous label')
        root = (key.parent / name).resolve()
        if not (root / 'work/input.txt').is_file():
            raise ValueError(f'Missing input for {label}')
        samples.append((label, root))
    if criteria is None and (key.parent / 'criteria.md').is_file():
        criteria = key.parent / 'criteria.md'
    frozen = criteria.read_bytes() if criteria is not None else None
    output.mkdir(parents=True, exist_ok=False)
    if frozen is not None:
        (output / 'criteria.md').write_bytes(frozen)
    (output / 'review-instructions.txt').write_text(REVIEW_INSTRUCTIONS + '\n')
    for label, root in samples:
        dest = output / label
        dest.mkdir()
        write_evidence(root, dest)
        for path in [root / 'work/input.txt', root / 'logs/user-turn2.txt',
                     *sorted((root / 'work').rglob('*.md'))]:
            if path.is_file() and path.resolve().is_relative_to(root):
                rel = path.relative_to(root / 'work') if path.is_relative_to(root / 'work') else Path(path.name)
                copy = dest / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                copy.write_text(anonymize(path.read_text(), root))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('key', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--criteria', type=Path, help='Frozen criteria for this original batch')
    args = parser.parse_args()
    prepare(args.key, args.output, args.criteria)
