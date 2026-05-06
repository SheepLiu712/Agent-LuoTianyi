"""
LLM tool test — validates OpenAI-compatible client configuration.
Skips if QWEN_API_KEY is not set (CI/debug environments).
"""

import json
import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

import pytest


@pytest.mark.skipif(
    not os.getenv("QWEN_API_KEY") or os.getenv("QWEN_API_KEY", "").startswith("$"),
    reason="QWEN_API_KEY not configured",
)
def test_llm_client_creates_response():
    from openai import OpenAI

    api_key = os.environ["QWEN_API_KEY"]
    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    response = client.chat.completions.create(
        model="qwen3-plus",
        messages=[
            {"role": "system", "content": "Output JSON."},
            {"role": "user", "content": 'Say {"hello": "world"} in JSON.'},
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    data = json.loads(content)
    assert "hello" in data
