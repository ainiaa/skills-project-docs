"""Read-only snapshot summary for SIM-REG-001. 作者：Jeff.Liu"""
import argparse
import csv
import json
import sys

FIELDS = ('record_id', 'employee_id', 'session_id', 'status', 'source')


def summarize(rows, session):
    groups = {}
    selected = []
    for number, row in enumerate(rows, start=2):
        for field in FIELDS:
            if field not in row or row[field] is None or (field != 'employee_id' and not row[field].strip()):
                raise ValueError(f'row {number}: missing {field}')
        if row['status'] not in ('confirmed', 'cancelled'):
            raise ValueError(f'row {number}: invalid status')
        if row['session_id'] == session:
            selected.append(row)
            if row['employee_id'].strip():
                groups.setdefault(row['employee_id'], []).append(row)

    conflicts = {employee for employee, records in groups.items()
                 if {row['status'] for row in records} == {'confirmed', 'cancelled'}}
    count = sum(employee not in conflicts and any(row['status'] == 'confirmed' for row in records)
                for employee, records in groups.items())
    pending = []
    for row in selected:
        reason = ('missing_employee_id' if not row['employee_id'].strip() else
                  'status_conflict' if row['employee_id'] in conflicts else None)
        if reason:
            pending.append({**{field: row[field] for field in FIELDS}, 'reason': reason})
    return {'session': session, 'count': count, 'pending_records': pending,
            'has_pending': bool(pending),
            'notice': '有待核实' if pending else '无该场次记录' if not selected else '本快照无待核实'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    try:
        with open(args.input, encoding='utf-8', newline='') as source:
            reader = csv.DictReader(source, strict=True)
            names = reader.fieldnames or []
            missing = [field for field in FIELDS if field not in names]
            if missing:
                raise ValueError('missing columns: ' + ', '.join(missing))
            if len(names) != len(set(names)):
                raise ValueError('duplicate columns')
            rows = list(reader)
            if any(None in row or any(value is None for value in row.values()) for row in rows):
                raise ValueError('CSV row width differs from header')
            result = summarize(rows, args.session)
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f'input error: {error}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
