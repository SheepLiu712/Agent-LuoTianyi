import asyncio
import os

import uvicorn
from fastapi import FastAPI

from src.application.host_context import ServerHostContext
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
    await lifecycle.start(host_context=ServerHostContext._single_worker_launcher())
    try:
        await web_server.serve()
    finally:
        await lifecycle.stop()


def main() -> None:
    """仅从配置读取启动模式和端口；SERVER_HOST 可覆盖监听主机地址。"""
    try:
        is_debug = config["is_debug"]
        if type(is_debug) is not bool:
            raise ValueError("is_debug 必须为布尔值")
        port_key = "debug_port" if is_debug else "production_port"
        port = config["server"][port_key]
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f"server.{port_key} 必须为 1 到 65535 之间的整数")
    except (KeyError, TypeError, ValueError):
        logger.exception("服务器启动配置无效")
        raise
    logger.info("服务器正在以%s模式运行，监听端口：%s", "调试" if is_debug else "生产", port)
    logger.info("启用 HTTP 模式")
    host = os.environ.get("SERVER_HOST", "127.0.0.1")
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    admin_url = f"http://{display_host}:{port}/admin"
    logger.info("控制台地址: %s", admin_url)
    print(f"\nAgentLuo 控制台: {admin_url}\n", flush=True)
    try:
        asyncio.run(run_server(host, port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
