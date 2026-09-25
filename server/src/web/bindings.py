from __future__ import annotations

from fastapi import FastAPI

from src.web.admin import register_admin_ui
from src.web.http.project_plan import register_project_plan
from src.web.http.routes import router as http_router
from src.web.websocket.endpoint import router as websocket_router


def bind_web_interfaces(app: FastAPI, root_dir: str) -> None:
    """Bind every externally exposed Web interface to one FastAPI application."""
    app.include_router(http_router)
    app.include_router(websocket_router)
    register_admin_ui(app, root_dir)
    register_project_plan(app, root_dir)
