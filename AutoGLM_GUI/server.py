"""AutoGLM-GUI Backend API Server (FastAPI + Socket.IO)."""

from socketio import ASGIApp

from AutoGLM_GUI.api import app as fastapi_app
from AutoGLM_GUI.socketio_server import sio

app = ASGIApp(sio, other_asgi_app=fastapi_app)

__all__ = ["app"]
