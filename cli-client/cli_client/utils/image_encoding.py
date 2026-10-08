"""CLI 客户端图片编码管道，供会话发送流程使用。"""

from __future__ import annotations

import base64
import os
import uuid

from . import image_rules
from .image_compression import compress_image_for_upload
from .logger import get_logger


def save_image_to_temp(image_data: bytes, postfix: str, *, base_dir: str | None = None) -> str:
    """将图片字节保存到独立的 temp/images/<UUID><后缀> 并返回路径。"""
    cwd = base_dir or os.getcwd()
    new_file_path = os.path.join(
        cwd,
        "temp",
        "images",
        uuid.uuid4().hex + postfix,
    )
    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
    with open(new_file_path, "wb") as f:
        f.write(image_data)
    return new_file_path


def prepare_image_payload(image_path: str) -> dict:
    """检测大小、按需压缩，产出预览与上传共用的临时副本和载荷。"""
    logger = get_logger(__name__)
    mime_type = image_rules.detect_image_mime(image_path)
    if mime_type not in image_rules.ALLOWED_IMAGE_MIME_TYPES:
        return {"ok": False, "error": "不支持的图片格式，请选择 JPG、PNG、GIF、BMP 或 WebP 图片", "drop": True}
    try:
        original_size = os.path.getsize(image_path)
    except OSError:
        original_size = None
        logger.warning("图片大小无法获取，继续尝试读取原图")
    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
    except OSError:
        logger.exception("图片读取失败")
        return {"ok": False, "error": "图片无法读取，请确认文件仍然存在且可访问", "drop": True}
    postfix = os.path.splitext(image_path)[1]
    if original_size is not None and original_size > image_rules.MAX_IMAGE_BYTES:
        try:
            logger.info("开始压缩图片，原始大小=%s", original_size)
            image_data, mime_type, postfix = compress_image_for_upload(image_data, mime_type)
            if len(image_data) > image_rules.MAX_IMAGE_BYTES:
                raise ValueError("compressed image exceeds upload limit")
            logger.info("图片压缩完成，大小=%s，格式=%s", len(image_data), mime_type)
        except Exception:
            logger.exception("图片压缩失败")
            return {"ok": False, "error": "图片过大（上限约 6 MB），请选择更小的图片", "drop": True}
    try:
        new_file_path = save_image_to_temp(image_data, postfix)
    except OSError:
        logger.exception("图片临时副本保存失败")
        return {"ok": False, "error": "图片无法保存，请检查磁盘空间与访问权限", "drop": True}

    return {
        "ok": True,
        "image_base64": base64.b64encode(image_data).decode("utf-8"),
        "mime_type": mime_type,
        "image_client_path": new_file_path,
    }
