from typing import TYPE_CHECKING
from ...utils.logger import get_logger
from ...vision.image_process import save_image, get_image_bytes_from_base64, get_postfix_by_mime
from ...agent.jargon_retriver import extract_song_entities
from ..chat_events import ChatInputEventType
if TYPE_CHECKING:
    from ..chat_events import ChatInputEvent
    from ...interface.service_hub import ServiceHub

logger = get_logger("Ingress")


def _ensure_data_uri_header(image_base64: str, postfix: str) -> str:
    if not image_base64:
        return image_base64
    if image_base64.startswith("data:image/"):
        return image_base64

    postfix_to_mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "bmp": "image/bmp",
    }
    mime = postfix_to_mime.get((postfix or "").lower(), "image/jpeg")
    return f"data:{mime};base64,{image_base64}"


async def ingress_message(service_hub: "ServiceHub", user_id: str, message: "ChatInputEvent"):
    '''
    原地对message进行转换，添加必要的字段。
    '''
    if service_hub is None:
        logger.error("ServiceHub is not set in ingress_message")
        return

    if message.event_type == ChatInputEventType.USER_IMAGE:
        await _process_image_message(service_hub, user_id, message) # 保存图片到本地，并调用图片描述

    song_entities = extract_song_entities(message.text)
    if song_entities:
        logger.debug(f"Extracted song entities from user input: {song_entities}")
        message.payload["terms"] = song_entities


async def _process_image_message(service_hub: "ServiceHub", user_id: str, message: "ChatInputEvent"):
    '''
    对图片消息进行处理，调用图片描述服务获取描述文本，并将其添加到message的payload中。
    '''
    payload = message.payload
    image_base64 = payload.get("image_base64")
    mime_type = payload.get("mime_type")
    if not image_base64 or not mime_type:
        logger.warning(f"Image message from {user_id} is missing image_base64 or mime_type")
        return
    logger.info(f"Agent handling image input for {user_id}")

    # 1. 获取图片字节，并保存图片到服务器
    image_bytes = get_image_bytes_from_base64(image_base64)
    if not image_bytes:
        logger.error(f"Failed to decode image bytes from base64 for {user_id}")
        return
    postfix = get_postfix_by_mime(mime_type)
    image_server_path = save_image(user_id, image_bytes, postfix)

    # 2. 将图片通过vlm模块转换为描述文本，并添加到对话中
    image_with_header = _ensure_data_uri_header(image_base64, postfix)
    image_description = await service_hub.agent.vision_module.describe_image(image_with_header)
    image_description = f"[一张图片]:{image_description}"
    message.text = image_description  # 将描述文本放入message.text，供后续处理使用
    payload["image_server_path"] = image_server_path