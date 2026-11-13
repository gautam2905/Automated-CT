"""Local web server between the Python engine and the browser client."""
from scansim_server.app import create_app

__all__ = ["create_app"]
