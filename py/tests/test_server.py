"""Server tests: a real aiohttp TestServer on a background event loop, driven through a small sync helper."""
import asyncio
import json
import threading
from pathlib import Path

import pytest
from aiohttp import ClientSession, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from scansim_server.app import create_app

PROTOCOL = "ohsu.ct.multiphase_liver"
PNG = b"\x89PNG\r\n\x1a\n"
WAIT_S = 10.0


class Reply:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body


class SyncSocket:
    def __init__(self, harness, ws):
        self._h, self._ws, self.session_id = harness, ws, None
        self.closed_by_server = False

    def send(self, message):
        self._h.run(self._ws.send_str(json.dumps(message)))

    def send_raw(self, text):
        self._h.run(self._ws.send_str(text))

    def _receive(self):
        msg = self._h.run(self._ws.receive(), WAIT_S)
        if msg.type == WSMsgType.TEXT:
            return json.loads(msg.data)
        self.closed_by_server = True
        return None

    def until(self, predicate):
        for _ in range(2000):
            message = self._receive()
            if message is None:
                raise AssertionError("socket closed while waiting")
            if predicate(message):
                return message
        raise AssertionError("no matching message")

    def next(self, kind):
        return self.until(lambda m: m["type"] == kind)

    def close(self):
        self._h.run(self._ws.close())


class Harness:
    def __init__(self, data_dir, client_dir=None):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()
        self.app = create_app(data_dir, client_dir)
        self.client = TestClient(TestServer(self.app), loop=self.loop)
        self.run(self.client.start_server())

    def run(self, coro, timeout=WAIT_S):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def get(self, path, headers=None):
        async def go():
            async with self.client.get(path, headers=headers) as r:
                return Reply(r.status, r.headers, await r.read())
        return self.run(go())

    def get_json(self, path):
        r = self.get(path)
        assert r.status == 200
        return json.loads(r.body)

    def ws(self, headers=None):
        return SyncSocket(self, self.run(self.client.ws_connect("/ws", headers=headers)))

    def started_ws(self, patient="sub-000", seed=1):
        ws = self.ws()
        ws.send({"type": "start", "modality": "CT", "protocol_id": PROTOCOL, "patient_id": patient, "seed": seed})
        ws.session_id = ws.next("snapshot")["data"]["session_id"]
        return ws

    def settle(self, seconds=0.3):
        self.run(asyncio.sleep(seconds))

    def stop(self):
        self.run(self.client.close())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)
        self.loop.close()


@pytest.fixture
def client(DATA):
    harness = Harness(DATA)
    yield harness
    harness.stop()


@pytest.fixture
def app(client):
    return client.app


def test_catalog_lists_the_liver_exam_and_built_patients(client):
    c = client.get_json("/api/catalog")
    assert any(p["id"] == PROTOCOL and p["status"] == "complete" for p in c["protocols"])
    assert {"id": "sub-000", "label": "Volunteer 000"} in c["patients"]
    assert [m["id"] for m in c["modalities"]] == ["CT", "MRI"]
    assert [m["available"] for m in c["modalities"]] == [True, False]
    assert c["scanners"] and set(c["scanners"][0]) == {"id", "label"}
    assert [p["id"] for p in c["patients"]] == sorted(p["id"] for p in c["patients"])


def test_session_over_websocket(client):
    ws = client.ws()
    ws.send({"type": "start", "modality": "CT", "protocol_id": PROTOCOL, "patient_id": "sub-000", "seed": 1})
    snap = ws.next("snapshot")["data"]
    assert snap["stages"][0]["steps"][0]["status"] == "ready"
    ws.send({"type": "action", "id": 1, "action": {"type": "perform", "step_id": "order_received"}})
    assert ws.next("result") == {"type": "result", "id": 1, "ok": True, "error": None}
    assert ws.until(lambda m: m["type"] == "snapshot" and m["data"]["stages"][0]["steps"][0]["status"] == "done")


def test_bad_action_is_an_error_message_not_a_crash(client):
    ws = client.started_ws()
    ws.send({"type": "action", "id": 2, "action": {"type": "explode"}})
    r = ws.next("result")
    assert r["ok"] is False and r["error"]


def test_images_are_png_and_unknown_session_is_404(client, monkeypatch):
    from scansim.session import ExamSession

    assert client.get("/api/session/nope/topogram/AP.png").status == 404
    ws = client.started_ws()
    sid = ws.session_id
    not_yet = client.get(f"/api/session/{sid}/topogram/AP.png")     # nothing acquired at the start
    assert not_yet.status == 404 and json.loads(not_yet.body)["error"]
    for path in (f"/api/session/{sid}/tracking.png", f"/api/session/{sid}/series/x/axial/0.png",
                 f"/api/session/{sid}/series/x/axial/abc.png", f"/api/session/{sid}/topogram/ZZ.png"):
        assert client.get(path).status == 404
    monkeypatch.setattr(ExamSession, "topogram_png", lambda self, view: PNG + view.encode())
    monkeypatch.setattr(ExamSession, "series_png", lambda self, s, plane, i: PNG + f"{s}{plane}{i}".encode())
    monkeypatch.setattr(ExamSession, "tracking_png", lambda self: PNG)
    r = client.get(f"/api/session/{sid}/topogram/AP.png?t=5")
    assert r.status == 200 and r.body[:8] == PNG and r.headers["Cache-Control"] == "no-store"
    assert r.headers["Content-Type"] == "image/png"
    assert client.get(f"/api/session/{sid}/series/s1/axial/3.png").body.endswith(b"s1axial3")
    assert client.get(f"/api/session/{sid}/tracking.png").status == 200


