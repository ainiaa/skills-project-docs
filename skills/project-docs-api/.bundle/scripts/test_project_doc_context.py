import json
import itertools
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import project_doc_context
from project_doc_context import _related_graph


SCRIPT = Path(__file__).with_name("project_doc_context.py")


class ProjectDocContextTests(unittest.TestCase):
    def test_graph_focus_is_one_hop_regardless_of_edge_order(self):
        graph = {"nodes": [{"id": name, "filePath": name + ".py"} for name in "ABCDE"],
                 "edges": [{"source": "A", "target": "B"}, {"source": "B", "target": "C"},
                           {"source": "D", "target": "A"}, {"source": "A", "target": "A"},
                           {"source": "C", "target": "E"}]}
        for edges in itertools.permutations(graph["edges"]):
            with self.subTest(edges=edges):
                nodes, related = _related_graph(dict(graph, edges=edges), {"A.py"}, [])
                self.assertEqual({node["id"] for node in nodes}, {"A", "B", "D"})
                self.assertEqual({(edge["source"], edge["target"]) for edge in related},
                                 {("A", "B"), ("D", "A"), ("A", "A")})

    def test_graph_focus_handles_no_matches_and_text_matches(self):
        graph = {"nodes": [{"id": "A", "name": "Refund"}, {"id": "B", "summary": "Approve"}],
                 "edges": [{"source": "B", "target": "A"}]}
        self.assertEqual(_related_graph(graph, set(), ["absent"]), ([], []))
        nodes, edges = _related_graph(graph, set(), ["refund"])
        self.assertEqual({node["id"] for node in nodes}, {"A", "B"})
        self.assertEqual(edges, graph["edges"])

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "src"
        source.mkdir()
        (source / "OrderController.java").write_text("class OrderController {}\n", encoding="utf-8")
        (source / "RefundController.java").write_text("class RefundController {}\n", encoding="utf-8")

    def run_context(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--source", str(self.root), *args],
                                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_focus_keeps_related_facts_and_reports_total(self):
        code, result = self.run_context("--focus", "Refund")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["matchedFiles"], ["src/RefundController.java"])
        self.assertEqual(result["totalFiles"], 2)
        self.assertTrue(any(item["name"] == "RefundController" for item in result["symbols"]))
        self.assertFalse(any(item["name"] == "OrderController" for item in result["symbols"]))

    def test_multiple_topics_share_one_source_scan(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', [str(SCRIPT), '--source', str(self.root),
                                       '--focus', 'Order', '--focus', 'Refund']), \
                patch.object(project_doc_context, 'build_context', wraps=project_doc_context.build_context) as scan, \
                contextlib.redirect_stdout(output):
            project_doc_context.main()
        scan.assert_called_once_with(self.root)
        result = json.loads(output.getvalue())
        self.assertEqual(result['matchedFiles'], ['src/OrderController.java', 'src/RefundController.java'])
        self.assertEqual(result['focus'], ['Order', 'Refund'])
        self.assertEqual({symbol['name'] for symbol in result['symbols']}, {'OrderController', 'RefundController'})

    def test_partial_topic_matches_still_require_broader_search(self):
        code, result = self.run_context('--focus', 'Order', '--focus', 'AbsentTopic')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['matchedFiles'], ['src/OrderController.java'])
        self.assertTrue(result['needsBroaderSearch'])
        self.assertTrue(any('AbsentTopic' in warning for warning in result['warnings']))

    def test_topic_matches_use_symbols_routes_config_and_tables(self):
        context = dict(project='sample', gitCommitHash='', files=['a.py', 'b.py'], warnings=[],
                       symbols=[dict(name='RefundService', path='a.py')],
                       routes=[dict(value='/orders', path='a.py')],
                       configKeys=[dict(key='redis.host', path='b.py')],
                       tables=[dict(name='payment_record', path='b.py')])
        for focus in (['REFUND', '/orders', 'redis', 'payment'], ['refund', 'absent'], []):
            with self.subTest(focus=focus):
                result = project_doc_context.focused_context(context, focus)
                self.assertEqual(result['needsBroaderSearch'], 'absent' in focus or not focus)
                self.assertEqual(result['matchedFiles'], ['a.py', 'b.py'] if len(focus) == 4 else ['a.py'] if focus else [])
        self.assertEqual(context['warnings'], [])


    def test_fresh_graph_adds_related_domain_flow_but_stale_graph_does_not(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "src"], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "init"], check=True)
        commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()
        ua = self.root / ".ua"
        ua.mkdir()
        graph = {"project": {"gitCommitHash": commit}, "nodes": [
            {"id": "flow:refund", "type": "flow", "name": "Refund flow", "filePath": "src/RefundController.java"},
            {"id": "step:approve", "type": "step", "name": "Approve refund"}],
            "edges": [{"source": "flow:refund", "target": "step:approve", "type": "flow_step"}]}
        (ua / "domain-graph.json").write_text(json.dumps(graph), encoding="utf-8")
        (ua / "knowledge-graph.json").write_text(json.dumps({
            "project": {"gitCommitHash": commit},
            "nodes": [{"id": "file:refund", "type": "file", "name": "RefundController", "filePath": "src/RefundController.java"}],
            "edges": [],
            "layers": [{"id": "api", "name": "API", "nodeIds": ["file:refund"]}],
            "tour": [{"order": 1, "title": "Read refund entry", "nodeIds": ["file:refund"]}],
        }), encoding="utf-8")
        _, fresh = self.run_context("--focus", "Refund")
        self.assertEqual(len(fresh["domainNodes"]), 2)
        self.assertEqual(fresh["graphTour"][0]["title"], "Read refund entry")
        self.assertEqual(fresh["graphLayers"][0]["name"], "API")
        (self.root / "src" / "RefundController.java").write_text("class ChangedRefundController {}\n", encoding="utf-8")
        _, stale = self.run_context("--focus", "Refund")
        self.assertEqual(stale["domainNodes"], [])
        self.assertEqual(stale["graphTour"], [])
        self.assertTrue(any("stale" in warning for warning in stale["warnings"]))


if __name__ == "__main__":
    unittest.main()
