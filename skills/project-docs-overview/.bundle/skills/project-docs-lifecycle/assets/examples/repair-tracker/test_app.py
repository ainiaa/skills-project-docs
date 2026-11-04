"""Executable AC-01..07 for the synthetic repair service. 作者：Jeff.Liu"""
import copy
import unittest
from app import REPAIRS, query


class RepairTests(unittest.TestCase):
    def test_ac01_owner_sees_only_public_fields(self):
        self.assertEqual(query("Bearer demo-alice", "R-100"),
                         (200, {"id": "R-100", "device": "laptop", "status": "repairing", "next_action": "等待维修完成"}))

    def test_ac02_missing_and_invalid_identity(self):
        for identity in (None, "", "Bearer other", "demo-alice"):
            self.assertEqual(query(identity, "R-100"), (401, {"error": "unauthorized"}))

    def test_ac03_other_employee_cannot_read(self):
        self.assertEqual(query("Bearer demo-bob", "R-100"), (403, {"error": "forbidden"}))

    def test_ac04_unknown_repair(self):
        self.assertEqual(query("Bearer demo-alice", "R-999"), (404, {"error": "not_found"}))

    def test_ac05_invalid_boundaries(self):
        for repair_id in (None, "", "R-10", "R-1000", "R-１２３", "R-100/extra", " R-100"):
            self.assertEqual(query("Bearer demo-alice", repair_id), (400, {"error": "invalid_id"}))

    def test_ac06_source_outage_and_recovery(self):
        self.assertEqual(query("Bearer demo-alice", "R-100", available=False), (503, {"error": "source_unavailable"}))
        self.assertEqual(query("Bearer demo-alice", "R-100")[0], 200)

    def test_ac07_repeated_queries_do_not_mutate_source(self):
        before = copy.deepcopy(REPAIRS)
        for _ in range(2):
            response = query("Bearer demo-alice", "R-100")[1]
            response["status"] = "tampered"
            query("Bearer demo-bob", "R-100")
            query("Bearer demo-alice", "R-100", available=False)
        self.assertEqual(REPAIRS, before)


if __name__ == "__main__":
    unittest.main()
