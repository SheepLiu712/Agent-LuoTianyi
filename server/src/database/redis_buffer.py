from typing import Dict, Any

from .memory_storage import MemoryStorage
from ..utils.logger import get_logger

r: MemoryStorage | None = None
logger = get_logger(__name__)


def init_redis_buffer(redis_config: Dict[str, Any]):
    global r
    _ = redis_config
    r = MemoryStorage()
    logger.info("Memory buffer initialized (Redis compatibility mode)")


def get_redis_buffer() -> MemoryStorage:
    global r
    if r is None:
        raise Exception("Memory buffer not initialized")
    return r


