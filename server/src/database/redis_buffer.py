import redis
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from ..utils.logger import get_logger

r : redis.Redis | None = None
logger = get_logger(__name__)
def init_redis_buffer(redis_config: Dict[str, Any]):
    global r
    r = redis.Redis(
        host=redis_config.get("host", "localhost"),
        port=redis_config.get("port", 6379),
        db=redis_config.get("db", 0),
        password=redis_config.get("password", None),
        decode_responses=True
    )
    logger.info("Redis buffer initialized")

def get_redis_buffer() -> redis.Redis:
    global r
    if r is None:
        raise Exception("Redis not initialized")
    return r


