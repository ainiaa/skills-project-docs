"""Synthetic read-only repair service; no production identity integration. 作者：Jeff.Liu"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

REPAIRS = {
    "R-100": {"owner": "alice", "device": "laptop", "status": "repairing", "next_action": "等待维修完成"},
    "R-200": {"owner": "bob", "device": "monitor", "status": "ready", "next_action": "联系行政领取"},
}
# Synthetic identities only; never use these fixture tokens for real authentication.
IDENTITIES = {"Bearer demo-alice": "alice", "Bearer demo-bob": "bob"}


def query(authorization, repair_id, available=True):
    actor = IDENTITIES.get(authorization)
    if actor is None:
        return 401, {"error": "unauthorized"}
    if not isinstance(repair_id, str) or not re.fullmatch(r"R-[0-9]{3}", repair_id):
        return 400, {"error": "invalid_id"}
    if not available:
        return 503, {"error": "source_unavailable"}
    repair = REPAIRS.get(repair_id)
    if repair is None:
        return 404, {"error": "not_found"}
    if repair["owner"] != actor:
        return 403, {"error": "forbidden"}
    return 200, {"id": repair_id, **{key: repair[key] for key in ("device", "status", "next_action")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--unavailable", action="store_true")
    args = parser.parse_args()
    build = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == "/health":
                status, body = (503 if args.unavailable else 200), {"available": not args.unavailable, "build": build}
            elif path.startswith("/repairs/"):
                status, body = query(self.headers.get("Authorization"), path[len("/repairs/"):], not args.unavailable)
            else:
                status, body = 404, {"error": "not_found"}
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass  # The pilot records responses; authorization headers never enter logs.

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        args.port_file.write_text(json.dumps({"host": "127.0.0.1", "port": server.server_port, "build": build}))
        server.serve_forever()


if __name__ == "__main__":
    main()
