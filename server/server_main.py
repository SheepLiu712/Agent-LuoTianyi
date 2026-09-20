import asyncio
import os

import uvicorn
from fastapi import FastAPI

from src.application.server_lifecycle import ServerLifecycle
from src.utils.helpers import load_config
from src.utils.logger import get_logger, install_access_log_filter
from src.web.bindings import bind_web_interfaces

current_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(current_dir)
logger = get_logger("server_main")
config = load_config("config/config.json")
server_lifecycle = ServerLifecycle(root_dir=current_dir)
app = FastAPI()
bind_web_interfaces(app, current_dir)


async def run_server(
    host: str,
    port: int,
    lifecycle: ServerLifecycle = server_lifecycle,
) -> None:
    """Run the application lifecycle and Uvicorn in one event loop."""
    install_access_log_filter()
    web_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            lifespan="off",
        )
    )
    await lifecycle.start()
    try:
        await web_server.serve()
    finally:
        await lifecycle.stop()


if __name__ == "__main__":
    is_debug = config.get("is_debug", False)
    if is_debug:
        logger.info("服务器正在以调试模式运行")
    logger.info("启用 HTTP 模式")
    host = os.environ.get("SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("SERVER_PORT", "60030"))
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    admin_url = f"http://{display_host}:{port}/admin"
    logger.info("控制台地址: %s", admin_url)
    print(f"\nAgentLuo 控制台: {admin_url}\n", flush=True)
    asyncio.run(run_server(host, port))
