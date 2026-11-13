"""Run the server: python -m scansim_server [--port 8770] [--data DIR] [--client DIR]."""
import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from aiohttp import web

from scansim_server.app import create_app

ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"


async def serve(port: int, data_dir: Path, client_dir: Path) -> None:
    runner = web.AppRunner(create_app(data_dir, client_dir))
    await runner.setup()
    await web.TCPSite(runner, HOST, port).start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    sys.stdout.write(f"Scan Room Simulator is ready at http://{HOST}:{port}\n")
    sys.stdout.flush()
    await stop.wait()
    await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(prog="scansim_server")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--client", type=Path, default=ROOT / "client" / "dist")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(args.port, args.data, args.client))


if __name__ == "__main__":
    main()
