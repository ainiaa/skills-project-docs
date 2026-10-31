"""Local lifecycle consistency and single-writer update regressions."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifecycle_record import check_record, update_record

ROOT = Path(__file__).resolve().parents[1]


def record():
    def node(identity, stage, dependencies):
        return {"id": identity, "kind": "artifact", "stage": stage, "branch": "feature",
                "version": 1, "owner": "test-owner", "source": "fixture/" + identity,
                "status": "completed", "depends_on": [{"id": d, "version": 1} for d in dependencies],
                "evidence": [{"kind": "executed", "source": "fixture/log", "actor": "test-runner",
                              "at": "2026-10-31T10:00:00+08:00", "result": "passed",
                              "subject": {"id": identity, "version": 1}}]}
    return {"schema_version": 1, "revision": 1, "project_ref": "existing-project",
            "subject_ref": "existing-FR-42", "goal": "Track an exception",
            "owner": "test-owner", "updated_at": "2026-10-31T10:00:00+08:00",
            "next_actions": [], "assertions": [],
            "branches": [{"id": "feature", "route": "development", "required": ["issue", "requirement", "test"]}],
            "artifacts": [node("issue", "L0", []), node("requirement", "L3", ["issue"]),
                          node("test", "L6", ["requirement"])]}


class RecordTests(unittest.TestCase):
    def test_equivalent_time_representations_cannot_rebind_an_observation(self):
        instants = [('2026-10-31T10:00:00+08:00', '2026-10-31T02:00:00Z'),
                    ('2026-10-31T00:00:00+08:00', '2026-10-30T16:00:00+00:00'),
                    ('2026-10-31T10:00:00.100000+08:00', '2026-10-31T02:00:00.1Z'),
                    ('2026-10-31T10:00:00.100000100+08:00', '2026-10-31T02:00:00.1000001Z'),
                    ('2026-10-31T02:00:00+00:00:00.0000001', '2026-10-31T01:59:59.9999999Z')]
        for before_at, after_at in instants:
            with self.subTest(before_at=before_at), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'record.json'
                original = record()
                original['artifacts'] = original['artifacts'][:1]
                original['branches'][0].update(route='guidance', required=['issue'])
                original['artifacts'][0]['evidence'][0].update(at=before_at, result='failed')
                path.write_text(json.dumps(original))
                candidate = copy.deepcopy(original)
                candidate['revision'] = 2
                node = candidate['artifacts'][0]
                node['version'] = 2
                node['evidence'][0].update(at=after_at, result='passed', subject={'id': 'issue', 'version': 2})
                with self.assertRaises(ValueError):
                    update_record(path, candidate, 1)
                self.assertEqual(json.loads(path.read_text()), original)
                self.assertFalse(path.with_name('record.json.rev-1.json').exists())
                self.assertFalse(path.with_name('record.json.lock').exists())

    def test_a_later_execution_in_another_offset_remains_a_new_observation(self):
        for later_at in ('2026-10-31T02:00:01Z', '2026-10-31T02:00:00.0000001Z'):
            with self.subTest(later_at=later_at), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'record.json'
                original = record()
                original['artifacts'] = original['artifacts'][:1]
                original['branches'][0].update(route='guidance', required=['issue'])
                original['artifacts'][0]['evidence'][0]['result'] = 'failed'
                path.write_text(json.dumps(original))
                candidate = copy.deepcopy(original)
                candidate['revision'] = 2
                node = candidate['artifacts'][0]
                node['version'] = 2
                node['evidence'][0].update(at=later_at, result='passed',
                                           subject={'id': 'issue', 'version': 2})
                update_record(path, candidate, 1)
                self.assertEqual(check_record(json.loads(path.read_text()))['needs_review'], [])
                self.assertEqual(json.loads(path.with_name('record.json.rev-1.json').read_text()), original)

    def test_history_validation_is_local_to_this_filename_and_record(self):
        for mode in ('valid', 'broken', 'foreign', 'revision_conflict'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'record[local].json'
                current = record()
                current['revision'] = 2
                path.write_text(json.dumps(current))
                historical = dict(current, revision=1)
                if mode == 'foreign':
                    historical = dict(historical, project_ref='another-project')
                elif mode == 'revision_conflict':
                    historical = dict(historical, revision=3)
                history = path.with_name(path.name + '.rev-1.json')
                history.write_text('{' if mode == 'broken' else json.dumps(historical))
                # Unrelated names and future revisions are not predecessor snapshots.
                (path.parent / 'recordl.json.rev-1.json').write_text('{')
                path.with_name(path.name + '.rev-20.json').write_text('{')
                before = path.read_bytes()
                candidate = dict(current, revision=3, owner='new-owner')
                if mode == 'valid':
                    update_record(path, candidate, 2)
                    self.assertEqual(json.loads(path.read_text()), candidate)
                else:
                    with self.assertRaises(ValueError):
                        update_record(path, candidate, 2)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertFalse(path.with_name(path.name + '.rev-2.json').exists())
                self.assertFalse(path.with_name(path.name + '.lock').exists())

    def test_intermediate_save_does_not_allow_rebinding_historical_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            original = record()
            original['artifacts'] = original['artifacts'][:1]
            original['branches'][0].update(route='guidance', required=['issue'])
            original['artifacts'][0]['evidence'][0]['result'] = 'failed'
            path.write_text(json.dumps(original))
            working = copy.deepcopy(original)
            working['revision'] = 2
            working['artifacts'][0].update(version=2, source='fixture/issue-v2', status='in_progress', evidence=[])
            update_record(path, working, 1)
            before = path.read_bytes()
            history = path.with_name('record.json.rev-1.json')
            frozen = history.read_bytes()
            candidate = copy.deepcopy(working)
            candidate['revision'] = 3
            old = copy.deepcopy(original['artifacts'][0]['evidence'][0])
            old.update(subject={'id': 'issue', 'version': 2}, result='passed')
            candidate['artifacts'][0].update(status='completed', evidence=[old])
            with self.assertRaises(ValueError):
                update_record(path, candidate, 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(history.read_bytes(), frozen)
            self.assertFalse(path.with_name('record.json.rev-2.json').exists())
            old.update(source='fixture/new-run', at='2026-10-31T12:00:00+08:00')
            update_record(path, candidate, 2)
            self.assertEqual(check_record(json.loads(path.read_text()))['branches']['feature'], 'recorded')
            self.assertEqual(history.read_bytes(), frozen)

    def test_planned_unknown_is_not_a_failed_execution_or_completion_proof(self):
        data = record()
        data['artifacts'] = data['artifacts'][:1]
        data['branches'][0].update(route='guidance', required=['issue'])
        node = data['artifacts'][0]
        actual = copy.deepcopy(node['evidence'][0])
        plan = dict(actual, kind='planned', source='fixture/plan', result='unknown')
        node.update(status='in_progress', evidence=[plan])
        self.assertEqual(check_record(data)['branches']['feature'], 'incomplete')
        node['status'] = 'completed'
        self.assertTrue(check_record(data)['needs_review'], 'A plan cannot prove completion')
        node['status'] = 'in_progress'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps(data))
            completed = copy.deepcopy(data)
            completed['revision'] = 2
            completed['artifacts'][0].update(status='completed', evidence=[plan, actual])
            update_record(path, completed, 1)
            self.assertEqual(check_record(completed)['needs_review'], [])
            self.assertEqual(completed['artifacts'][0]['version'], 1)
            self.assertEqual(json.loads(path.with_name('record.json.rev-1.json').read_text()), data)
        for kind, status in [('executed', 'failed'), ('reported', 'unknown'),
                             ('planned', 'failed'), ('planned', 'skipped')]:
            changed = copy.deepcopy(completed)
            changed['artifacts'][0]['evidence'].append(dict(actual, kind=kind, result=status))
            self.assertTrue(check_record(changed)['needs_review'])

    def test_same_version_evidence_cannot_be_rewritten_or_removed(self):
        for change in ('result', 'source', 'actor', 'at', 'remove'):
            with self.subTest(change=change):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'record.json'
                    original = record()
                    original['artifacts'][0]['evidence'][0]['result'] = 'failed'
                    path.write_text(json.dumps(original))
                    before = path.read_bytes()
                    candidate = copy.deepcopy(original)
                    candidate['revision'] = 2
                    evidence = candidate['artifacts'][0]['evidence']
                    if change == 'remove':
                        evidence.clear()
                    else:
                        evidence[0][change] = {'result': 'passed', 'source': 'other.log',
                                              'actor': 'other-owner', 'at': '2026-10-31T11:00:00+08:00'}[change]
                    with self.assertRaises(ValueError):
                        update_record(path, candidate, 1)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertFalse(path.with_name('record.json.rev-1.json').exists())
                    self.assertFalse(path.with_name('record.json.lock').exists())

    def test_version_bump_cannot_rebind_an_old_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            original = record()
            original['artifacts'][0]['evidence'][0]['result'] = 'failed'
            path.write_text(json.dumps(original))
            candidate = copy.deepcopy(original)
            candidate['revision'] = 2
            candidate['artifacts'][0]['version'] = 2
            old_receipt = candidate['artifacts'][0]['evidence'][0]
            old_receipt['subject']['version'] = 2
            old_receipt['result'] = 'passed'
            with self.assertRaises(ValueError):
                update_record(path, candidate, 1)
            self.assertEqual(json.loads(path.read_text()), original)

    def test_fresh_retest_resolves_failure_and_preserves_prior_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            original = record()
            original['artifacts'][0]['evidence'][0]['result'] = 'failed'
            path.write_text(json.dumps(original))
            observed = copy.deepcopy(original)
            observed['revision'] = 2
            receipt = copy.deepcopy(observed['artifacts'][0]['evidence'][0])
            receipt.update(source='fixture/retest', result='passed', at='2026-10-31T11:00:00+08:00')
            observed['artifacts'][0]['evidence'].append(receipt)
            update_record(path, observed, 1)
            self.assertTrue(check_record(observed)['needs_review'])
            recovered = copy.deepcopy(observed)
            recovered['revision'] = 3
            for node in recovered['artifacts']:
                node['version'] = 2
                node['source'] += '-v2'
                for dependency in node['depends_on']:
                    dependency['version'] = 2
                node['evidence'] = [dict(node['evidence'][-1], source='fixture/retest-' + node['id'],
                                         at='2026-10-31T12:00:00+08:00', result='passed',
                                         subject={'id': node['id'], 'version': 2})]
            update_record(path, recovered, 2)
            self.assertFalse(check_record(json.loads(path.read_text()))['needs_review'])
            self.assertEqual(json.loads(path.with_name('record.json.rev-1.json').read_text()), original)
            self.assertEqual(json.loads(path.with_name('record.json.rev-2.json').read_text()), observed)

    def test_valid_record_is_only_a_local_consistency_result(self):
        result = check_record(record())
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["needs_review"], [])
        self.assertEqual(result["branches"], {"feature": "recorded"})
        self.assertEqual(result["verification"], "local_consistency_only")

    def test_version_change_propagates_only_to_dependents_and_keeps_history(self):
        data = record()
        data["artifacts"][0]["version"] = 2
        original = copy.deepcopy(data)
        result = check_record(data)
        self.assertEqual({x["id"] for x in result["needs_review"]}, {"issue", "requirement", "test"})
        self.assertEqual(data, original)

    def test_pending_independent_branch_is_not_completed_or_invalidated(self):
        data = record()
        data["branches"].append({"id": "support", "route": "guidance", "required": ["guide"]})
        guide = copy.deepcopy(data["artifacts"][0])
        guide.update(id="guide", branch="support", status="blocked", evidence=[],
                     reason="Missing source", recovery="Owner supplies manual")
        data["artifacts"].append(guide)
        result = check_record(data)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["branches"], {"feature": "recorded", "support": "incomplete"})

    def test_bad_shapes_and_references_fail_without_crashing(self):
        for mutate in (
            lambda d: d.update(revision=True),
            lambda d: d.update(schema_version=2),
            lambda d: d.update(updated_at="yesterday"),
            lambda d: d.update(updated_at="2026-10-31T10:00:00"),
            lambda d: d.update(artifacts=[]),
            lambda d: d["artifacts"].append(copy.deepcopy(d["artifacts"][0])),
            lambda d: d["artifacts"][0].update(stage="L11"),
            lambda d: d["artifacts"][0].update(status="approved"),
            lambda d: d["artifacts"][0].update(depends_on=[{"id": "missing", "version": 1}]),
            lambda d: d["artifacts"][0].update(depends_on=[{"id": "test", "version": 1}]),
            lambda d: d["branches"][0].update(required=[]),
            lambda d: d["branches"][0].update(required=["missing"]),
            lambda d: d["artifacts"][0].update(branch="missing"),
            lambda d: d["artifacts"][0].update(evidence=[True]),
            lambda d: d["artifacts"][0].update(depends_on="wrong"),
        ):
            with self.subTest(mutate=mutate):
                data = record()
                mutate(data)
                self.assertFalse(check_record(data)["valid"])
        for data in (None, [], {}, {"schema_version": 1}):
            self.assertFalse(check_record(data)["valid"])

    def test_malformed_field_types_are_reported_instead_of_raising(self):
        for field in ("id", "kind", "stage", "branch", "owner", "source", "status", "version", "evidence", "depends_on"):
            for value in (None, [], {}, False, 0):
                with self.subTest(field=field, value=value):
                    if field in ("evidence", "depends_on") and value == []:
                        continue
                    data = record()
                    data["artifacts"][0][field] = value
                    self.assertFalse(check_record(data)["valid"])
        data = record()
        del data["artifacts"][0]["version"]
        self.assertFalse(check_record(data)["valid"])

    def test_update_rejects_changed_artifact_without_version_bump(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(record()))
            candidate = record()
            candidate["revision"] = 2
            candidate["artifacts"][0]["source"] = "changed-content"
            with self.assertRaises(ValueError):
                update_record(path, candidate, 1)
            self.assertEqual(json.loads(path.read_text()), record())

    def test_history_does_not_broaden_private_record_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(record()))
            path.chmod(0o600)
            update_record(path, dict(record(), revision=2), 1)
            history = path.parent / "record.json.rev-1.json"
            self.assertEqual(history.stat().st_mode & 0o077, 0)

    def test_missing_reported_failed_and_wrong_subject_evidence_cannot_prove_completion(self):
        for evidence in ([], [{"kind": "reported"}], [{"result": "failed"}],
                         [{"subject": {"id": "issue", "version": 2}}]):
            data = record()
            if evidence and "source" not in evidence[0]:
                changed = copy.deepcopy(data["artifacts"][0]["evidence"][0])
                changed.update(evidence[0])
                evidence = [changed]
            data["artifacts"][0]["evidence"] = evidence
            result = check_record(data)
            self.assertEqual(result["branches"]["feature"], "needs_review")

    def test_blocked_and_unknown_statements_need_action_and_source(self):
        data = record()
        data["artifacts"][0].update(status="blocked", evidence=[])
        self.assertFalse(check_record(data)["valid"])
        data = record()
        data["assertions"] = [{"text": "AI guessed", "classification": "fact", "source": "", "confirmation": "confirmed"}]
        self.assertFalse(check_record(data)["valid"])

    def test_update_is_versioned_atomic_and_identity_preserving(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            old = record()
            path.write_text(json.dumps(old))
            new = copy.deepcopy(old)
            new["revision"] = 2
            update_record(path, new, 1)
            self.assertEqual(json.loads(path.read_text()), new)
            self.assertEqual(json.loads((path.parent / "record.json.rev-1.json").read_text()), old)
            before = path.read_bytes()
            for candidate, expected in ((new, 1), (dict(new, revision=4), 2),
                                        (dict(new, revision=3, subject_ref="different"), 2),
                                        (dict(new, revision=3, artifacts=[]), 2)):
                with self.assertRaises(ValueError):
                    update_record(path, candidate, expected)
                self.assertEqual(path.read_bytes(), before)
            lock = path.with_name(path.name + ".lock")
            lock.touch()
            with self.assertRaises(FileExistsError):
                update_record(path, dict(new, revision=3), 2)
            self.assertTrue(lock.exists())
            self.assertEqual(path.read_bytes(), before)

    def test_cli_saved_review_candidate_is_distinguishable_from_rejected_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(record()))
            candidate = record()
            candidate["revision"] = 2
            candidate["artifacts"][0]["version"] = 2
            pending = Path(directory) / "candidate.json"
            pending.write_text(json.dumps(candidate))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/lifecycle_record.py"),
                                     "--record", str(path), "--candidate", str(pending),
                                     "--expected-revision", "1"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(json.loads(result.stdout)["updated"])
            self.assertEqual(json.loads(path.read_text())["revision"], 2)

    def test_non_development_resolution_does_not_require_a_feature_or_release(self):
        data = record()
        data["subject_ref"] = "existing-issue-42"
        data["branches"] = [{"id": "feature", "route": "guidance", "required": ["issue"]}]
        data["artifacts"] = data["artifacts"][:1]
        result = check_record(data)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["branches"], {"feature": "recorded"})

    def test_evidence_for_another_subject_cannot_hide_behind_a_valid_receipt(self):
        for subject in ({"id": "other", "version": 1}, {"id": "issue", "version": 2}):
            data = record()
            receipt = copy.deepcopy(data["artifacts"][0]["evidence"][0])
            receipt["subject"] = subject
            data["artifacts"][0]["evidence"].append(receipt)
            self.assertEqual(check_record(data)["branches"]["feature"], "needs_review")

    def test_execution_receipt_must_match_declared_build_environment_and_scope(self):
        for field in ("build", "environment", "scope"):
            for supplied in (None, "different"):
                with self.subTest(field=field, supplied=supplied):
                    data = record()
                    data["artifacts"][0][field] = "expected"
                    if supplied is not None:
                        data["artifacts"][0]["evidence"][0][field] = supplied
                    result = check_record(data)
                    self.assertEqual({x["id"] for x in result["needs_review"]}, {"issue", "requirement", "test"})
            data = record()
            data["artifacts"][0][field] = "expected"
            data["artifacts"][0]["evidence"][0][field] = "expected"
            self.assertEqual(check_record(data)["needs_review"], [])

    def test_expired_receipt_needs_review_and_bad_expiry_is_invalid(self):
        for expiry in ("2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z", "yesterday", "2026-01-01"):
            data = record()
            data["artifacts"][0]["evidence"][0]["expires_at"] = expiry
            result = check_record(data)
            if expiry.startswith("2000"):
                self.assertTrue(result["valid"], result)
                self.assertEqual(result["branches"]["feature"], "needs_review")
            elif expiry.startswith("2999"):
                self.assertEqual(result["needs_review"], [])
            else:
                self.assertFalse(result["valid"])

    def test_justified_cancelled_or_inapplicable_scope_is_closed_without_claiming_success(self):
        for status in ("cancelled", "not_applicable"):
            data = record()
            data["artifacts"] = data["artifacts"][:1]
            data["branches"][0]["required"] = ["issue"]
            data["artifacts"][0].update(status=status, reason="Explicit scope decision", evidence=[])
            result = check_record(data)
            self.assertTrue(result["valid"], result)
            self.assertEqual(result["branches"]["feature"], "closed")
            del data["artifacts"][0]["reason"]
            self.assertFalse(check_record(data)["valid"])

    def test_recording_execution_does_not_invent_a_new_artifact_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            original = record()
            original["artifacts"][0].update(status="in_progress", evidence=[])
            path.write_text(json.dumps(original))
            candidate = record()
            candidate["revision"] = 2
            update_record(path, candidate, 1)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["artifacts"][0]["version"], 1)
            self.assertEqual(check_record(saved)["needs_review"], [])

    def test_update_cannot_drop_prior_artifacts_or_branches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            original = record()
            original["branches"].append({"id": "support", "route": "guidance", "required": ["guide"]})
            guide = copy.deepcopy(original["artifacts"][0])
            guide.update(id="guide", branch="support", status="blocked", evidence=[], reason="Missing manual", recovery="Supply source")
            original["artifacts"].append(guide)
            path.write_text(json.dumps(original))
            for drop_branch in (False, True):
                candidate = copy.deepcopy(original)
                candidate["revision"] = 2
                candidate["artifacts"] = candidate["artifacts"][:3]
                if drop_branch:
                    candidate["branches"] = candidate["branches"][:1]
                else:
                    candidate["branches"][1]["required"] = ["issue"]
                    candidate["artifacts"][0]["branch"] = "support"
                    candidate["artifacts"][0]["version"] = 2
                    candidate["branches"][0]["required"] = ["requirement", "test"]
                with self.assertRaises(ValueError):
                    update_record(path, candidate, 1)
                self.assertEqual(json.loads(path.read_text()), original)

    def test_failed_replace_preserves_record_releases_lock_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            original = json.dumps(record()).encode()
            path.write_bytes(original)
            candidate = dict(record(), revision=2)
            with patch("lifecycle_record.os.replace", side_effect=PermissionError("injected write failure")):
                with self.assertRaises(PermissionError):
                    update_record(path, candidate, 1)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual({entry.name for entry in path.parent.iterdir()}, {"record.json", "record.json.rev-1.json"})
            update_record(path, candidate, 1)
            self.assertEqual(json.loads(path.read_text()), candidate)

    def test_update_through_symlink_preserves_alias_and_canonical_history(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "record.json"
            real.write_text(json.dumps(record()))
            alias = Path(directory) / "alias.json"
            alias.symlink_to(real.name)
            update_record(alias, dict(record(), revision=2), 1)
            self.assertTrue(alias.is_symlink())
            self.assertEqual(json.loads(real.read_text())["revision"], 2)
            self.assertTrue((real.parent / "record.json.rev-1.json").exists())

    def test_cli_bad_json_and_stale_revision_are_nonzero_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            for value in ("{", json.dumps(record())):
                path.write_text(value)
                result = subprocess.run([sys.executable, str(ROOT / "scripts/lifecycle_record.py"),
                                         "--record", str(path), "--expected-revision", "2"],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), value)


if __name__ == "__main__":
    unittest.main()
