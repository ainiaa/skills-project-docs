"""Synthetic CLI fixture, not a production order service. 作者：Jeff.Liu"""
import json
import sys


def lookup(role, order_id, available=True):
    # Role and records are fixture values; replace with trusted identity/data in a real service.
    if role != "owner":
        raise PermissionError("Access denied")
    if not order_id.strip():
        raise ValueError("Order ID is required")
    if not available:
        raise ConnectionError("Source unavailable")
    if order_id != "EX-1":
        return {"status": "not_found", "next_action": "Check order ID"}
    return {"status": "investigating", "next_action": "Wait for support"}


if __name__ == "__main__":
    print(json.dumps(lookup(*sys.argv[1:]), sort_keys=True))
