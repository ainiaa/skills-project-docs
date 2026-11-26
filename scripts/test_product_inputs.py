"""Frozen product inputs must include the actual referenced bytes. 作者：Jeff.Liu"""
import copy
import hashlib
from pathlib import Path
import unittest
from urllib.parse import quote

import test_product_handoff as fixtures


class ProductInputsTests(unittest.TestCase):
    def setUp(self):
        fixtures.ProductHandoffTests.setUp(self)

    def freeze(self, **options):
        from product_inputs import freeze_inputs
        return freeze_inputs(self.prd, **options)

    def project_index(self, **changes):
        import json
        from lifecycle_quality import reference
        source = self.root / 'decisions.md'
        source.write_text('Keep request identifiers.\n')
        item = {'id': 'PROJECT-KEEP-ID', 'stage': 'L3', 'check': 'acceptance',
                'required': True, 'method': 'review', 'requirements': ['FR-001'],
                'source': reference(self.root, source.name, 'Keep request identifiers.')}
        item.update(changes)
        content = self.prd.read_text().replace('用户已明确仅展示当前状态。',
                                               '用户已明确仅展示当前状态。[Decisions](decisions.md)')
        self.prd.write_text(content.replace('## 来源', '```project-checks\n'
                            + json.dumps({'items': [item], 'changes': []}) + '\n```\n\n## 来源', 1))
        return item

    def test_project_checks_are_derived_from_frozen_inputs_and_cannot_be_dropped(self):
        from product_inputs import validate_snapshot, digest
        self.project_index()
        snapshot = self.freeze()
        self.assertIn('project_checks', snapshot, 'project scope is not frozen')
        self.assertEqual(snapshot['project_checks']['PROJECT-KEEP-ID']['requirements'], ['FR-001'])
        changed = copy.deepcopy(snapshot)
        changed['project_checks'] = {}
        changed['fingerprint'] = digest({k: v for k, v in changed.items() if k != 'fingerprint'})
        with self.assertRaises(ValueError):
            validate_snapshot(changed)

    def test_project_index_rejects_invalid_binding_source_and_duplicate_declarations(self):
        import json
        original = self.prd.read_text()
        for changes in ({'required': 'true'}, {'requirements': ['FR-999']}, {'stage': 'L11'},
                        {'source': {'path': 'missing.md', 'sha256': '0' * 64, 'quote': 'absent'}}):
            with self.subTest(changes=changes):
                self.prd.write_text(original)
                self.project_index(**changes)
                with self.assertRaises(ValueError):
                    self.freeze()
        self.prd.write_text(original)
        item = self.project_index()
        self.prd.write_text(self.prd.read_text() + '\n```project-checks\n'
                            + json.dumps({'items': [item], 'changes': []}) + '\n```\n')
        with self.assertRaises(ValueError):
            self.freeze()

    def test_single_document_snapshot_is_offline_verifiable_and_read_only(self):
        from product_inputs import validate_snapshot, require_current_inputs
        before = self.prd.read_bytes()
        snapshot = self.freeze()
        self.assertEqual(snapshot['product_version'], 'v1')
        self.assertEqual(snapshot['acceptance']['AC-001']['requirement'], 'FR-001')
        self.assertEqual(snapshot['files'], [{'path': str(self.prd), 'sha256': hashlib.sha256(before).hexdigest()}])
        self.assertEqual(validate_snapshot(snapshot), snapshot)
        require_current_inputs(snapshot)
        self.assertEqual(self.prd.read_bytes(), before)
        self.assertFalse(self.state_root.exists())
        self.prd.unlink()
        self.assertEqual(validate_snapshot(snapshot), snapshot)
        with self.assertRaises((ValueError, OSError)):
            require_current_inputs(snapshot)

    def test_linked_split_tracking_and_recursive_attachments_are_all_frozen(self):
        content = self.prd.read_text()
        tracking = self.root / 'trace.md'
        tracking.write_text('## 追踪\n> 追踪版本：v1\n[主文](prd.md)\n## 来源' + content.split('## 来源', 1)[1])
        self.prd.write_text(content.split('## 来源', 1)[0] + '[追踪](trace.md)\n')
        facts = self.root / 'facts.md'; facts.write_text('事实\n![图片](figure.bin)\n')
        figure = self.root / 'figure.bin'; figure.write_bytes(b'\x00\xff figure')
        tracking.write_text(tracking.read_text().replace('用户已明确仅展示当前状态。', '用户已明确仅展示当前状态。[事实](facts.md)'))
        snapshot = self.freeze(tracking=tracking)
        self.assertEqual({item['path'] for item in snapshot['files']}, {str(p) for p in (self.prd, tracking, facts, figure)})
        self.assertIn(str(figure), snapshot['inputs_by_requirement']['FR-001'])
        from product_inputs import require_current_inputs
        for path in (tracking, facts, figure):
            with self.subTest(path=path.name):
                old = path.read_bytes();path.write_bytes(old + b' changed')
                with self.assertRaises((ValueError, OSError)):
                    require_current_inputs(snapshot)
                path.write_bytes(old)
        require_current_inputs(snapshot)

    def test_remote_resource_requires_explicit_local_snapshot_and_is_not_fetched(self):
        self.prd.write_text(self.prd.read_text().replace('用户已明确仅展示当前状态。', '[访谈](https://example.invalid/interview)'))
        with self.assertRaisesRegex(ValueError, 'snapshot|冻结'):
            self.freeze()
        cached = self.root / 'interview.txt';cached.write_text('实际提供的访谈记录')
        snapshot = self.freeze(attachments={'https://example.invalid/interview': cached})
        self.assertIn(str(cached), snapshot['inputs_by_requirement']['FR-001'])

    def test_missing_outside_and_symlink_resources_are_not_silently_omitted(self):
        original = self.prd.read_text()
        outside = self.root.parent / (self.root.name + '-outside.txt')
        outside.write_text('outside');self.addCleanup(outside.unlink)
        alias = self.root / 'alias.txt';alias.symlink_to(outside)
        for target in ('missing.txt', '../' + outside.name, 'alias.txt'):
            with self.subTest(target=target):
                self.prd.write_text(original + '\n[资料](' + quote(target) + ')\n')
                with self.assertRaises((ValueError, OSError)):
                    self.freeze()
        snapshot = self.freeze(attachments={'alias.txt': outside})
        self.assertIn(str(outside), {item['path'] for item in snapshot['files']})

    def test_cyclic_markdown_links_are_finite_and_opaque_attachments_are_whole_files(self):
        self.prd.write_text(self.prd.read_text() + '\n[附件](extra.md)\n')
        (self.root / 'extra.md').write_text('[主文](prd.md)\n[归档](archive.pdf)\n')
        (self.root / 'archive.pdf').write_bytes(b'opaque\x00 bytes')
        self.assertEqual(len(self.freeze()['files']), 3)

    def test_snapshot_cannot_relabel_rules_or_drop_an_input(self):
        from product_inputs import digest, validate_snapshot
        self.prd.write_text(self.prd.read_text() + '\n[资料](fact.txt)\n')
        (self.root / 'fact.txt').write_text('fact')
        snapshot = self.freeze()
        for mutate in (lambda s:s['requirements'].update({'FR-001': '0'*64}),
                       lambda s:s['files'].pop(),
                       lambda s:s['documents'].update({str(self.prd): '# Forged'})):
            with self.subTest(mutate=mutate):
                bad = copy.deepcopy(snapshot);mutate(bad)
                bad['fingerprint'] = digest({k:v for k,v in bad.items() if k != 'fingerprint'})
                with self.assertRaises(ValueError):
                    validate_snapshot(bad)

    def test_snapshot_cannot_omit_markdown_attachment_text_or_add_unselected_files(self):
        from product_inputs import digest,validate_snapshot
        self.prd.write_text(self.prd.read_text()+'\n[事实](facts.md)\n')
        attachment=self.root/'facts.md';attachment.write_text('必须参与离线核对的附件原文。')
        snapshot=self.freeze()
        missing=copy.deepcopy(snapshot);missing['documents'].pop(str(attachment))
        missing['fingerprint']=digest({k:v for k,v in missing.items() if k!='fingerprint'})
        with self.assertRaises(ValueError):validate_snapshot(missing)
        extra=self.root/'unused.txt';extra.write_text('未被选择的输入')
        orphan=copy.deepcopy(snapshot)
        orphan['files'].append({'path':str(extra),'sha256':hashlib.sha256(extra.read_bytes()).hexdigest()})
        orphan['files'].sort(key=lambda item:item['path'])
        orphan['fingerprint']=digest({k:v for k,v in orphan.items() if k!='fingerprint'})
        with self.assertRaises(ValueError):validate_snapshot(orphan)

    def test_only_owning_requirement_changes_when_its_attachment_changes(self):
        self.prd.write_text(self.prd.read_text().replace('用户已明确仅展示当前状态。', '[事实](one.txt)') + '''
### SRC-002 其他需求
其他来源。
### FR-002 编辑名称
状态：已确认
依据：SRC-002
原型：否
确认记录：业务负责人 产品版本 v1
#### AC-002 保存名称
给定有效名称，保存后显示新名称。
''')
        fact=self.root/'one.txt';fact.write_text('one')
        before=self.freeze();fact.write_text('changed');after=self.freeze()
        self.assertNotEqual(before['requirements']['FR-001'],after['requirements']['FR-001'])
        self.assertEqual(before['requirements']['FR-002'],after['requirements']['FR-002'])

    def test_snapshot_requires_confirmed_input_and_matching_tracking_version(self):
        self.prd.write_text(self.prd.read_text().replace('已确认','草稿'))
        with self.assertRaises(ValueError):
            self.freeze()
        self.prd.write_text('# Business\n> 产品版本：v2\n> 状态：已确认\n[追踪](trace.md)\n')
        trace=self.root/'trace.md';trace.write_text('## 追踪\n> 追踪版本：v1\n')
        with self.assertRaises(ValueError):
            self.freeze(tracking=trace)

    def test_tracking_cannot_supply_the_main_documents_missing_title(self):
        content=self.prd.read_text()
        trace=self.root/'trace.md'
        trace.write_text('# Borrowed title\n> 追踪版本：v1\n## 来源'+content.split('## 来源',1)[1])
        self.prd.write_text('> 产品版本：v1\n> 状态：已确认\n[追踪](trace.md)\n')
        with self.assertRaises(ValueError):
            self.freeze(tracking=trace)
