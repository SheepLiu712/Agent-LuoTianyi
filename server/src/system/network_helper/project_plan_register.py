import os
from fastapi import HTTPException
from fastapi.responses import FileResponse
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def register_project_plan(app: "FastAPI", current_dir: str) -> None:
    """将项目计划书页面注册到 FastAPI 应用中。"""
    project_plan_path = os.path.join(
        os.path.dirname(current_dir),
        "docs",
        "项目计划书",
        "AgentLuo项目计划书.html",
    )

    @app.get("/project-plan", include_in_schema=False)
    @app.get("/project-plan/", include_in_schema=False)
    async def project_plan():
        if not os.path.isfile(project_plan_path):
            raise HTTPException(status_code=404, detail="项目计划书页面尚未生成")
        return FileResponse(project_plan_path, media_type="text/html")
