"""Default discovery must not grant permission to start desktop renderers."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
DESKTOP_CASES = {
    "test_architecture": ("ArchitectureTests", ["test_official_diagram_engines_accept_generated_outputs"]),
    "test_architecture_delivery": ("ArchitectureDeliveryTest", [
        "test_deliver_renders_overview_and_every_detail", "test_failed_replacement_preserves_last_complete_bundle"]),
    "test_diagram_profiles": ("DiagramProfilesTest", ["test_supported_profiles_parse_in_official_engines"]),
    "test_native_diagrams": ("NativeDiagramTest", ["test_official_drawio_freeform_diagram_native_export"]),
}


class DesktopTestPolicyTests(unittest.TestCase):
    def methods(self, opt_in):
        environment = {f"{name}_OFFICIAL_CLI": "/fixture/renderer" for name in ("MERMAID", "PLANTUML", "DRAWIO")}
        environment["PROJECT_DOCS_DESKTOP_TESTS"] = opt_in
        with patch.dict(os.environ, environment), patch("shutil.which", return_value="/fixture/renderer"):
            for module_name, (class_name, methods) in DESKTOP_CASES.items():
                spec = importlib.util.spec_from_file_location("desktop_policy_" + module_name, ROOT / (module_name + ".py"))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for method in methods:
                    yield module_name + "." + method, getattr(getattr(module, class_name), method)

    def test_installed_or_configured_renderer_does_not_enable_desktop_tests(self):
        for value in ("", "0", "true"):
            for name, method in self.methods(value):
                with self.subTest(value=value, method=name):
                    self.assertTrue(getattr(method, "__unittest_skip__", False), name)

    def test_explicit_opt_in_keeps_desktop_acceptance_available(self):
        for name, method in self.methods("1"):
            with self.subTest(method=name):
                self.assertFalse(getattr(method, "__unittest_skip__", False), name)

    def test_ordinary_cli_regression_does_not_call_discovered_desktop_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            called = directory / "desktop-called"
            cli = directory / "drawio"
            cli.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(called)!r}).touch()\nraise SystemExit(99)\n")
            cli.chmod(0o755)
            environment = dict(os.environ, DRAWIO_OFFICIAL_CLI=str(cli),
                               PATH=str(directory) + os.pathsep + os.environ.get("PATH", ""), PROJECT_DOCS_DESKTOP_TESTS="")
            result = subprocess.run([sys.executable, "-m", "unittest",
                                     "test_diagram_profiles.DiagramProfilesTest.test_cli_validates_and_renders_v2_without_changing_v1_contract"],
                                    cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30)
            self.assertFalse(called.exists(), "ordinary tests invoked the discovered desktop renderer")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
