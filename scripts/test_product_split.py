"""Split delivery must preserve the existing structural and path checks."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts/validate_product_doc.py'
MAIN = '''# 报名餐食
> 产品版本：draft-1
> 状态：草稿

## 业务规则
每人一份，保存结果须与确认一致。

[验收追踪](trace.md)
'''
TRACE = '''## 验收与追踪
> 追踪版本：draft-1

[业务主文](prd.md)

### FR-01 餐食份数
状态：草稿
依据：SRC-01
原型：否
见业务规则。
#### AC-01 两人报名
2人各1份，保存2份。
### SRC-01 输入
本例为模拟口述。
'''

class SplitProductTests(unittest.TestCase):
    def run_check(self, directory, extra=()):
        args=[sys.executable,str(CLI),'--file',str(directory/'prd.md'),*extra]
        result=subprocess.run(args,text=True,capture_output=True)
        # Missing CLI support is a red light, not a malformed fixture success.
        self.assertTrue(result.stdout, result.stderr)
        return result.returncode,json.loads(result.stdout)

    def fixture(self, directory):
        (directory/'prd.md').write_text(MAIN)
        (directory/'trace.md').write_text(TRACE)

    def test_linked_split_and_legacy_single_document(self):
        with tempfile.TemporaryDirectory() as folder:
            d=Path(folder);self.fixture(d)
            code,report=self.run_check(d,('--tracking',str(d/'trace.md')))
            self.assertEqual(code,0,report)
            (d/'prd.md').write_text(MAIN+'\n'+TRACE)
            self.assertEqual(self.run_check(d)[0],0)

    def test_main_alone_does_not_skip_requirement_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            d=Path(folder);self.fixture(d)
            code,report=self.run_check(d)
            self.assertNotEqual(code,0)
            self.assertTrue(any('FR' in p for p in report['problems']))

    def test_stale_duplicate_missing_and_unlinked_tracking_rejected(self):
        mutations=[('stale',MAIN,TRACE.replace('追踪版本：draft-1','追踪版本：draft-0')),
                   ('duplicate',MAIN,TRACE+'\n### FR-01 重复\n状态：草稿\n'),
                   ('unlinked',MAIN.replace('[验收追踪](trace.md)','追踪另存'),TRACE),
                   ('wrong_level',MAIN,TRACE.replace('#### AC-01','### AC-01'))]
        for name,main,trace in mutations:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                d=Path(folder);self.fixture(d);(d/'prd.md').write_text(main);(d/'trace.md').write_text(trace)
                self.assertNotEqual(self.run_check(d,('--tracking',str(d/'trace.md')))[0],0)
        with tempfile.TemporaryDirectory() as folder:
            d=Path(folder);self.fixture(d);(d/'trace.md').unlink()
            self.assertNotEqual(self.run_check(d,('--tracking',str(d/'trace.md')))[0],0)

    def test_main_resources_and_tracking_resources_are_both_checked(self):
        for target in ['prd.md','trace.md']:
            with self.subTest(target=target),tempfile.TemporaryDirectory() as folder:
                d=Path(folder);self.fixture(d);p=d/target;p.write_text(p.read_text()+'\n![缺图](missing.png)\n')
                code,report=self.run_check(d,('--tracking',str(d/'trace.md')))
                self.assertNotEqual(code,0)
                self.assertTrue(any('missing.png' in p for p in report['problems']),report)

    def test_source_allowlist_does_not_allow_external_tracking_or_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);d=root/'delivery';d.mkdir();sources=root/'sources';sources.mkdir();self.fixture(d)
            (sources/'fact.md').write_text('事实')
            p=d/'trace.md';p.write_text(p.read_text()+'\n[来源](../sources/fact.md)\n')
            flags=('--tracking',str(p))
            self.assertNotEqual(self.run_check(d,flags)[0],0)
            self.assertEqual(self.run_check(d,flags+('--source-root',str(sources)))[0],0)
            outside=sources/'trace.md';outside.write_text(TRACE);p.unlink();p.symlink_to(outside)
            self.assertNotEqual(self.run_check(d,flags+('--source-root',str(sources)))[0],0)

    def test_tracking_cannot_supply_missing_main_identity(self):
        mutations = [
            (MAIN.replace('> 产品版本：draft-1\n', ''),
             TRACE.replace('> 追踪版本：draft-1', '> 产品版本：draft-1')),
            (MAIN.replace('> 状态：草稿\n', ''), TRACE + '\n> 状态：草稿\n'),
            (MAIN.replace('# 报名餐食\n', ''), TRACE + '\n# 外部标题\n'),
        ]
        for main, trace in mutations:
            with self.subTest(main=main), tempfile.TemporaryDirectory() as folder:
                d=Path(folder);self.fixture(d)
                (d/'prd.md').write_text(main);(d/'trace.md').write_text(trace)
                self.assertNotEqual(self.run_check(d,('--tracking',str(d/'trace.md')))[0],0)

    def test_reference_definitions_are_checked_in_each_file(self):
        for destination in ['missing.md','../source/fact.md']:
            with self.subTest(destination=destination), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);d=root/'delivery';d.mkdir();self.fixture(d)
                (d/'good.md').write_text('存在的证据')
                (root/'source').mkdir();(root/'source/fact.md').write_text('范围外证据')
                (d/'prd.md').write_text(MAIN+'\n[主文证据][same]\n\n[same]: good.md\n')
                (d/'trace.md').write_text(TRACE+'\n[追踪证据][same]\n\n[same]: '+destination+'\n')
                code,report=self.run_check(d,('--tracking',str(d/'trace.md')))
                self.assertNotEqual(code,0,report)
                self.assertTrue(any(destination in p for p in report['problems']),report)

    def test_unclosed_main_markup_cannot_hide_tracking_duplicates(self):
        for opening in ['```text\n','<!--\n']:
            with self.subTest(opening=opening), tempfile.TemporaryDirectory() as folder:
                d=Path(folder);self.fixture(d)
                (d/'prd.md').write_text(MAIN+'\n'+TRACE+'\n'+opening)
                code,report=self.run_check(d,('--tracking',str(d/'trace.md')))
                self.assertNotEqual(code,0,report)
                self.assertTrue(any('重复标识' in p for p in report['problems']),report)

    def test_split_keeps_prototype_resource_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);d=root/'delivery';d.mkdir();self.fixture(d)
            outside=root/'source';outside.mkdir();(outside/'image.png').write_bytes(b'not a real image')
            prototype=d/'prototype.html';prototype.write_text('<meta name="product-version" content="draft-1"><img src="../source/image.png">')
            code,report=self.run_check(d,('--tracking',str(d/'trace.md'),'--prototype',str(prototype),'--source-root',str(outside)))
            self.assertNotEqual(code,0)
            self.assertTrue(any('超出' in p for p in report['problems']),report)

class SplitApprovalTests(unittest.TestCase):
    run_check = SplitProductTests.run_check
    def approved_pair(self, directory, version='draft-1'):
        directory.mkdir(parents=True, exist_ok=True)
        main=MAIN.replace('draft-1',version)
        trace=TRACE.replace('> 追踪版本：draft-1','> 追踪版本：'+version).replace(
            '状态：草稿','状态：已确认\n确认记录：业务负责人确认 draft-1。')
        # Backlinks and in-pair rule references are covered by the two explicit files.
        trace=trace.replace('见业务规则。','见[业务规则](prd.md#业务规则)。')
        (directory/'prd.md').write_text(main);(directory/'trace.md').write_text(trace)
        return directory/'prd.md',directory/'trace.md'

    def flags(self, current, *pairs):
        args=['--tracking',str(current/'trace.md')]
        for pair in pairs:args+=['--baseline',*[str(p) for p in pair]]
        return tuple(args)

    def test_split_version_only_and_multistep_inherit_original_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=self.approved_pair(root/'old');second=self.approved_pair(root/'second','draft-2');self.approved_pair(root/'current','draft-3')
            self.assertEqual(self.run_check(root/'old',('--tracking',str(old[1])))[0],0)
            code,report=self.run_check(root/'second',self.flags(root/'second',old));self.assertEqual(code,0,report)
            code,report=self.run_check(root/'current',self.flags(root/'current',old,second));self.assertEqual(code,0,report)
            self.assertNotEqual(self.run_check(root/'current',('--tracking',str(root/'current/trace.md')))[0],0)

    def test_split_changes_to_rule_ac_source_context_or_markup_require_reconfirmation(self):
        mutations=[('prd.md','每人一份','每人两份'),('trace.md','2人各1份，保存2份','2人各2份，保存4份'),
                   ('trace.md','本例为模拟口述','业务规则已经另行更改'),('prd.md','每人一份','**每人一份**'),
                   ('prd.md','## 业务规则','## 业务规则\n默认数量规则已改变。')]
        for name,before,after in mutations:
            with self.subTest(change=(before,after)),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);old=self.approved_pair(root/'old');self.approved_pair(root/'current','draft-2')
                p=root/'current'/name;p.write_text(p.read_text().replace(before,after))
                code,report=self.run_check(root/'current',self.flags(root/'current',old));self.assertNotEqual(code,0,report)
                self.assertTrue(any('已变更' in p for p in report['problems']),report)
                if name=='prd.md':
                    p=root/'current/trace.md';p.write_text(p.read_text().replace('业务负责人确认 draft-1。','业务负责人重新确认 draft-2。'))
                    code,report=self.run_check(root/'current',self.flags(root/'current',old));self.assertEqual(code,0,report)

    def test_split_unrelated_unconfirmed_requirement_change_keeps_other_approval(self):
        extra='\n### FR-02 备注\n状态：待确认\n依据：SRC-01\n原型：否\n备注不影响份数。\n#### AC-02 备注为空\n允许为空。\n'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=self.approved_pair(root/'old');self.approved_pair(root/'current','draft-2')
            for d in ['old','current']:
                p=root/d/'trace.md';p.write_text(p.read_text()+extra.replace('允许为空。','允许为空或短备注。') if d=='current' else p.read_text()+extra)
            code,report=self.run_check(root/'current',self.flags(root/'current',old));self.assertEqual(code,0,report)

    def test_split_old_external_or_other_file_references_are_not_auto_frozen(self):
        for target in ['https://example.invalid/rule','extra.md','image.png']:
            with self.subTest(target=target),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);old=self.approved_pair(root/'old');self.approved_pair(root/'current','draft-2')
                for d in ['old','current']:
                    (root/d/'extra.md').write_text('未冻结的其他规则');(root/d/'image.png').write_bytes(b'image')
                    p=root/d/'prd.md';p.write_text(p.read_text()+'\n[其他依据]('+target+')\n')
                code,report=self.run_check(root/'current',self.flags(root/'current',old));self.assertNotEqual(code,0,report)
                self.assertTrue(any('未冻结' in p for p in report['problems']),report)

    def test_split_invalid_baseline_pair_and_ambiguous_groups_are_rejected(self):
        for mode in ['missing','stale','unlinked','symlink','too_many']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);old=self.approved_pair(root/'old');self.approved_pair(root/'current','draft-2')
                if mode=='missing':old[1].unlink()
                if mode=='stale':old[1].write_text(old[1].read_text().replace('追踪版本：draft-1','追踪版本：draft-0'))
                if mode=='unlinked':old[0].write_text(old[0].read_text().replace('[验收追踪](trace.md)','另存追踪'))
                if mode=='symlink':
                    external=root/'outside.md';external.write_text(old[1].read_text());old[1].unlink();old[1].symlink_to(external)
                pair=(*old,old[0]) if mode=='too_many' else old
                code,report=self.run_check(root/'current',self.flags(root/'current',pair));self.assertNotEqual(code,0,report)

    def test_baseline_resources_use_local_and_explicit_source_boundaries(self):
        for split in (False, True):
            for target, allowed, expected in (
                ('source.md', False, 0), ('missing.md', False, 1),
                ('../outside.md', False, 1), ('../outside.md', True, 0),
                ('https://example.invalid/reference', False, 0),
            ):
                with self.subTest(split=split, target=target, allowed=allowed), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    old, current = root / 'old', root / 'current'
                    old.mkdir(); current.mkdir()
                    SplitProductTests.fixture(self, old)
                    SplitProductTests.fixture(self, current)
                    (old / 'source.md').write_text('冻结的模拟来源')
                    (root / 'outside.md').write_text('需显式允许的来源')
                    if split:
                        target_file = old / 'trace.md'
                        pair = (old / 'prd.md', target_file)
                    else:
                        target_file = old / 'prd.md'
                        target_file.write_text(MAIN + '\n' + TRACE)
                        pair = (target_file,)
                    target_file.write_text(target_file.read_text() + '\n[历史资料](' + target + ')\n')
                    extra = self.flags(current, pair)
                    if allowed: extra += ('--source-root', str(root))
                    code, report = self.run_check(current, extra)
                    self.assertEqual(code, expected, report)
                    if expected:
                        self.assertTrue(any('历史基线无效' in problem and '资源' in problem
                                            for problem in report['problems']), report)

    def test_old_baseline_without_trace_is_still_rejected_and_legacy_cli_remains(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=self.approved_pair(root/'old');self.approved_pair(root/'current','draft-2')
            self.assertNotEqual(self.run_check(root/'current',self.flags(root/'current',(old[0],)))[0],0)
            for name,version in [('old','draft-1'),('current','draft-2')]:
                p=root/name/'prd.md';p.write_text(MAIN.replace('draft-1',version).replace('[验收追踪](trace.md)','')+'\n'+TRACE.replace('[业务主文](prd.md)','').replace('追踪版本：draft-1','追踪版本：'+version))
            code,report=self.run_check(root/'current',('--baseline',str(old[0])));self.assertEqual(code,0,report)

if __name__=='__main__':unittest.main()