def test_foreign_host_is_forbidden(client):
    assert client.get("/api/catalog", headers={"Host": "evil.example"}).status == 403
    assert client.get("/api/catalog", headers={"Host": "localhost:1234"}).status == 200
    assert client.get("/api/catalog", headers={"Host": "127.0.0.1.evil.example"}).status == 403


def test_closing_the_socket_frees_the_session(client, app):
    ws = client.started_ws()
    assert len(app["sessions"]) == 1
    ws.close()
    client.settle()
    assert app["sessions"] == {}


def test_foreign_origin_websocket_is_rejected(client):
    with pytest.raises(Exception):
        client.ws(headers={"Origin": "http://evil.example"})
    ws = client.ws(headers={"Origin": "http://localhost:5173"})
    ws.close()


def test_second_start_replaces_the_session(client, app):
    ws = client.started_ws()
    first = ws.session_id
    ws.send({"type": "start", "modality": "CT", "protocol_id": PROTOCOL, "patient_id": "sub-000", "seed": 2})
    second = ws.next("snapshot")["data"]["session_id"]
    assert second != first
    assert list(app["sessions"]) == [second]
    assert client.get(f"/api/session/{first}/tracking.png").status == 404


@pytest.mark.parametrize("start", [
    {"modality": "MRI", "protocol_id": PROTOCOL, "patient_id": "sub-000"},
    {"modality": "CT", "protocol_id": "nope", "patient_id": "sub-000"},
    {"modality": "CT", "protocol_id": PROTOCOL, "patient_id": "../etc"},
    {"modality": "CT", "protocol_id": PROTOCOL, "patient_id": "sub-000", "seed": "x"},
])
def test_bad_start_is_an_error_and_opens_nothing(client, app, start):
    ws = client.ws()
    ws.send({"type": "start", **start})
    assert ws.next("error")["message"]
    assert app["sessions"] == {}


def test_a_negative_seed_is_refused_by_name_and_opens_nothing(client, app):
    ws = client.ws()
    ws.send({"type": "start", "modality": "CT", "protocol_id": PROTOCOL, "patient_id": "sub-000", "seed": -1})
    assert "The seed must be a whole number from 0 up" in ws.next("error")["message"]
    assert app["sessions"] == {}


def test_a_refused_start_leaves_the_running_exam_alone(client, app):
    ws = client.started_ws()
    for bad in ({"seed": -1}, {"patient_id": "nobody"}, {"protocol_id": "nope"}):
        ws.send({"type": "start", "modality": "CT", "protocol_id": PROTOCOL, "patient_id": "sub-000", "seed": 1, **bad})
        assert ws.next("error")["message"]
        assert list(app["sessions"]) == [ws.session_id]
    ws.send({"type": "action", "id": 5, "action": {"type": "perform", "step_id": "order_received"}})
    assert ws.next("result") == {"type": "result", "id": 5, "ok": True, "error": None}


def test_malformed_messages_get_error_messages(client):
    ws = client.ws()
    ws.send_raw("not json")
    assert ws.next("error")["message"]
    ws.send_raw("[1, 2]")
    assert ws.next("error")["message"]
    ws.send({"type": "dance"})
    assert ws.next("error")["message"]
    ws.send({"type": "action", "id": 7, "action": {"type": "abort"}})
    r = ws.next("result")
    assert r["id"] == 7 and r["ok"] is False and "Start an exam first" in r["error"]


def test_dropped_socket_mid_scan_frees_session_and_new_connection_starts(client, app):
    ws = client.started_ws()
    ws.send({"type": "action", "id": 1, "action": {"type": "set_time_scale", "value": 20}})
    ws.next("result")
    ws.close()
    client.settle()
    assert app["sessions"] == {}
    fresh = client.started_ws()
    assert len(app["sessions"]) == 1
    fresh.close()


def test_engine_error_reports_closes_and_frees(client, app, monkeypatch):
    from scansim.session import ExamSession

    def boom(self, dt_s):
        raise RuntimeError("kaput")
    ws = client.started_ws()
    monkeypatch.setattr(ExamSession, "advance", boom)
    message = ws.next("error")["message"]
    assert message.startswith("Simulation error: RuntimeError: kaput")
    client.settle()
    assert app["sessions"] == {}
    assert ws._receive() is None and ws.closed_by_server


def test_clock_advances_in_real_time(client):
    ws = client.started_ws()
    ws.send({"type": "action", "id": 1, "action": {"type": "set_time_scale", "value": 50}})
    assert ws.until(lambda m: m["type"] == "snapshot" and m["data"]["clock"]["sim_time_s"] > 0.5)


def test_static_client_is_served_and_missing_client_is_404(DATA, tmp_path):
    (tmp_path / "index.html").write_text("<html>hi</html>")
    (tmp_path / "a.js").write_text("1")
    served = Harness(DATA, tmp_path)
    try:
        assert b"hi" in served.get("/").body
        assert served.get("/a.js").body == b"1"
        assert served.get("/api/catalog").status == 200
    finally:
        served.stop()
    missing = Harness(DATA, tmp_path / "absent")
    try:
        r = missing.get("/")
        assert r.status == 404 and b"The client has not been built" in r.body
    finally:
        missing.stop()


def test_shutdown_clears_sessions(DATA):
    h = Harness(DATA)
    h.started_ws()
    app = h.app
    h.stop()
    assert app["sessions"] == {}
