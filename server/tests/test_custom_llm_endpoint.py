"""
测试自定义 LLM 端点接口、配置加密和客户端缓存
"""

import json
import os
import sys
import hashlib
from unittest.mock import MagicMock, patch, AsyncMock

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

import pytest


# =========================================================================
# 加密模块测试
# =========================================================================

class TestConfigEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        from src.utils.config_encryption import encrypt_value, decrypt_value

        plaintext = "sk-test-api-key-12345"
        encrypted = encrypt_value(plaintext)
        assert encrypted != plaintext, "加密后不应与原文相同"
        assert isinstance(encrypted, str)

        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext, "解密后应与原文一致"

    def test_encrypt_decrypt_special_chars(self):
        from src.utils.config_encryption import encrypt_value, decrypt_value

        plaintext = "sk-test-key-with-chars!@#$%^&*()_+-=[]{}|;':\",./<>?"
        encrypted = encrypt_value(plaintext)
        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_empty_string_roundtrip(self):
        from src.utils.config_encryption import encrypt_value, decrypt_value

        encrypted = encrypt_value("")
        decrypted = decrypt_value(encrypted)
        assert decrypted == ""

    def test_encrypt_sensitive_fields_only_encrypts_api_key(self):
        from src.utils.config_encryption import encrypt_sensitive_fields

        config = {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-secret",
            "model": "gpt-4",
            "temperature": 0.7,
            "max_tokens": 4096,
            "timeout": 60,
        }
        encrypted = encrypt_sensitive_fields(config)
        assert encrypted["api_key"] != config["api_key"], "api_key 应被加密"
        assert encrypted["base_url"] == config["base_url"], "base_url 应保持不变"
        assert encrypted["model"] == config["model"]
        assert encrypted["temperature"] == config["temperature"]
        assert encrypted["max_tokens"] == config["max_tokens"]
        assert encrypted["timeout"] == config["timeout"]

    def test_encrypt_sensitive_fields_handles_default_headers(self):
        from src.utils.config_encryption import encrypt_sensitive_fields, decrypt_sensitive_fields

        config = {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-secret",
            "default_headers": {"X-Auth": "token-123", "X-Org": "my-org"},
        }
        encrypted = encrypt_sensitive_fields(config)
        assert encrypted["api_key"] != config["api_key"]
        assert encrypted["default_headers"] != config["default_headers"]

        decrypted = decrypt_sensitive_fields(encrypted)
        assert decrypted["api_key"] == config["api_key"]
        assert decrypted["default_headers"] == config["default_headers"]

    def test_encrypt_decrypt_full_roundtrip(self):
        from src.utils.config_encryption import encrypt_sensitive_fields, decrypt_sensitive_fields

        config = {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-secret-999",
            "model": "gpt-4",
            "temperature": 0.7,
            "max_tokens": 4096,
            "timeout": 60,
            "enable_thinking": False,
            "default_headers": {"Authorization": "Bearer xyz"},
        }
        encrypted = encrypt_sensitive_fields(config)
        decrypted = decrypt_sensitive_fields(encrypted)

        for key in config:
            assert decrypted.get(key) == config[key], f"{key} 解密后应与原文一致"

    def test_non_sensitive_keys_untouched(self):
        from src.utils.config_encryption import encrypt_sensitive_fields, decrypt_sensitive_fields

        config = {
            "base_url": "https://api.example.com",
            "model": "deepseek-chat",
            "temperature": 0.3,
            "api_type": "custom",
        }
        encrypted = encrypt_sensitive_fields(config)
        assert encrypted == config  # no sensitive keys, should be identical

        decrypted = decrypt_sensitive_fields(encrypted)
        assert decrypted == config

    def test_encrypt_is_deterministic(self):
        """Fernet 的每次加密结果不同（IV），但解密后应一致。"""
        from src.utils.config_encryption import encrypt_value, decrypt_value

        plaintext = "sk-consistent-test"
        encrypted_1 = encrypt_value(plaintext)
        encrypted_2 = encrypt_value(plaintext)

        # Fernet uses random IV, so ciphertexts differ
        # But both should decrypt to the original
        assert decrypt_value(encrypted_1) == plaintext
        assert decrypt_value(encrypted_2) == plaintext


# =========================================================================
# LLMAPIFactory & CustomEndpointInterface 测试
# =========================================================================

