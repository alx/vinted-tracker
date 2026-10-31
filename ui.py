#!/usr/bin/env python3
"""Read-only web dashboard for the Vinted tracker. Stdlib only.

Serves index.html at / and a JSON view of tracked items at /api/items,
both read from the same state file the poller writes.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATE_FILE = Path(os.environ.get("STATE_FILE", str(BASE / "state" / "seen.json")))
INDEX = Path(os.environ.get("INDEX_HTML", str(BASE / "index.html")))
TITLE = os.environ.get("TRACKER_NAME", "Vinted Tracker")
HOST = os.environ.get("UI_HOST", "127.0.0.1")
PORT = int(os.environ.get("UI_PORT", "3110"))


def load_items():
    d = {}
    if STATE_FILE.exists():
        try:
            d = json.loads(STATE_FILE.read_text())
        except Exception:
            d = {}
    out = []
    for sid, r in d.items():
        if sid == "__primed__":
            continue
        if isinstance(r, str):
            out.append(
                {
                    "id": sid,
                    "title": "",
                    "price": None,
                    "currency": "",
                    "size": "",
                    "condition": "",
                    "photo": "",
                    "url": "",
                    "first_seen": r,
                    "updated": r,
                    "missing": 0,
                    "sold": False,
                }
            )
        else:
            out.append(
                {
                    "id": sid,
                    "title": r.get("title", ""),
                    "price": r.get("price"),
                    "currency": r.get("currency", ""),
                    "size": r.get("size", ""),
                    "condition": r.get("condition", ""),
                    "photo": r.get("photo", ""),
                    "url": r.get("url", ""),
                    "first_seen": r.get("first_seen", ""),
                    "updated": r.get("updated", ""),
                    "missing": r.get("missing", 0),
                    "sold": bool(r.get("sold", False)),
                }
            )
    return out


class H(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            html = INDEX.read_text() if INDEX.exists() else "missing index.html"
            self._send(200, "text/html; charset=utf-8", html.replace("__TITLE__", TITLE))
        elif p == "/api/items":
            self._send(200, "application/json", json.dumps(load_items()))
        elif p == "/healthz":
            self._send(200, "application/json", '{"ok": true}')
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
