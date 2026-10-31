"""Collect real unittest outcomes bound to one FR/AC contract. 作者：Jeff.Liu"""
import argparse
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

if __name__ == '__main__':
    sys.dont_write_bytecode = True
    # -B prevents writes, but an empty prefix also prevents stale cache reads.
    _import_cache = tempfile.TemporaryDirectory(prefix='lifecycle-imports-')
    sys.pycache_prefix = _import_cache.name

from lifecycle_quality import check_trace, fingerprint, local_file, reference, runner_identity


def run_tests(root, tests, trace_path, output):
    root = Path(root).resolve()
    tests = (root / tests).resolve()
    if not tests.is_relative_to(root) or not tests.is_dir():
        raise ValueError('test directory must be inside root')
    output = Path(output).resolve()
    if not output.is_relative_to(root) or output.exists():
        raise ValueError('execution output must be a new file inside root')
    trace = json.loads(local_file(root, trace_path).read_text())
    planned = check_trace(trace, None, root)
    if not planned['valid']:
        raise ValueError(str(planned['errors']))
    before = fingerprint(trace)
    runner_before = runner_identity()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(tests))
    sys.dont_write_bytecode = True

    class Result(unittest.TextTestResult):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.observed, self.started = {}, {}

        def startTest(self, test):
            super().startTest(test)
            self.started[test.id()] = self.started.get(test.id(), 0) + 1

        def outcome(self, test, status):
            source = Path(inspect.getfile(type(test))).resolve()
            ref = reference(root, str(source.relative_to(root))) if source.is_relative_to(root) else None
            previous = self.observed.get(test.id())
            if previous is None or status != 'passed':
                self.observed[test.id()] = {'id': test.id(), 'status': status, 'source': ref}
            try:
                method = inspect.unwrap(getattr(test, test._testMethodName))
                implementation = Path(inspect.getfile(method)).resolve()
            except (AttributeError, TypeError, ValueError):
                implementation = None
            if implementation != source:
                self.observed[test.id()]['binding_error'] = 'Test implementation is outside the bound class file; use project test evidence.'

        def addSuccess(self, test):
            super().addSuccess(test); self.outcome(test, 'passed')

        def addFailure(self, test, error):
            super().addFailure(test, error); self.outcome(test, 'failed')

        def addError(self, test, error):
            super().addError(test, error); self.outcome(test, 'error')

        def addSkip(self, test, reason):
            super().addSkip(test, reason); self.outcome(test, 'skipped')

        def addExpectedFailure(self, test, error):
            super().addExpectedFailure(test, error); self.outcome(test, 'expected_failure')

        def addUnexpectedSuccess(self, test):
            super().addUnexpectedSuccess(test); self.outcome(test, 'unexpected_success')

        def addSubTest(self, test, subtest, error):
            super().addSubTest(test, subtest, error)
            if error is not None:
                self.outcome(test, 'failed' if issubclass(error[0], test.failureException) else 'error')

    suite = unittest.defaultTestLoader.discover(str(tests), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    try:
        fresh = (check_trace(trace, None, root)['valid']
                 and fingerprint(json.loads(local_file(root, trace_path).read_text())) == before
                 and runner_identity() == runner_before)
    except (ValueError, OSError):
        fresh = False
    receipt = {'schema_version': 1, 'trace_sha256': before, 'runner_sha256': runner_before,
               'build': trace['build']['sha256'], 'environment': trace['environment'], 'scope': trace['scope'],
               'at': datetime.now(timezone.utc).isoformat(), 'exit_code': 0 if result.wasSuccessful() and result.testsRun else 1,
               'cases': list(result.observed.values()), 'duplicate_cases': [key for key, count in result.started.items() if count > 1],
               'source_unchanged': fresh, 'tests_run': result.testsRun}
    if not check_trace(trace, receipt, root)['ready']:
        receipt['exit_code'] = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as target:
        json.dump(receipt, target, ensure_ascii=False, indent=2)
        target.write('\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--tests', default='.')
    parser.add_argument('--trace', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = run_tests(args.root, args.tests, args.trace, args.output)
    except (ValueError, OSError) as error:
        print(json.dumps({'ready': False, 'error': str(error)}))
        return 1
    print(json.dumps({'tests_run': receipt['tests_run'], 'exit_code': receipt['exit_code']}))
    return receipt['exit_code']


if __name__ == '__main__':
    with _import_cache:
        raise SystemExit(main())
