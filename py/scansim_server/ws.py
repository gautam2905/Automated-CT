"""The WebSocket: actions in, snapshots out, and the real-time loop that advances each session."""
import asyncio
import contextlib
import json
import logging
import secrets
import time
from typing import Optional
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from scansim.session import ExamSession, open_session

log = logging.getLogger(__name__)

TICK_S = 0.033
MIN_SEND_INTERVAL_S = 0.05          # at most 20 snapshots a second
LOCAL_HOSTS = ("127.0.0.1", "localhost")
MAX_ADVANCE_S = 2.0                 # simulated seconds per tick, so a stalled event loop cannot make time jump


class Connection:
    """One browser tab: its socket, its session (if any) and that session's loop."""

    def __init__(self, app: web.Application, ws: web.WebSocketResponse) -> None:
        self.app, self.ws = app, ws
        self.session: Optional[ExamSession] = None
        self.task: Optional[asyncio.Task] = None
        self._last_json: Optional[str] = None
        self._last_sent_s = 0.0
        self._send_lock = asyncio.Lock()

    async def send(self, message: dict) -> None:
        async with self._send_lock:
            if not self.ws.closed:
                await self.ws.send_str(json.dumps(message))

    async def send_error(self, text: str) -> None:
        await self.send({"type": "error", "message": text})

    async def send_snapshot(self, force: bool = False) -> None:
        data = self.session.snapshot().model_dump_json()
        if not force and data == self._last_json:
            return
        self._last_json, self._last_sent_s = data, time.monotonic()
        async with self._send_lock:
            if not self.ws.closed:
                await self.ws.send_str('{"type": "snapshot", "data": ' + data + "}")

    # ---- session lifecycle ----

    async def stop_session(self) -> None:
        task, session = self.task, self.session
        self.task = self.session = self._last_json = None
        if task is not None:
            task.cancel()
            if task is not asyncio.current_task():
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        if session is not None:
            self.app["sessions"].pop(session.session_id, None)
            self.app["loops"].pop(session.session_id, None)

    async def start(self, message: dict) -> None:
        problem = _check_start(message)
        if problem:
            return await self.send_error(problem)
        await self.stop_session()
        try:
            session = open_session(self.app["data_dir"], message["protocol_id"], message["patient_id"],
                                   seed=message.get("seed", 0), session_id=secrets.token_hex(8))
        except (ValueError, OSError) as err:
            return await self.send_error(str(err))
        self.session = session
        self.app["sessions"][session.session_id] = session
        await self.send_snapshot(force=True)
        self.task = asyncio.create_task(self._run(session))
        self.app["loops"][session.session_id] = self.task

    async def act(self, message: dict) -> None:
        action_id = message.get("id")
        if self.session is None:
            return await self.send({"type": "result", "id": action_id, "ok": False,
                                    "error": "Start an exam first"})
        action = message.get("action")
        try:
            result = self.session.dispatch(action) if isinstance(action, dict) else None
        except Exception as err:
            return await self._fail(err)
        if result is None:
            result_msg = {"ok": False, "error": "Invalid action: expected an object"}
        else:
            result_msg = {"ok": result.ok, "error": result.error}
        await self.send({"type": "result", "id": action_id, **result_msg})
        await self.send_snapshot(force=True)

    async def handle_text(self, text: str) -> None:
        try:
            message = json.loads(text)
        except ValueError:
            return await self.send_error("Message is not valid JSON")
        if not isinstance(message, dict):
            return await self.send_error("Message must be a JSON object")
        kind = message.get("type")
        if kind == "start":
            await self.start(message)
        elif kind == "action":
            await self.act(message)
        else:
            await self.send_error(f"Unknown message type {kind!r}")

    # ---- the real-time loop ----

    async def _run(self, session: ExamSession) -> None:
        last = time.monotonic()
        try:
            while True:
                await asyncio.sleep(TICK_S)
                now = time.monotonic()
                elapsed, last = now - last, now
                session.advance(min(elapsed * session.time_scale, MAX_ADVANCE_S))
                if now - self._last_sent_s >= MIN_SEND_INTERVAL_S:
                    await self.send_snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as err:
            await self._fail(err)

    async def _fail(self, err: Exception) -> None:
        log.error("Simulation error in session %s", getattr(self.session, "session_id", "?"), exc_info=err)
        with contextlib.suppress(ConnectionError, RuntimeError):
            await self.send_error(f"Simulation error: {type(err).__name__}: {err}")
        await self.stop_session()
        await self.ws.close()


def _check_start(message: dict) -> Optional[str]:
    if message.get("modality") != "CT":
        return "Only the CT modality is available"
    for key in ("protocol_id", "patient_id"):
        if not isinstance(message.get(key), str):
            return f"Start needs a text value for {key}"
    seed = message.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        return "The seed must be an integer"
    return None


def is_local_origin(origin: str) -> bool:
    try:
        return urlsplit(origin).hostname in LOCAL_HOSTS
    except ValueError:
        return False


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    origin = request.headers.get("Origin")
    if origin is not None and not is_local_origin(origin):
        return web.json_response({"error": "Forbidden: foreign origin"}, status=403)
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    conn = Connection(request.app, ws)
    request.app["sockets"].add(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await conn.handle_text(msg.data)
    finally:
        request.app["sockets"].discard(ws)
        await asyncio.shield(conn.stop_session())
    return ws


async def close_all_sessions(app: web.Application) -> None:
    for task in list(app["loops"].values()):
        task.cancel()
    await asyncio.gather(*app["loops"].values(), return_exceptions=True)
    app["loops"].clear()
    app["sessions"].clear()


async def close_all_sockets(app: web.Application) -> None:
    await asyncio.gather(*(ws.close() for ws in list(app["sockets"])), return_exceptions=True)
