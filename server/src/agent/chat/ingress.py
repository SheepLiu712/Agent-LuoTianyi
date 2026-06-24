from typing import TYPE_CHECKING, List, Optional
from src.utils.logger import get_logger
from src.utils.vision.image_process import save_image, get_image_bytes_from_base64, get_postfix_by_mime
from src.subconscious.music_knowledge.jargon import extract_song_entities
from src.agent.chat.chat_events import ChatInputEvent, ChatInputEventType
import json

if TYPE_CHECKING:
    from src.agent.chat.chat_events import ChatInputEvent
    from src.system.system_runtime import SystemRuntime

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


async def ingress_message(system_runtime: "SystemRuntime", user_id: str, message: "ChatInputEvent"):
    '''
    原地对message进行转换，添加必要的字段。
    '''
    if system_runtime is None:
        logger.error("SystemRuntime is not set in ingress_message")
        return

    if message.event_type == ChatInputEventType.USER_IMAGE:
        await _process_image_message(system_runtime, user_id, message) # 保存图片到本地，并调用图片描述

    song_entities = extract_song_entities(message.text)
    if song_entities:
        logger.debug(f"Extracted song entities from user input: {song_entities}")
        message.payload["terms"] = song_entities


async def _process_image_message(system_runtime: "SystemRuntime", user_id: str, message: "ChatInputEvent"):
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
    image_description = await system_runtime.capabilities.image_understanding.describe_image(image_with_header)
    message.text = image_description  # 将描述文本放入message.text，供后续处理使用
    payload["image_server_path"] = image_server_path
    
async def extract_date_entities(user_input: str, llm_module) -> Optional[dict]:
    """
    使用LLM从用户输入中提取重要日期信息。
    如果检测到重要日期，返回结构化信息；否则返回None。
    """
    if not user_input or not llm_module:
        return None
    
    prompt = f"""请分析以下用户消息，判断其中是否提到了重要日期（如生日、纪念日、节日等）。
            如果提到了，请提取以下信息并以JSON格式返回：
            - name: 日期的名称（如"我的生日"、"结婚纪念日"）
            - type: 日期类型，必须是以下之一：生日、纪念日、节日、其他
            - date: 具体的日期（格式：MM-DD 或 YYYY-MM-DD，如果知道具体日期的话）
            - description: 简短描述（可选）

            如果用户消息中没有提到重要日期，请返回 null。

            用户消息：{user_input}

            只返回JSON或null，不要有其他内容。"""

    try:
        response = await llm_module.generate_response(
            character_name="助手",
            character_persona="你是一个帮助用户提取日期信息的助手。",
            speaking_style="简洁准确",
            user_persona="用户",
            conversation_history="",
            current_time="",
            reply_topic=prompt,
            sing_requirement="不需要唱歌",
            extra_knowledge=""
        )
        
        if not response:
            return None
        
        # 尝试解析JSON
        response = response.strip()
        if response.startswith("```"):
            # 移除markdown代码块
            lines = response.split("\n")
            response = "\n".join(lines[1:-1])
        
        result = json.loads(response)
        if result and isinstance(result, dict):
            logger.info(f"检测到重要日期: {result}")
            return result
        return None
        
    except json.JSONDecodeError as e:
        logger.warning(f"解析日期提取结果失败: {e}, 响应: {response}")
        return None
    except Exception as e:
        logger.error(f"提取日期实体时出错: {e}")
        return None
