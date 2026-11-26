"""Count canonical production sources once, while testing packaged copies separately."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless((ROOT / '.coveragerc').is_file() and importlib.util.find_spec('coverage'),
                     'source checkout and coverage runtime required')
class CoverageScopeTests(unittest.TestCase):
    def test_source_is_measured_and_identical_installed_copy_is_not_counted_again(self):
        source = ROOT / 'scripts/product_dependencies.py'
        snapshot = ROOT / 'skills/project-docs/.bundle/scripts/product_dependencies.py'
        self.assertEqual(source.read_bytes(), snapshot.read_bytes())
        code = ('import coverage,json,runpy,sys;'
                'c=coverage.Coverage(config_file=sys.argv[1],data_file=None);c.start();'
                'runpy.run_path(sys.argv[2]);runpy.run_path(sys.argv[3]);c.stop();'
                'print(json.dumps(sorted(c.get_data().measured_files())))')
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('COV_CORE', 'COVERAGE', 'PYTEST'))}
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / '.coveragerc'),
                                 str(source), str(snapshot)], env=env, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        measured = json.loads(result.stdout)
        self.assertIn(str(source), measured)
        self.assertNotIn(str(snapshot), measured)


@unittest.skipUnless((ROOT / '.github/workflows/product-acceptance.yml').is_file(), 'source workflow required')
class WorkflowCoverageTests(unittest.TestCase):
    def test_product_ci_launches_mermaid_with_runner_browser_config(self):
        import tempfile
        import textwrap

        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        section = workflow.split('name: Reuse the existing Mermaid browser runtime\n', 1)[1]
        step = section.split('      - name:', 1)[0]
        command = textwrap.dedent(step.partition('run:')[2].removeprefix(' |').lstrip('\n'))
        with tempfile.TemporaryDirectory(prefix='mermaid ci ') as temporary:
            root = Path(temporary)
            mmdc = root / 'bin' / 'mmdc'
            mmdc.parent.mkdir()
            mmdc.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            mmdc.chmod(0o755)
            wrapper = root / 'mmdc-product'
            env_file = root / 'env'
            env = dict(os.environ, RUNNER_TEMP=str(root), UNDERSTAND_RENDERER_HOME=str(root),
                       GITHUB_ENV=str(env_file))
            env.pop('MERMAID_OFFICIAL_CLI', None)
            result = subprocess.run(['bash', '-e', '-c', 'python3() { :; }\n' + command],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_file.read_text().splitlines(), [f'MERMAID_OFFICIAL_CLI={wrapper}'])
            self.assertTrue(wrapper.is_file())
            result = subprocess.run([str(wrapper), '-i', 'input file.mmd'],
                                    capture_output=True, text=True, check=True, timeout=10)
            flag, config, *args = result.stdout.splitlines()
            self.assertEqual(flag, '--puppeteerConfigFile')
            self.assertEqual(args, ['-i', 'input file.mmd'])
            self.assertEqual(json.loads(Path(config).read_text()), {'args': ['--no-sandbox']})

    def test_browser_and_release_specialties_have_shared_commands(self):
        commands = dict(line.split(': ', 1) for line in
                        (ROOT / 'docs/00_standards/test-commands.yml').read_text().splitlines()
                        if line and not line.startswith('#'))
        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        self.assertEqual(commands.get('browser_doctor'), 'node scripts/product_browser.mjs --doctor')
        self.assertEqual(commands.get('browser'), 'node --test scripts/test_product_browser.mjs')
        self.assertTrue(commands.get('release_specialties', '').startswith('env PYTHONPATH=scripts python3 -m unittest '))
        for key in ('browser_doctor', 'browser', 'release_specialties'):
            self.assertIn(commands[key], workflow)
        for module in ('test_install.py', 'test_update.py'):
            self.assertNotIn('python3 -m unittest discover -s scripts -p ' + module, workflow)
        for module in ('test_install', 'test_update', 'test_product_npx_installer',
                       'test_native_diagrams', 'test_archify_native_types', 'test_generate_api_docs'):
            self.assertIn('scripts.' + module, commands['release_specialties'])
        self.assertLess(workflow.index(commands['browser_doctor']), workflow.index('python3 -m pytest '))

    def test_workflow_runs_the_canonical_coverage_command(self):
        import shlex
        canonical = next(line.partition(':')[2].strip() for line in
                         (ROOT / 'docs/00_standards/test-commands.yml').read_text().splitlines()
                         if line.startswith('coverage:'))
        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        commands = [line.strip() for line in workflow.splitlines() if 'python3 -m pytest ' in line]
        self.assertEqual([shlex.split(line) for line in commands], [shlex.split(canonical)])
        self.assertNotIn('four Product modules', workflow)
        self.assertIn('python3 -m unittest discover -s scripts -p test_coverage_scope.py', workflow)

    def test_required_workflow_is_independent_and_integration_is_manual(self):
        workflow = (ROOT / '.github/workflows/product-acceptance.yml').read_text()
        for dependency in ('PROJECT_DOCS_CONVERGE_TEST_ROOT', 'PROJECT_DOCS_CONVERGE_REF',
                           'skills-convergent-delivery', 'test_suite_upgrade'):
            self.assertNotIn(dependency, workflow)
        integration = (ROOT / '.github/workflows/converge-integration.yml').read_text()
        self.assertIn('workflow_dispatch:', integration)
        self.assertNotIn('  push:', integration)
        self.assertNotIn('  pull_request:', integration)
        self.assertIn('fetch-depth: 0', integration)
        self.assertIn('test_suite_upgrade.py', integration)
        for capability in ('adopt', 'revise', 'iterate'):
            self.assertIn('--capability ' + capability, integration)
        self.assertLess(integration.index('--check-provider'), integration.index('python3 -m pytest '))

    @unittest.skipUnless(importlib.util.find_spec('coverage'), 'coverage runtime required')
    def test_coverage_threshold_does_not_round_89_78_to_90(self):
        from coverage import Coverage
        from coverage.results import should_fail_under
        config = Coverage(config_file=str(ROOT / '.coveragerc'))
        precision = config.get_option('report:precision')
        self.assertTrue(should_fail_under(89.78, 90, precision))
        self.assertFalse(should_fail_under(90, 90, precision))

    def test_provider_revision_guard_accepts_only_full_commit_ids(self):
        import re
        import textwrap
        workflow = (ROOT / '.github/workflows/converge-integration.yml').read_text()
        section = workflow.split('name: Require a pinned Converge acceptance revision', 1)[1]
        shell = textwrap.dedent(section.split('run: |\n', 1)[1].split('      - uses:', 1)[0])
        syntax = subprocess.run(['bash', '-n'], input=shell, text=True, capture_output=True)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        for ref in ('', 'main', 'a' * 39, 'A' * 40, 'a' * 40):
            with self.subTest(ref=ref):
                result = subprocess.run(['bash', '-c', shell], env=dict(os.environ, CONVERGE_REF=ref),
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0 if re.fullmatch('[0-9a-f]{40}', ref) else 1)


if __name__ == '__main__':
    unittest.main()
