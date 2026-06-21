#!/usr/bin/env python
# coding: utf-8

import argparse
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI


def read_text_auto(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 <歌名>.clear.lrc 输入 LLM，生成 <歌名>.llm.lrc"
    )
    parser.add_argument(
        "--song_dir",
        required=True,
        help="歌曲目录，目录中应包含 <歌名>.clear.lrc",
    )
    parser.add_argument(
        "--prompt_json",
        default="res/song_learner/re_segment_prompt.json",
        help="Prompt 配置文件路径，默认 res/song_learner/re_segment_prompt.json",
    )
    parser.add_argument(
        "--model",
        default="qwen3.5-plus",
        help="LLM 模型名，默认 qwen3.5-plus",
    )
    parser.add_argument(
        "--base_url",
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        help="OpenAI 兼容接口 base_url",
    )
    parser.add_argument(
        "--enable_thinking",
        action="store_true",
        default=True,
        help="是否启用思考模式，通过 extra_body 传递",
    )
    return parser.parse_args()


def ensure_exists(path: Path, desc: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{desc}不存在: {path}")


def load_prompt_template(prompt_json_path: Path) -> str:
    raw = read_text_auto(prompt_json_path)
    payload = json.loads(raw)
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"prompt 字段缺失或为空: {prompt_json_path}")
    if "{{ lyrics }}" not in prompt:
        raise ValueError("prompt 中未包含占位符 {{ lyrics }}")
    return prompt


def build_prompt(template: str, lyrics_text: str) -> str:
    return template.replace("{{ lyrics }}", lyrics_text)


def extract_text_from_response(response: Any) -> str:
    # 优先兼容 chat.completions 返回格式
    if hasattr(response, "choices") and response.choices:
        message = response.choices[0].message
        content = message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    parts.append(text)
            if parts:
                return "\n".join(parts).strip()

    # 兼容少数 SDK 的 output_text 字段
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    raise RuntimeError("无法从 LLM 响应中提取文本内容")


def call_llm(
    model: str,
    api_key: str,
    base_url: str,
    enable_thinking: bool,
    prompt: str,
) -> str:
    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        extra_body={"enable_thinking": enable_thinking},
    )
    return extract_text_from_response(response)


def generate_llm_lrc(
    song_dir: Path,
    prompt_json: Path = Path("res/song_learner/re_segment_prompt.json"),
    model: str = "qwen3.5-plus",
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    enable_thinking: bool = True,
) -> Path:
    song_dir = Path(song_dir).expanduser().resolve()
    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    prompt_json_path = Path(prompt_json).expanduser().resolve()
    ensure_exists(prompt_json_path, "prompt配置文件")

    song_name = song_dir.name
    clear_lrc_path = song_dir / f"{song_name}.clear.lrc"
    out_path = song_dir / f"{song_name}.llm.lrc"
    ensure_exists(clear_lrc_path, "clear歌词文件")

    api_key = os.environ.get("QWEN_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("环境变量 QWEN_API_KEY 未设置")

    clear_lyrics = read_text_auto(clear_lrc_path).strip()
    if not clear_lyrics:
        raise ValueError(f"clear歌词为空: {clear_lrc_path}")

    prompt_template = load_prompt_template(prompt_json_path)
    prompt = build_prompt(prompt_template, clear_lyrics)

    llm_text = call_llm(
        model=model,
        api_key=api_key,
        base_url=base_url,
        enable_thinking=bool(enable_thinking),
        prompt=prompt,
    )

    out_path.write_text(llm_text + "\n", encoding="utf-8")
    print(f"[INFO] 输入歌词行数: {len(clear_lyrics.splitlines())}")
    print(f"[SUCCESS] 已生成: {out_path}")
    return out_path


def main() -> None:
    args = parse_args()

    generate_llm_lrc(
        song_dir=Path(args.song_dir),
        prompt_json=Path(args.prompt_json),
        model=args.model,
        base_url=args.base_url,
        enable_thinking=bool(args.enable_thinking),
    )


if __name__ == "__main__":
    main()
