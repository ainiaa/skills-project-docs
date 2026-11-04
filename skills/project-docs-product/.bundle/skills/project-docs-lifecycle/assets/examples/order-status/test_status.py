"""Synthetic requirement FR-EX-1: observable normal, boundary and error behavior."""
import unittest
from status import lookup


class StatusTests(unittest.TestCase):
    def test_authorized_user_sees_next_action(self):
        self.assertEqual(lookup("owner", "EX-1"), {"status": "investigating", "next_action": "Wait for support"})

    def test_other_role_is_denied(self):
        with self.assertRaises(PermissionError):
            lookup("visitor", "EX-1")

    def test_missing_order(self):
        self.assertEqual(lookup("owner", "unknown"), {"status": "not_found", "next_action": "Check order ID"})

    def test_empty_order_is_invalid(self):
        with self.assertRaises(ValueError):
            lookup("owner", "  ")

    def test_source_failure_is_visible(self):
        with self.assertRaises(ConnectionError):
            lookup("owner", "EX-1", available=False)


if __name__ == "__main__":
    unittest.main()
