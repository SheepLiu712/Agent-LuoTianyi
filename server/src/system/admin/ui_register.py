import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from typing import TYPE_CHECKING

from .admin_interface import router as admin_router

if TYPE_CHECKING:
    from fastapi import FastAPI

def register_admin_ui(app: "FastAPI", current_dir: str) -> None:
    '''将管理后台的UI注册到FASTAPI应用中'''
    # 1. 注册管理后台的路由
    app.include_router(admin_router)

    # 2. 注册管理后台的静态资源
    admin_ui_build = os.path.join(current_dir, "res", "admin_ui", "admin_static")
    admin_ui_assets = os.path.join(admin_ui_build, "assets")
    if os.path.isdir(admin_ui_assets):
        app.mount("/admin/assets", StaticFiles(directory=admin_ui_assets), name="admin-assets")

    index_path = os.path.join(admin_ui_build, "index.html")
    @app.get("/admin")
    @app.get("/admin/{path:path}")
    async def admin_index(path: str = ""):
        if index_path and os.path.exists(index_path):
            return FileResponse(index_path, headers={"Cache-Control": "no-store"})
        return HTMLResponse(
            "<h1>AgentLuo Server Console</h1>"
            "<p>Admin UI has not been built yet. Run <code>cd server/res/admin_ui && npm install && npm run build</code>.</p>"
        )

