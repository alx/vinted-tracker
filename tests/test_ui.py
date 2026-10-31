"""Tests for the dashboard HTTP layer (ui.py)."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import ui


def _start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ui.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.load(r)


def test_api_items(tmp_path, monkeypatch):
    state = tmp_path / "seen.json"
    state.write_text(
        json.dumps(
            {
                "__primed__": True,
                "1": {
                    "title": "A",
                    "price": 20.0,
                    "currency": "EUR",
                    "size": "M",
                    "condition": "G",
                    "photo": "",
                    "url": "u1",
                    "first_seen": "t",
                    "updated": "t",
                    "missing": 0,
                    "sold": False,
                },
                "2": {
                    "title": "B",
                    "price": 10.0,
                    "currency": "EUR",
                    "size": "S",
                    "condition": "G",
                    "photo": "",
                    "url": "u2",
                    "first_seen": "t",
                    "updated": "t",
                    "missing": 2,
                    "sold": True,
                },
            }
        )
    )
    monkeypatch.setattr(ui, "STATE_FILE", state)

    srv = _start_server()
    try:
        data = _get(srv.server_port, "/api/items")
        assert {i["id"] for i in data} == {"1", "2"}
        assert next(i for i in data if i["id"] == "2")["sold"] is True
        assert next(i for i in data if i["id"] == "1")["sold"] is False
    finally:
        srv.shutdown()


def test_healthz(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "STATE_FILE", tmp_path / "seen.json")
    srv = _start_server()
    try:
        assert _get(srv.server_port, "/healthz") == {"ok": True}
    finally:
        srv.shutdown()
