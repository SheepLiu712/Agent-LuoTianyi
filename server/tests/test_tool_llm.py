from openai import OpenAI
import os
import sys
import json
cwd = os.getcwd()
sys.path.insert(0, str(cwd))


api_key = os.environ.get("QWEN_API_KEY", "您的 APIKEY"), # 从https://cloud.siliconflow.cn/account/ak获取
print(api_key)
client = OpenAI(
    api_key=os.environ.get("QWEN_API_KEY", "您的 APIKEY"), # 从https://cloud.siliconflow.cn/account/ak获取
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
        model="qwen3-max",
        messages=[
            {"role": "system", "content": "You are a helpful assistant designed to output JSON."},
            {"role": "user", "content": "? 2020 年世界奥运会乒乓球男子和女子单打冠军分别是谁? "
             "Please respond in the format {\"男子冠军\": ..., \"女子冠军\": ...}"}
        ],
        response_format={"type": "json_object"}
    )

print(response.choices[0].message.content)