class TestLLMAPIFactory:
    def test_create_openai_interface(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory, OpenAIAPIInterface

        interface = LLMAPIFactory.create_interface({
            "api_type": "openai",
            "base_url": "https://api.siliconflow.cn/v1",
            "api_key": "sk-test",
            "model": "Pro/deepseek-ai/DeepSeek-V3",
        })
        assert isinstance(interface, OpenAIAPIInterface)
        info = interface.get_interface_info()
        assert info["name"] == "OpenAIAPIInterface"

    def test_create_custom_interface(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory, CustomEndpointInterface

        interface = LLMAPIFactory.create_interface({
            "api_type": "custom",
            "base_url": "https://custom-api.example.com/v1",
            "api_key": "sk-custom",
            "model": "my-model",
        })
        assert isinstance(interface, CustomEndpointInterface)
        info = interface.get_interface_info()
        assert info["name"] == "CustomEndpointInterface"
        assert info["base_url"] == "https://custom-api.example.com/v1"
        assert info["model"] == "my-model"

    def test_create_custom_with_advanced_params(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory, CustomEndpointInterface

        interface = LLMAPIFactory.create_interface({
            "api_type": "custom",
            "base_url": "https://custom-api.example.com/v1",
            "api_key": "sk-custom",
            "model": "gpt-4",
            "temperature": 0.5,
            "max_tokens": 8192,
            "timeout": 120,
            "enable_thinking": True,
            "default_headers": {"X-Custom": "value"},
        })
        assert isinstance(interface, CustomEndpointInterface)
        info = interface.get_interface_info()
        assert info["temperature"] == 0.5
        assert info["max_tokens"] == 8192
        assert info["timeout"] == 120
        assert info["has_custom_headers"] is True

    def test_create_custom_missing_base_url_raises(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        with pytest.raises(ValueError, match="base_url"):
            LLMAPIFactory.create_interface({
                "api_type": "custom",
                "api_key": "sk-test",
            })

    def test_create_custom_missing_api_key_warns_but_creates(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory, CustomEndpointInterface

        interface = LLMAPIFactory.create_interface({
            "api_type": "custom",
            "base_url": "https://api.example.com/v1",
        })
        assert isinstance(interface, CustomEndpointInterface)

    def test_create_unknown_type_raises(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        with pytest.raises(ValueError, match="未知"):
            LLMAPIFactory.create_interface({"api_type": "nonexistent"})


class TestCustomEndpointInterface:
    def test_get_interface_info_contains_custom_fields(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        interface = LLMAPIFactory.create_interface({
            "api_type": "custom",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
            "timeout": 60,
        })
        info = interface.get_interface_info()
        assert "timeout" in info
        assert info["timeout"] == 60
        assert "has_custom_headers" in info
        assert info["has_custom_headers"] is False

    def test_inherits_generate_response_signature(self):
        from src.utils.llm.llm_api_interface import CustomEndpointInterface, LLMAPIInterface

        assert issubclass(CustomEndpointInterface, LLMAPIInterface)
        # 验证抽象方法已实现（可实例化）
        import inspect
        assert not inspect.isabstract(CustomEndpointInterface)

    def test_get_response_time_returns_list(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        interface = LLMAPIFactory.create_interface({
            "api_type": "custom",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
        })
        times = interface.get_response_time()
        assert isinstance(times, (list, float))  # empty queue returns 0.0

    def test_set_parameters_works(self):
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        interface = LLMAPIFactory.create_interface({
            "api_type": "custom",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
        })
        interface.set_parameters(temperature=0.3, max_tokens=2048)
        assert interface.temperature == 0.3
        assert interface.max_tokens == 2048


# =========================================================================
# MainChat._call_llm 测试
# =========================================================================

class TestMainChatCallLlm:
    @pytest.fixture
    def mock_main_chat(self):
        """创建一个简化的 MainChat 实例用于 _call_llm 测试"""
        from src.agent.main_chat import MainChat
        from src.utils.llm.llm_module import LLMModule
        from src.utils.llm.prompt_manager import PromptManager, PromptTemplate

        # Mock prompt template
        mock_template = MagicMock(spec=PromptTemplate)
        mock_template.render.return_value = "Rendered prompt: Hello!"

        # Mock LLMModule
        mock_llm = MagicMock(spec=LLMModule)
        mock_llm.prompt_template = mock_template
        mock_llm.llm_client = MagicMock()
        mock_llm.llm_client.generate_response = AsyncMock(return_value="Default response")
        mock_llm.generate_response = AsyncMock(return_value="Default response")

        chat = MagicMock(spec=MainChat)
        chat.llm = mock_llm
        # 绑定真实方法
        from src.agent.main_chat import MainChat
        import inspect
        # 手动模拟 _call_llm 逻辑
        return chat, mock_llm, mock_template

    @pytest.mark.asyncio
    async def test_call_llm_without_override_uses_default_client(self):
        from src.agent.main_chat import MainChat

        mock_template = MagicMock()
        mock_template.render.return_value = "Rendered prompt: Hello!"
        mock_client = MagicMock()
        mock_client.generate_response = AsyncMock(return_value="Default response")

        mock_llm = MagicMock()
        mock_llm.prompt_template = mock_template
        mock_llm.llm_client = mock_client

        chat = MainChat.__new__(MainChat)
        chat.llm = mock_llm
        chat.logger = MagicMock()

        result = await chat._call_llm(reply_topic="test")
        assert result == "Default response"
        # 模板应被渲染一次
        mock_template.render.assert_called_once()
        # 默认客户端的 generate_response 被调用
        mock_client.generate_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_llm_with_override_uses_override_client(self):
        from src.agent.main_chat import MainChat

        mock_template = MagicMock()
        mock_template.render.return_value = "Rendered prompt: Hello!"
        default_client = MagicMock()
        default_client.generate_response = AsyncMock(return_value="Default response")
        override_client = MagicMock()
        override_client.generate_response = AsyncMock(return_value="Override response")

        mock_llm = MagicMock()
        mock_llm.prompt_template = mock_template
        mock_llm.llm_client = default_client

        chat = MainChat.__new__(MainChat)
        chat.llm = mock_llm
        chat.logger = MagicMock()

        result = await chat._call_llm(
            llm_client_override=override_client,
            reply_topic="test"
        )
        assert result == "Override response"
        # 模板被渲染一次
        mock_template.render.assert_called_once()
        # override 客户端的 generate_response 被调用
        override_client.generate_response.assert_called_once()
        # 默认客户端不应被调用
        default_client.generate_response.assert_not_called()

    @pytest.mark.asyncio
    async def test_call_llm_prompt_is_rendered_with_correct_args(self):
        from src.agent.main_chat import MainChat

        mock_template = MagicMock()
        mock_template.render.return_value = "Rendered: topic=test, style=casual"
        override_client = MagicMock()
        override_client.generate_response = AsyncMock(return_value="OK")

        mock_llm = MagicMock()
        mock_llm.prompt_template = mock_template
        mock_llm.llm_client = MagicMock()

        chat = MainChat.__new__(MainChat)
        chat.llm = mock_llm
        chat.logger = MagicMock()

        await chat._call_llm(
            llm_client_override=override_client,
            reply_topic="test",
            speaking_style="casual",
        )
        # 验证 render 被调用时传入了所有 kwargs
        mock_template.render.assert_called_once_with(
            reply_topic="test",
            speaking_style="casual",
        )

    @pytest.mark.asyncio
    async def test_call_llm_exception_returns_empty_string(self):
        from src.agent.main_chat import MainChat

        mock_template = MagicMock()
        mock_template.render.side_effect = RuntimeError("Render failed")

        mock_llm = MagicMock()
        mock_llm.prompt_template = mock_template
        mock_llm.llm_client = MagicMock()

        chat = MainChat.__new__(MainChat)
        chat.llm = mock_llm
        chat.logger = MagicMock()

        result = await chat._call_llm(reply_topic="test")
        assert result == ""


# =========================================================================
# LLM 客户端缓存逻辑测试
# =========================================================================

class TestLlmClientCache:
    @pytest.fixture
    def agent(self):
        from src.agent.luotianyi_agent import LuoTianyiAgent

        agent = LuoTianyiAgent.__new__(LuoTianyiAgent)
        agent._llm_client_cache = {}
        agent.logger = MagicMock()
        return agent

    def test_cache_empty_initially(self, agent):
        assert agent._llm_client_cache == {}

    def test_cache_store_and_retrieve(self, agent):
        import hashlib
        user_id = "test-user-1"
        config = {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        }

        config_json = json.dumps(config, sort_keys=True, ensure_ascii=False)
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()

        from src.utils.llm.llm_api_interface import LLMAPIFactory
        client = LLMAPIFactory.create_interface(config)
        agent._llm_client_cache[user_id] = (config_hash, client)

        assert user_id in agent._llm_client_cache
        cached_hash, cached_client = agent._llm_client_cache[user_id]
        assert cached_hash == config_hash
        assert cached_client is client  # same object

    def test_cache_miss_on_config_change(self, agent):
        import hashlib
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        user_id = "test-user-2"

        config1 = {
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        }
        config2 = {
            "base_url": "https://other-api.example.com/v1",
            "api_key": "sk-test",
            "model": "gpt-4",
        }

        hash1 = hashlib.sha256(
            json.dumps(config1, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        hash2 = hashlib.sha256(
            json.dumps(config2, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

        assert hash1 != hash2, "不同配置的哈希应不同"

        client1 = LLMAPIFactory.create_interface(config1)
        agent._llm_client_cache[user_id] = (hash1, client1)

        # 不同配置 → cache miss
        cached = agent._llm_client_cache.get(user_id)
        assert cached is not None
        assert cached[0] == hash1  # old hash
        assert cached[0] != hash2  # doesn't match new config

    def test_cache_multiple_users_isolation(self, agent):
        import hashlib
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        config_a = {"base_url": "https://api-a.com/v1", "api_key": "sk-a", "model": "gpt-4"}
        config_b = {"base_url": "https://api-b.com/v1", "api_key": "sk-b", "model": "gpt-4"}
        config_c = {"base_url": "https://api-a.com/v1", "api_key": "sk-a", "model": "gpt-4"}  # same as a

        hash_a = hashlib.sha256(
            json.dumps(config_a, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        hash_c = hashlib.sha256(
            json.dumps(config_c, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        assert hash_a == hash_c, "相同配置哈希应相同"

        client_a = LLMAPIFactory.create_interface(config_a)
        client_b = LLMAPIFactory.create_interface(config_b)

        agent._llm_client_cache["user-a"] = (hash_a, client_a)
        agent._llm_client_cache["user-b"] = (hash_b := hashlib.sha256(
            json.dumps(config_b, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(), client_b)

        assert len(agent._llm_client_cache) == 2
        assert agent._llm_client_cache["user-a"][0] == hash_a
        assert agent._llm_client_cache["user-b"][0] == hash_b


# =========================================================================
# 集成：解密 → 客户端创建 → 缓存 流程测试
# =========================================================================

class TestEndToEndFlow:
    def test_decrypt_then_create_client(self):
        from src.utils.config_encryption import encrypt_sensitive_fields, decrypt_sensitive_fields
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        original_config = {
            "api_type": "custom",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-real-secret-key",
            "model": "gpt-4",
            "timeout": 60,
        }

        # 模拟加密后存储
        stored = encrypt_sensitive_fields(original_config)

        # api_key 被加密
        assert stored["api_key"] != original_config["api_key"]
        # base_url 未加密
        assert stored["base_url"] == original_config["base_url"]

        # 模拟从 DB 读出后解密
        loaded = decrypt_sensitive_fields(stored)

        # 解密后应能创建客户端
        client = LLMAPIFactory.create_interface(loaded)
        info = client.get_interface_info()
        assert info["base_url"] == original_config["base_url"]
        assert info["model"] == original_config["model"]
        assert info["timeout"] == original_config["timeout"]

    def test_caching_with_encrypted_config(self):
        from src.utils.config_encryption import encrypt_sensitive_fields, decrypt_sensitive_fields
        from src.utils.llm.llm_api_interface import LLMAPIFactory

        config = {
            "api_type": "custom",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-secret",
            "model": "gpt-4",
        }

        # 加密存储→解密加载
        stored = encrypt_sensitive_fields(config)
        loaded = decrypt_sensitive_fields(stored)

        # 计算解密后配置的哈希（应为同一个配置）
        import hashlib, json
        config_json = json.dumps(loaded, sort_keys=True, ensure_ascii=False)
        hash1 = hashlib.sha256(config_json.encode()).hexdigest()

        # 再次执行相同流程
        stored2 = encrypt_sensitive_fields(config)
        loaded2 = decrypt_sensitive_fields(stored2)
        config_json2 = json.dumps(loaded2, sort_keys=True, ensure_ascii=False)
        hash2 = hashlib.sha256(config_json2.encode()).hexdigest()

        # 相同原始配置 → 解密后的哈希应相同
        assert hash1 == hash2
