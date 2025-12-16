"""
src.llm.llm_api_interface.py
----------------------------
实现各种LLM API接口的统一调用接口
"""

from typing import Dict, List, Optional, Any, Tuple
from abc import ABC, abstractmethod
from ..utils.logger import get_logger
import os


class LLMAPIInterface(ABC):
    @abstractmethod
    def generate_response(self, prompt: str, **kwargs) -> str:
        """
        生成LLM的响应

        :param prompt: 用户输入的提示语
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


class SiliconFlowAPIInterface(
    LLMAPIInterface
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
            self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
            self.logger.info(f"硅基流动客户端初始化完成，模型: {self.model}")
        except Exception as e:
            self.logger.error(f"初始化硅基流动客户端失败: {e}")
            raise Exception(f"无法初始化硅基流动客户端: {e}")

    def generate_response(self, prompt: str, **kwargs) -> str:
        # 实现调用SiliconFlow API生成响应的逻辑
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                st_time = time.time()
                ret = self.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    **kwargs,
                )
                response = self._extract_content(ret)
                self.response_time_queue.append(time.time() - st_time)
                return response

            except Exception as e:
                last_exception = e
                self.logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    # 指数退避
                    delay = self.retry_delay * (2**attempt) + random.uniform(0, 1)
                    time.sleep(delay)

        # 所有重试都失败
        raise last_exception

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

    def _extract_content(self, response) -> str:
        """提取响应内容

        Args:
            response: API响应

        Returns:
            回复文本，在无法提取内容时返回空字符串并记录错误日志

        """
        try:
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                prompt_tokens = usage.prompt_tokens
                completion_tokens = usage.completion_tokens
                total_tokens = usage.total_tokens
                self.logger.debug(
                    f"Token usage - Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}"
                )
            else:
                self.logger.warning("无法获取token usage信息")

        except:
            self.logger.error("无法获取token usage信息")

        try:
            if hasattr(response, "choices") and response.choices:
                choice = response.choices[0]
                if hasattr(choice, "message") and hasattr(choice.message, "content"):
                    return choice.message.content or ""

            self.logger.warning("无法从响应中提取内容")
            return ""

        except Exception as e:
            self.logger.error(f"提取响应内容失败: {e}")
            return ""

    def get_interface_info(self) -> Dict[str, Any]:
        return {
            "name": "SiliconFlowAPIInterface",
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
基于Requests的LLM API接口实现
"""

import requests

class RequestsAPIInterface(LLMAPIInterface):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = get_logger(__name__)
        self._init_parameters()
        self.response_time_queue = deque(maxlen=20)  # 存储最近的响应时间

    def generate_response(self, prompt: str, **kwargs) -> str:
        # 实现调用SiliconFlow API生成响应的逻辑
        last_exception = None
        self.payload["messages"] = [{"role": "user", "content": prompt}]
        for attempt in range(self.max_retries):
            try:
                st_time = time.time()
                ret: requests.Response = requests.post(
                    self.url, headers=self.headers, json=self.payload, timeout=10
                )
                response = self._extract_content(ret)
                self.response_time_queue.append(time.time() - st_time)
                return response

            except Exception as e:
                last_exception = e
                self.logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")

                if attempt < self.max_retries - 1:
                    # 指数退避
                    delay = self.retry_delay * (2**attempt) + random.uniform(0, 1)
                    time.sleep(delay)

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

    def _extract_content(self, response: requests.Response) -> str:
        """提取响应内容

        Args:
            response: API响应

        Returns:
            回复文本，在无法提取内容时返回空字符串并记录错误日志

        """
        data = response.json()
        try:
            if data.get("usage"):
                usage = data["usage"]
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                self.logger.debug(
                    f"Token usage - Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}"
                )
            else:
                self.logger.warning("无法获取token usage信息")

        except:
            self.logger.error("无法获取token usage信息")

        try:
            if "choices" in data and data["choices"]:
                choice = data["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    return choice["message"]["content"] or ""

            self.logger.warning("无法从响应中提取内容")
            return ""

        except Exception as e:
            self.logger.error(f"提取响应内容失败: {e}")
            return ""

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
            return 0.0
        k = min(last_k, len(self.response_time_queue))
        return list(self.response_time_queue)[-k:]


"""
LLM API接口工厂
根据配置创建对应的LLM API接口实例
"""


class LLMAPIFactory:
    @staticmethod
    def create_interface(config: Dict[str, Any]) -> LLMAPIInterface:
        api_type = config.get("api_type", "siliconflow").lower()
        if api_type == "siliconflow":
            return SiliconFlowAPIInterface(config)
        elif api_type == "requests":
            return RequestsAPIInterface(config)
        else:
            raise ValueError(f"未知的LLM API类型: {api_type}")
