"""
src.llm.llm_api_interface.py
----------------------------
实现各种LLM API接口的统一调用接口
"""

from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod
from src.utils.logger import get_logger
from src.domain.tool_type import MyTool
from typing import List, Dict, Any
import json
import os
import asyncio


class VLMAPIInterface(ABC):
    @abstractmethod
    async def generate_response(self, prompt: str, image_base64: str, **kwargs) -> str:
        """
        生成LLM的响应 (异步)

        :param prompt: 用户输入的提示语
        :param image_base64: 输入的图像的Base64编码
        :param kwargs: 其他可选参数
        :return: LLM生成的响应文本
        """
        pass

    @abstractmethod
    def set_parameters(self, **params) -> None:
        """
        设置LLM的参数

        :param params: 参数键值对
        """
        pass

    @abstractmethod
    def get_interface_info(self) -> Dict[str, Any]:
        """
        获取接口的基本信息

        :return: 包含接口信息的字典
        """
        pass

    @abstractmethod
    def get_response_time(self, last_k: int) -> List[float]:
        """
        获取最近请求的响应时间

        :return: 响应时间，单位为秒
        """
        pass


"""
硅基流动API接口实现
"""
from openai import OpenAI
from collections import deque
import time
import random


class OpenAIAPIInterface(
    VLMAPIInterface
):  # 这个东西本质上调用的是openai的接口，如果之后需要使用openai的其他模型，可以直接用这个类（原样继承）
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = get_logger(__name__)
        self._init_parameters()
        self.response_time_queue = deque(maxlen=20)  # 存储最近的响应时间
        
        # 检查 SSL_CERT_FILE 环境变量，如果指向的文件不存在，则移除该环境变量，防止 httpx/ssl 报错
        ssl_cert_file = os.environ.get("SSL_CERT_FILE")
        if ssl_cert_file and not os.path.exists(ssl_cert_file):
            self.logger.warning(f"检测到 SSL_CERT_FILE 环境变量指向不存在的文件: {ssl_cert_file}。正在移除该环境变量以避免错误。")
            del os.environ["SSL_CERT_FILE"]

        try:
            # 兼容同步和异步调用：如果需要异步，应使用 AsyncOpenAI
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            self.logger.info(f"OpenAI客户端初始化完成，模型: {self.model}")
        except Exception as e:
            self.logger.error(f"初始化OpenAI客户端失败: {e}")
            raise Exception(f"无法初始化OpenAI客户端: {e}")

    async def generate_response(self, prompt: str, image_base64: str, **kwargs) -> str:
        """
        使用 asyncio.to_thread 包装阻塞的同步调用
        """
        # 实现调用SiliconFlow API生成响应的逻辑
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                st_time = time.time()
                
                # 定义一个同步函数来执行实际的阻塞调用
                def _do_request(messages: List):
                    return self.client.chat.completions.create(
                        messages=messages,
                        model=self.model,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        top_p=self.top_p,  
                        **kwargs,
                    )
                payload_url = image_base64
                # print("Payload URL:", payload_url[:50] + "...")  # 打印前50个字符以避免日志过长
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt,
                            },
                            {
                                "type":"image_url",
                                "image_url": {
                                    "url": payload_url,
                                    "detail": "auto"
                                }
                            }
                        ],
                    },
                ]
                # 放入线程池执行
                ret = await asyncio.to_thread(_do_request, messages)
                
                elapsed = time.time() - st_time
                extracted = self._extract_content(ret, elapsed=elapsed)
                self.response_time_queue.append(elapsed)
                return extracted

            except Exception as e:
                last_exception = e
                self.logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    # 异步等待
                    delay = self.retry_delay * (2**attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)

        # 所有重试都失败
        self.logger.error(f"Generate response failed after {self.max_retries} retries.")
        raise last_exception if last_exception else Exception("Unknown error")
        

    def set_parameters(self, **params) -> None:
        # 设置参数
        for key, value in params.items():
            setattr(self, key, value)

    def _init_parameters(self):
        # 初始化默认参数
        self.base_url = self.config.get("base_url", "https://api.siliconflow.cn/v1")
        self.api_key = self.config.get("api_key") or os.environ.get("SILICONFLOW_API_KEY")
        if not self.api_key:
            self.logger.error("未提供硅基流动API密钥，无法正常调用API。")
            raise ValueError("缺少硅基流动API密钥")

        self.model = self.config.get("model", "Pro/deepseek-ai/DeepSeek-V3")
        self.temperature = self.config.get("temperature", 0.7)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.top_p = self.config.get("top_p", 0.9)

        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 0.5)

    
    def _extract_content(self, response, elapsed: float = 0.0) -> Dict[str, Any]:
        """提取响应内容、token 用量和响应用时

        Args:
            response: API 响应（OpenAI SDK 返回的对象）
            elapsed: 从发起请求到收到响应所经过的时间（秒），由调用方传入

        Returns:
            {"content": str, "usage": Optional[dict], "response_time_s": float}
        """
        # 尝试从响应对象中提取服务器侧用时（毫秒）
        server_time_s: Optional[float] = None
        for attr in ("response_ms", "response_time", "timing"):
            val = getattr(response, attr, None)
            if val is not None:
                try:
                    server_time_s = float(val)
                    break
                except (TypeError, ValueError):
                    pass

        usage_dict: Optional[Dict[str, int]] = None
        try:
            if hasattr(response, "usage") and response.usage:
                usage_obj = response.usage
                prompt_tokens = getattr(usage_obj, "prompt_tokens", 0)
                completion_tokens = getattr(usage_obj, "completion_tokens", 0)
                total_tokens = getattr(usage_obj, "total_tokens", 0)
                usage_dict = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
                self.logger.debug(
                    f"Token usage - Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}"
                )
                if server_time_s is None:
                    server_time_s = getattr(usage_obj, "completion_time", None) or getattr(usage_obj, "total_time", None)
            else:
                self.logger.warning("无法获取token usage信息")
        except Exception:
            self.logger.error("无法获取token usage信息", exc_info=True)

        if server_time_s is not None:
            try:
                response_time_s = float(server_time_s)
                if response_time_s > 1000:
                    response_time_s = response_time_s / 1000.0
            except (TypeError, ValueError):
                response_time_s = elapsed
        else:
            response_time_s = elapsed

        content = ""
        try:
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and hasattr(choice.message, "content"):
                    content = choice.message.content or ""
            else:
                self.logger.warning("无法从响应中提取内容")
        except Exception as e:
            self.logger.error(f"提取响应内容失败: {e}")

        return {
            "content": content,
            "usage": usage_dict,
            "response_time_s": response_time_s,
        }
        
    def _extract_tool_calls(self, response) -> List:
        try:
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and hasattr(choice.message, "tool_calls"):
                    return choice.message.tool_calls or []

            self.logger.warning("无法从响应中提取工具调用信息")
            return []
        except Exception as e:
            self.logger.error(f"提取工具调用信息失败: {e}")
            return []

    def get_interface_info(self) -> Dict[str, Any]:
        return {
            "name": "OpenAIAPIInterface",
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
        }

    def get_response_time(self, last_k: int = 1) -> List[float]:
        if not self.response_time_queue:
            return 0.0
        k = min(last_k, len(self.response_time_queue))
        return list(self.response_time_queue)[-k:]




"""
VLM API接口工厂
根据配置创建对应的VLM API接口实例
"""


class VLMAPIFactory:
    @staticmethod
    def create_interface(config: Dict[str, Any]) -> VLMAPIInterface:
        api_type = config.get("api_type", "openai").lower()
        if api_type == "openai":
            return OpenAIAPIInterface(config)
        else:
            raise ValueError(f"未知的VLM API类型: {api_type}")
