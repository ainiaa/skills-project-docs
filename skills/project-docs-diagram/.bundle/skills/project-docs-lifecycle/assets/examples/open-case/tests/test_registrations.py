"""CLI acceptance tests for SIM-REG-001. 作者：Jeff.Liu"""
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app/legacy_export.py'
FIELDS = ['record_id', 'employee_id', 'session_id', 'status', 'source']


def row(record='R1', employee='E01', session='S1', status='confirmed', source='web'):
    return dict(zip(FIELDS, [record, employee, session, status, source]))


def table(rows, fields=FIELDS):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='case-test-', dir=ROOT / 'tests')
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.sequence = 0

    def invoke_file(self, path, session='S1'):
        before = path.read_bytes() if path.exists() else None
        process = subprocess.run(
            [sys.executable, str(APP), '--input', str(path), '--session', session],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        )
        if before is not None:
            self.assertEqual(path.read_bytes(), before, 'CLI must never alter its input snapshot')
        return process

    def invoke(self, content, session='S1'):
        self.sequence += 1
        path = self.work / f'input-{self.sequence}.csv'
        path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
        return self.invoke_file(path, session)

    def success(self, process):
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, '')
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError:
            self.fail(f'Expected one JSON result, got: {process.stdout!r}')
        self.assertIsInstance(result, dict)
        return result

    def expected(self, count, pending=(), session='S1', no_records=False):
        return {'session': session, 'count': count, 'pending_records': list(pending),
                'has_pending': bool(pending),
                'notice': '有待核实' if pending else '无该场次记录' if no_records else '本快照无待核实'}

    def rejected(self, process, detail):
        self.assertNotEqual(process.returncode, 0, 'invalid input must fail, never return usable count')
        self.assertEqual(process.stdout, '', 'failure must not emit count JSON')
        self.assertTrue(process.stderr.strip())
        self.assertIn(detail, process.stderr)

    def test_sample_s1_snapshot_and_pending_source(self):
        result = self.success(self.invoke_file(ROOT / 'sources/registrations.csv'))
        self.assertEqual(result.get('count'), 3, 'S1 must exclude duplicate, cancelled, and unknown identity')
        pending = {**row('R7', '', source='spreadsheet'), 'reason': 'missing_employee_id'}
        self.assertEqual(result, self.expected(3, [pending]))

    def test_sample_s2_is_independent(self):
        result = self.success(self.invoke_file(ROOT / 'sources/registrations.csv', 'S2'))
        self.assertEqual(result, self.expected(1, session='S2'))

    def test_duplicate_cross_session_and_row_order(self):
        rows = [row('R1'), row('R2', source='spreadsheet'), row('R4', session='S2')]
        for records in (rows, list(reversed(rows))):
            for session in ('S1', 'S2'):
                with self.subTest(session=session, reversed=records != rows):
                    result = self.success(self.invoke(table(records), session))
                    self.assertEqual(result.get('count'), 1)
                    self.assertEqual(result, self.expected(1, session=session))

    def test_conflict_group_isolated_before_cancel_filter(self):
        rows = [row('C1'), row('C2', status='cancelled', source='spreadsheet'),
                row('V1', employee='E02'), row('X1', session='S2'),
                row('Z1', employee='E03', status='cancelled')]
        for records in (rows, list(reversed(rows))):
            result = self.success(self.invoke(table(records)))
            self.assertEqual(result.get('count'), 1, 'conflict contributes zero, E02 contributes one')
            expected = [{**r, 'reason': 'status_conflict'} for r in records if r['record_id'] in ('C1', 'C2')]
            self.assertEqual(result, self.expected(1, expected))
            self.assertEqual(self.success(self.invoke(table(records), 'S2')), self.expected(1, session='S2'))

    def test_all_cancelled_contributes_zero(self):
        rows = [row('C1', status='cancelled'), row('C2', status='cancelled')]
        self.assertEqual(self.success(self.invoke(table(rows))), self.expected(0))

    def test_missing_employee_rows_are_not_merged(self):
        rows = [row('M1', ''), row('M2', '', source='spreadsheet')]
        pending = [{**r, 'reason': 'missing_employee_id'} for r in rows]
        result = self.success(self.invoke(table(rows)))
        self.assertEqual(result.get('count'), 0)
        self.assertEqual(result, self.expected(0, pending))

    def test_header_only_and_absent_session(self):
        for content in (table([]), table([row(session='S2')])):
            with self.subTest(content=content):
                self.assertEqual(self.success(self.invoke(content)), self.expected(0, no_records=True))

    def test_missing_file_reports_failure_without_count(self):
        self.rejected(self.invoke_file(self.work / 'absent.csv'), 'absent.csv')

    def test_missing_columns_and_empty_critical_fields(self):
        for field in FIELDS:
            fields = [name for name in FIELDS if name != field]
            with self.subTest(missing_column=field):
                self.rejected(self.invoke(table([{k: v for k, v in row().items() if k != field}], fields)), field)
        for field in ('record_id', 'session_id', 'status', 'source'):
            record = row()
            record[field] = ''
            with self.subTest(empty_field=field):
                self.rejected(self.invoke(table([record])), field)

    def test_invalid_status_in_other_session_invalidates_snapshot(self):
        rows = [row(), row('BAD', employee='E09', session='S2', status='waiting')]
        self.rejected(self.invoke(table(rows)), 'status')

    def test_malformed_csv_and_invalid_encoding(self):
        header = ','.join(FIELDS) + '\n'
        for content in (header + 'R1,E01,S1,confirmed,web,EXTRA\n',
                        header + 'R1,E01,S1,confirmed\n',
                        header + 'R1,E01,S1,confirmed,"unterminated\n',
                        header.encode() + b'R1,E01,S1,confirmed,\xff\n',
                        b''):
            with self.subTest(content=repr(content)):
                process = self.invoke(content)
                self.rejected(process, 'input')

    def test_extra_columns_are_ignored_without_changing_source(self):
        records = [{**row(), 'comment': 'preserve this source-only value'}]
        result = self.success(self.invoke(table(records, FIELDS + ['comment'])))
        self.assertEqual(result, self.expected(1))

    def test_employee_identity_is_opaque(self):
        records = [row(), row('R2', employee='e01'), row('R3', employee=' E01')]
        self.assertEqual(self.success(self.invoke(table(records))), self.expected(3))

    def test_whitespace_employee_ids_preserve_raw_pending_rows(self):
        rows = [row('W1', '   '), row('W2', '\t ', source='spreadsheet')]
        result = self.success(self.invoke(table(rows)))
        self.assertEqual(result.get('count'), 0, 'whitespace-only is missing identity')
        pending = [{**r, 'reason': 'missing_employee_id'} for r in rows]
        self.assertEqual(result, self.expected(0, pending))

    def test_whitespace_critical_fields_fail_without_count(self):
        for field in ('record_id', 'session_id', 'source'):
            record = row()
            record[field] = ' \t '
            with self.subTest(field=field):
                self.rejected(self.invoke(table([record])), field)

    def test_duplicate_header_is_rejected(self):
        content = ','.join(FIELDS + ['source']) + '\nR1,E01,S1,confirmed,web,spreadsheet\n'
        self.rejected(self.invoke(content), 'duplicate columns')

    def test_reconciled_new_snapshot_retains_old_snapshot_and_result(self):
        path = ROOT / 'sources/registrations.csv'
        original = path.read_bytes()
        first_process = self.invoke_file(path)
        first = self.success(first_process)
        self.assertEqual(first.get('count'), 3)
        rows = list(csv.DictReader(io.StringIO(original.decode('utf-8'))))
        for record in rows:
            if record['record_id'] == 'R7':
                record['employee_id'] = 'E05'
        corrected = self.work / 'corrected.csv'
        corrected.write_text(table(rows), encoding='utf-8', newline='')
        self.assertEqual(self.success(self.invoke_file(corrected)), self.expected(4))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.success(self.invoke_file(path)), first)
        retained = self.work / 'original-result.json'
        retained.write_text(first_process.stdout, encoding='utf-8')
        self.assertEqual(json.loads(retained.read_text()), first)


if __name__ == '__main__':
    unittest.main()
