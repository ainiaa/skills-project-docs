"""Frozen existing behavior for the synthetic investigation. 作者：Jeff.Liu"""
import argparse
import csv
import json


def summarize(rows, session):
    return {'session': session, 'count': sum(row['session_id'] == session for row in rows)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    with open(args.input, encoding='utf-8', newline='') as source:
        print(json.dumps(summarize(list(csv.DictReader(source)), args.session)))
