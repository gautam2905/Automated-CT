"""The aiohttp application: catalog, image endpoints, static client files and the local-only guard."""
import json
import logging
import re
import warnings
from pathlib import Path
from typing import Optional

from aiohttp import web

from scansim.protocols.library import load_library
from scansim.snapshot import ProtocolView
from scansim_server.ws import close_all_sessions, close_all_sockets, websocket_handler

log = logging.getLogger(__name__)

_HOST_HEADER = re.compile(r"(127\.0\.0\.1|localhost)(:\d{1,5})?")
_INDEX = re.compile(r"\d{1,9}")
MODALITIES = [{"id": "CT", "label": "CT", "available": True}, {"id": "MRI", "label": "MRI", "available": False}]


@web.middleware
async def local_only(request: web.Request, handler):
    if not _HOST_HEADER.fullmatch(request.headers.get("Host", "")):
        return web.json_response({"error": "Forbidden: this server only answers local requests"}, status=403)
    return await handler(request)


def _patients(data_dir: Path) -> list[dict]:
    root = data_dir / "patients"
    ids = sorted(p.name for p in root.iterdir() if (p / "meta.json").is_file()) if root.is_dir() else []
    return [{"id": i, "label": "Volunteer " + "".join(re.findall(r"\d", i))} for i in ids]


def _scanners(data_dir: Path) -> list[dict]:
    result = []
    for path in sorted((data_dir / "scanners").glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            label = " ".join(str(spec[k]) for k in ("vendor", "model") if k in spec) or path.stem
        except (OSError, ValueError, AttributeError):
            log.warning("Scanner file %s is unreadable", path)
            label = path.stem
        result.append({"id": path.stem, "label": label})
    return result


async def catalog(request: web.Request) -> web.Response:
    data_dir: Path = request.app["data_dir"]
    protocols = [ProtocolView(id=p.id, title=p.title, modality=p.modality, region=p.region, status=p.status,
                              source_url=p.source.url).model_dump(mode="json")
                 for p in load_library(data_dir).values()]
    return web.json_response({"modalities": MODALITIES, "protocols": protocols,
                              "patients": _patients(data_dir), "scanners": _scanners(data_dir)})


def _not_found(message: str) -> web.Response:
    return web.json_response({"error": message}, status=404)


def _png(render, request: web.Request, *args) -> web.Response:
    session = request.app["sessions"].get(request.match_info["sid"])
    if session is None:
        return _not_found("Unknown session")
    try:
        body = render(session, *args)
    except (LookupError, ValueError) as err:
        return _not_found(str(err) or "No such image")
    return web.Response(body=body, content_type="image/png", headers={"Cache-Control": "no-store"})


async def topogram(request: web.Request) -> web.Response:
    view = request.match_info["view"]
    return _png(lambda s: s.topogram_png(view), request)


async def series(request: web.Request) -> web.Response:
    m = request.match_info
    if not _INDEX.fullmatch(m["index"]):
        return _not_found("Unknown image index")
    return _png(lambda s: s.series_png(m["series_id"], m["plane"], int(m["index"])), request)


async def tracking(request: web.Request) -> web.Response:
    return _png(lambda s: s.tracking_png(), request)


def _client_routes(app: web.Application, client_dir: Optional[Path]) -> None:
    if client_dir is not None and Path(client_dir).is_dir():
        root = Path(client_dir)

        async def index(request: web.Request) -> web.StreamResponse:
            return web.FileResponse(root / "index.html")
        app.router.add_get("/", index)
        app.router.add_static("/", root)
    else:
        async def missing(request: web.Request) -> web.Response:
            return web.Response(status=404, text="The client has not been built")
        app.router.add_get("/", missing)


async def _on_cleanup(app: web.Application) -> None:
    await close_all_sessions(app)


def create_app(data_dir: Path, client_dir: Optional[Path]) -> web.Application:
    app = web.Application(middlewares=[local_only])
    with warnings.catch_warnings():       # the interface names plain string keys (app["sessions"])
        warnings.simplefilter("ignore", web.NotAppKeyWarning)
        app["data_dir"] = Path(data_dir)
        app["sessions"] = {}
        app["loops"] = {}
        app["sockets"] = set()
    app.router.add_get("/api/catalog", catalog)
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/api/session/{sid}/topogram/{view}.png", topogram)
    app.router.add_get("/api/session/{sid}/series/{series_id}/{plane}/{index}.png", series)
    app.router.add_get("/api/session/{sid}/tracking.png", tracking)
    _client_routes(app, client_dir)
    app.on_shutdown.append(close_all_sockets)
    app.on_cleanup.append(_on_cleanup)
    return app
