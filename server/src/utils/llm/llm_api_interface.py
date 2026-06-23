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


class LLMAPIInterface(ABC):
    default_parameters: Dict[str, Any] = {}
    @abstractmethod
    async def generate_response(self, prompt: str, params: Dict[str, Any], enable_thinking: bool = False, use_json: bool = False, **kwargs) -> Dict[str, Any]:
        """
        生成LLM的响应 (异步)

        :param prompt: 用户输入的提示语
        :param params: 生成响应所需的参数
        :param enable_thinking: 是否启用思考过程
        :param use_json: 是否使用JSON格式输出
        :return: 包含生成文本、token用量和响应时间等信息的字典
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
from threading import Lock


class OpenAIAPIInterface(LLMAPIInterface):  
    '''
    实现了LLMAPIInterface接口，使用OpenAI Python SDK调用硅基流动API
    '''
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = get_logger(__name__)
        self.default_parameters = {}
        self._init_parameters()
        
        # 检查 SSL_CERT_FILE 环境变量，如果指向的文件不存在，暂移除该环境变量
        # 避免 httpx/ssl 报错。临时操作不影响其他模块。
        self._ssl_cert_file = os.environ.get("SSL_CERT_FILE")
        self._ssl_cert_file_removed = False
        if self._ssl_cert_file and not os.path.exists(self._ssl_cert_file):
            self.logger.warning(f"SSL_CERT_FILE 指向不存在的文件: {self._ssl_cert_file}，暂时移除。")
            del os.environ["SSL_CERT_FILE"]
            self._ssl_cert_file_removed = True

        try:
            # 兼容同步和异步调用
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            self.logger.info(f"OpenAI客户端初始化完成，模型: {self.model}")
        except Exception as e:
            self.logger.error(f"初始化OpenAI客户端失败: {e}")
            raise Exception(f"无法初始化OpenAI客户端: {e}")
        finally:
            if self._ssl_cert_file_removed:
                os.environ["SSL_CERT_FILE"] = self._ssl_cert_file

    async def generate_response(self, prompt: str, params: Dict[str, Any], enable_thinking: bool = False, use_json: bool = False, **kwargs) -> Dict[str, Any]:
        """
        使用 asyncio.to_thread 包装阻塞的同步调用
        """
        last_exception = None
        kwargs = kwargs or {}
        params = params or {}
        if enable_thinking and self.can_enable_thinking:
            kwargs["extra_body"] = {"enable_thinking": True}
        if use_json and self.can_use_json:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                st_time = time.time()
                
                # 定义一个同步函数来执行实际的阻塞调用
                def _do_request(messages: List, use_json: bool):
                    return self.client.chat.completions.create(
                        messages=messages,
                        model=self.model,
                        max_tokens=params.get("max_tokens", self.default_parameters.get("max_tokens", 8192)),
                        temperature=params.get("temperature", self.default_parameters.get("temperature", 0.7)),
                        top_p=params.get("top_p", self.default_parameters.get("top_p", 0.9)),
                        **kwargs,
                    )
                
                # 放入线程池执行
                ret = await asyncio.to_thread(_do_request, [{"role": "system", "content": prompt}], use_json)
                
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
        self.api_key = self.config.get("api_key")
        if not self.api_key:
            self.logger.error("未提供API密钥，无法正常调用API。")
            raise ValueError("缺少API密钥")

        self.model = self.config.get("model", "Pro/deepseek-ai/DeepSeek-V3")
        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 0.5)
        self.can_enable_thinking = self.config.get("can_enable_thinking", False)
        self.can_use_json = self.config.get("can_use_json", False)

        self.default_parameters = self.config.get("default_params", {})

    
    def _extract_content(self, response, elapsed: float = 0.0) -> Dict[str, Any]:
        """提取响应内容、token 用量和响应用时

        Args:
            response: API 响应（OpenAI SDK 返回的对象）
            elapsed: 从发起请求到收到响应所经过的时间（秒），由调用方传入

        Returns:
            {"content": str, "usage": Optional[dict], "response_time_s": float}
            content 为回复文本，无法提取时为空字符串；
            usage 包含 prompt_tokens / completion_tokens / total_tokens；
            response_time_s 为响应用时，无法获取时回退到 elapsed 参数值
        """

        # 尝试从响应对象中提取服务器侧用时（毫秒），不同厂商字段名可能不同
        server_time_s: Optional[float] = None
        for attr in ("response_ms", "response_time", "timing"):
            val = getattr(response, attr, None)
            if val is not None:
                try:
                    server_time_s = float(val)  # 假设为毫秒，下面统一处理
                    break
                except (TypeError, ValueError):
                    pass

        # 有的 API 将毫秒级值存储在 usage 扩展字段中
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

                # 某些厂商把时间埋在用量的额外字段里
                if server_time_s is None:
                    server_time_s = getattr(usage_obj, "completion_time", None) or getattr(usage_obj, "total_time", None)
            else:
                self.logger.warning("无法获取token usage信息")
        except Exception:
            self.logger.error("无法获取token usage信息", exc_info=True)

        # 优先使用服务器返回的时间，否则回退到调用方传入的 elapsed
        if server_time_s is not None:
            try:
                response_time_s = float(server_time_s)
                # 如果数值很大（> 1000），可能是毫秒级
                if response_time_s > 1000:
                    response_time_s = response_time_s / 1000.0
            except (TypeError, ValueError):
                response_time_s = elapsed
        else:
            response_time_s = elapsed

        # 提取文本内容
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
            "temperature": self.default_parameters.get("temperature"),
            "max_tokens": self.default_parameters.get("max_tokens"),
            "top_p": self.default_parameters.get("top_p"),
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
        }



"""
基于Requests的LLM API接口实现
"""

import requests

class RequestsAPIInterface(LLMAPIInterface):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = get_logger(__name__)
        self._init_parameters()
        self.response_time_queue = deque(maxlen=20)  # 存储最近的响应时间

    async def generate_response(self, prompt: str, use_json: bool = False, **kwargs) -> str:
        # 实现调用SiliconFlow API生成响应的逻辑
        last_exception = None
        self.payload["messages"] = [{"role": "user", "content": prompt}]
        if use_json:
            self.payload["response_format"] = {"type": "json_object"}
        for attempt in range(self.max_retries):
            try:
                st_time = time.time()

                def _do_request():
                    return requests.post(
                        self.url, headers=self.headers, json=self.payload, timeout=10
                    )

                ret = await asyncio.to_thread(_do_request)
                elapsed = time.time() - st_time
                extracted = self._extract_content(ret, elapsed=elapsed)
                self.response_time_queue.append(elapsed)
                return extracted

            except Exception as e:
                last_exception = e
                self.logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2**attempt) + random.uniform(0, 1)
                    await asyncio.sleep(delay)

        # 所有重试都失败
        raise last_exception

    def set_parameters(self, **params) -> None:
        # 设置参数
        for key, value in params.items():
            setattr(self, key, value)

    def _init_parameters(self):
        # 初始化默认参数
        self.url = self.config.get("url", "")
        self.api_key = self.config.get("api_key")
        if not self.api_key:
            self.logger.error("未提供硅基流动API密钥，无法正常调用API。")
            raise ValueError("缺少硅基流动API密钥")

        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }

        self.model = self.config.get("model", "Pro/deepseek-ai/DeepSeek-V3")
        self.temperature = self.config.get("temperature", 0.7)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self.top_p = self.config.get("top_p", 0.9)
        self.stream = self.config.get("stream", False)
        self.payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "messages": None,
            "n": 1,
            "stream": self.stream,
        }

        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 0.5)

    def _extract_content(self, response: requests.Response, elapsed: float = 0.0) -> Dict[str, Any]:
        """提取响应内容、token 用量和响应用时

        Args:
            response: requests.Response 对象
            elapsed: 从发起请求到收到响应所经过的时间（秒），由调用方传入

        Returns:
            {"content": str, "usage": Optional[dict], "response_time_s": float}
        """
        data = response.json()
        usage_dict: Optional[Dict[str, int]] = None
        response_time_s: float = elapsed

        # 尝试提取 token 用量
        try:
            if data.get("usage"):
                usage = data["usage"]
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                usage_dict = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                }
                self.logger.debug(
                    f"Token usage - Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}"
                )
                # 某些厂商把服务器耗时埋在用量的额外字段里
                server_time_ms = usage.get("completion_time") or usage.get("total_time")
                if server_time_ms is not None:
                    try:
                        server_time_ms = float(server_time_ms)
                        if server_time_ms > 1000:
                            response_time_s = server_time_ms / 1000.0
                        else:
                            response_time_s = server_time_ms
                    except (TypeError, ValueError):
                        pass
            else:
                self.logger.warning("无法获取token usage信息")
        except Exception:
            self.logger.error("无法获取token usage信息", exc_info=True)

        # 提取文本内容
        content = ""
        try:
            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    content = choice["message"]["content"] or ""
            else:
                self.logger.warning("无法从响应中提取内容")
        except Exception as e:
            self.logger.error(f"提取响应内容失败: {e}")

        return {
            "content": content,
            "usage": usage_dict,
            "response_time_s": response_time_s,
        }

    def get_interface_info(self) -> Dict[str, Any]:
        return {
            "name": "RequestsAPIInterface",
            "model": self.model,
            "url": self.url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
        }

    def get_response_time(self, last_k: int = 1) -> List[float]:
        if not self.response_time_queue:
            return []
        k = min(last_k, len(self.response_time_queue))
        return list(self.response_time_queue)[-k:]


"""
LLM API接口工厂
根据配置创建对应的LLM API接口实例
"""


class LLMAPIFactory:
    _client_cache: Dict[str, LLMAPIInterface] = {}
    _cache_lock = Lock()

    @staticmethod
    def _make_cache_key(config: Dict[str, Any]) -> str:
        try:
            return json.dumps(config, sort_keys=True, default=str)
        except Exception:
            return repr(sorted(config.items(), key=lambda item: item[0]))

    @staticmethod
    def create_interface(config: Dict[str, Any]) -> LLMAPIInterface:
        if config.get("cache_client", True):
            key = LLMAPIFactory._make_cache_key(config)
            with LLMAPIFactory._cache_lock:
                cached = LLMAPIFactory._client_cache.get(key)
                if cached is not None:
                    return cached
                client = LLMAPIFactory._create_interface_uncached(config)
                LLMAPIFactory._client_cache[key] = client
                return client

        return LLMAPIFactory._create_interface_uncached(config)

    @staticmethod
    def _create_interface_uncached(config: Dict[str, Any]) -> LLMAPIInterface:
        api_type = config.get("api_type", "openai").lower()
        if api_type == "openai":
            return OpenAIAPIInterface(config)
        if api_type == "requests":
            return RequestsAPIInterface(config)
        raise ValueError(f"未知的LLM API类型: {api_type}")
