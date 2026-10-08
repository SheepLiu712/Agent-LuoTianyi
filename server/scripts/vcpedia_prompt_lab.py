"""Offline-first extraction prompt experiments, not full production coverage.

    python scripts/vcpedia_prompt_lab.py --material title:Foxy
    python scripts/vcpedia_prompt_lab.py --material title:疑神疑鬼 --drop lyrics
    python scripts/vcpedia_prompt_lab.py --prompt a.json --prompt-b b.json --live

Only --live authorizes configured OpenAI-compatible model calls (api_type=openai).
--dry-run is an offline compatibility alias. Neither mode renders remote fragments
or fetches pages. Artifacts record prompts, normalized redacted JSON responses and
production merges, not model correctness. Invalid response bodies are withheld.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import io
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

CORPUS = SERVER / "tests" / "support" / "vcpedia_corpus"
DEFAULT_PROMPT = SERVER / "res" / "agent" / "prompts" / "song_knowledge_extraction_prompt.json"
OUT_ROOT = SERVER / "data" / "test_outputs" / "prompt-lab"
MODULE_NAME = "song_knowledge_extractor"
_JSON_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrt])')


def _json_escape_value(match: re.Match) -> str:
    return json.loads('"' + match.group() + '"')


class LabError(ValueError):
    """A deliberately credential-free diagnostic suitable for the report."""


class Artifacts:
    """One output boundary; provider credentials never enter persisted text."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.secrets: set[str] = set()

    def redact(self, text: str) -> str:
        secrets = sorted(filter(None, self.secrets), key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        # Detect JSON escapes even when the provider double-encodes a credential.
        # Only output is redacted; model values still go unchanged to production merge.
        candidate = text
        while True:
            decoded = _JSON_ESCAPE.sub(_json_escape_value, candidate)
            if decoded == candidate:
                return text
            if any(secret in decoded for secret in secrets):
                return "[REDACTED]"
            candidate = decoded

    def clean(self, value):
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {self.redact(str(key)): self.clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item) for item in value]
        return value

    def text(self, filename: str, text: str) -> None:
        (self.directory / filename).write_text(self.redact(text), encoding="utf-8")

    def json(self, filename: str, value) -> None:
        content = json.dumps(self.clean(value), ensure_ascii=False, indent=2, allow_nan=False)
        (self.directory / filename).write_text(content, encoding="utf-8")


def load_material(spec: str, title_override: str | None = None) -> tuple[str, str]:
    """Resolve only public title/file mappings, never historical private tags."""
    if spec.startswith("file:"):
        path = Path(spec[5:])
        return path.read_text(encoding="utf-8"), title_override or path.stem
    title = "疑神疑鬼" if spec == "yishen" else spec.partition(":")[2]
    if spec != "yishen" and not spec.startswith(("title:", "lyrics:")):
        raise LabError("无法识别材料；使用 title:<corpus标题> 或 file:<路径>，不支持旧 fixed/consecutive 索引")
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    entry = next((page for page in manifest["pages"] if page["title"] == title), None)
    if entry is None:
        raise LabError("corpus 中没有该标题或旧别名的实际映射；请使用 manifest.json 中的 title")
    path = (CORPUS / entry["file"]).resolve()
    if not path.is_relative_to(CORPUS.resolve()):
        raise LabError("corpus file 必须位于 corpus 目录内")
    return path.read_text(encoding="utf-8"), title_override or title


@contextlib.contextmanager
def build_prompt_dir(prompt_file: Path):
    """Keep scratch templates alive only while rendering/calling their module."""
    payload = json.loads(prompt_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str) or not payload["name"]:
        raise LabError("提示词 JSON 需要非空 name 与 template")
    template = payload.get("template")
    if not isinstance(template, (str, list)) or not template:
        raise LabError("提示词 template 必须是非空字符串或字符串列表")
    if isinstance(template, list) and not all(isinstance(line, str) for line in template):
        raise LabError("提示词 template 列表只能包含字符串")
    with tempfile.TemporaryDirectory(prefix="prompt-lab-") as scratch:
        directory = Path(scratch)
        # The template name is metadata, never a filesystem path.
        (directory / "experiment.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        yield directory, payload["name"]


def render_prompt(prompt_dir: Path, prompt_name: str, variables: dict) -> tuple[str, list[str]]:
    from src.infrastructure.models.llm.prompts import PromptManager

    manager = PromptManager({"template_dir": str(prompt_dir)})
    template = manager.get_template(prompt_name)
    if template is None:
        raise LabError("提示词未被加载；检查 template 内容")
    if set(template.var_list) - variables.keys():
        raise LabError("提示词引用了未提供的变量；仅提供 song_data、needed、materials")
    return manager.render_template(prompt_name, **variables), sorted(template.var_list)


def validate_needed(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"infobox", "summary", "lyrics"}:
        raise LabError("needed 必须是包含 infobox、summary、lyrics 的 JSON object")
    keys = value["infobox"]
    if not isinstance(keys, list) or not all(isinstance(key, str) and key.strip() for key in keys):
        raise LabError("needed.infobox 必须是非空字段名的列表")
    if not all(isinstance(value[key], bool) for key in ("summary", "lyrics")):
        raise LabError("needed.summary/lyrics 必须是布尔值")
    return {**value, "infobox": list(dict.fromkeys(keys))}


def _drop_infobox(data: dict, needed: dict, item: str) -> None:
    keys = list(data.get("infobox", {})) if item == "infobox" else [item.partition(":")[2].strip()]
    if not keys or not all(keys):
        raise LabError("没有可删除的信息框原键；请使用 infobox:<字段名> 指定请求键")
    for key in keys:
        data.setdefault("infobox", {}).pop(key, None)
        if key not in needed["infobox"]:
            needed["infobox"].append(key)


def apply_drop(data: dict, needed: dict, spec: str) -> None:
    """Drop actual values without losing the original infobox request keys."""
    for item in filter(None, (part.strip() for part in spec.split(","))):
        if item == "lyrics":
            data["lyrics"] = ""
            data.pop("spaced_lyrics", None)
            needed["lyrics"] = True
        elif item == "summary":
            data["summary"] = []
            needed["summary"] = True
        elif item == "infobox" or item.startswith("infobox:"):
            _drop_infobox(data, needed, item)
        else:
            raise LabError("无法识别 drop；使用 lyrics、summary、infobox 或 infobox:<字段名>")


def prepare_material(args) -> dict:
    from src.world.get_new_songs.source_extraction import collect_materials
    from src.world.get_new_songs.wikitext_parser import parse_details

    source, title = load_material(args.material, args.title)
    data, needed = parse_details(source, title, with_missing=True)
    needed = validate_needed(json.loads(args.needed) if args.needed is not None else needed)
    if args.drop:
        apply_drop(data, needed, args.drop)
    materials = collect_materials(data, needed, source, "https://vcpedia.cn", title, merge_fragments=False)
    variables = {
        "song_data": json.dumps(data, ensure_ascii=False, default=str),
        "needed": json.dumps(needed, ensure_ascii=False),
        "materials": json.dumps(materials, ensure_ascii=False),
    }
    return {
        "title": title,
        "source_chars": len(source),
        "data": data,
        "needed": needed,
        "materials": materials,
        "variables": variables,
    }


@contextlib.contextmanager
def _quiet_dependencies():
    """Do not echo provider errors or let imported services create log files."""
    from src.utils import logger

    previous_config = logger._DEFAULT_CONFIG.copy()
    previous_disable = logging.root.manager.disable
    logger._DEFAULT_CONFIG.update(file_output=False, console_output=False)
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            yield
    finally:
        logger._DEFAULT_CONFIG.update(previous_config)
        logging.disable(previous_disable)


def load_live_config(artifacts: Artifacts, provider_override: str | None = None) -> dict:
    """Check the supported API before credentials, then resolve existing configuration."""
    from src.infrastructure.config.secrets import SecretStore
    from src.infrastructure.config.store import ConfigStore

    config_store = ConfigStore(SERVER / "config" / "config.json", root_dir=SERVER)
    _select_provider(config_store.read_raw(), provider_override)
    store = SecretStore(SERVER / "config" / "secrets.local.env")
    secrets = store.read()
    artifacts.secrets.update(value for value in secrets.values() if value)
    previous = {key: os.environ.get(key) for key in secrets}
    try:
        store.load_into_environment()
        config = config_store.read_resolved()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return config


def _remember_provider_secrets(config: dict, artifacts: Artifacts) -> None:
    for provider in config.get("llm_service", {}).get("available_llms", {}).values():
        for key in ("api_key", "token", "secret", "password"):
            value = provider.get(key)
            if isinstance(value, str) and value:
                artifacts.secrets.add(value)


def _select_provider(config: dict, provider_override: str | None) -> tuple[dict, str, dict]:
    crawler = config.get("world", {}).get("song_knowledge", {}).get("crawler", {})
    module_config = copy.deepcopy(crawler.get("extraction_llm_module"))
    if not isinstance(module_config, dict) or not isinstance(module_config.get("llm"), dict):
        raise LabError("配置缺少 extraction_llm_module；未发送请求，不回退总结 llm_module")
    provider = provider_override or module_config["llm"].get("name")
    providers = config.get("llm_service", {}).get("available_llms", {})
    if provider not in providers:
        raise LabError("提取 provider 不在 llm_service.available_llms；未发送请求")
    provider_config = providers[provider]
    if provider_config.get("api_type") != "openai":
        raise LabError("lab live 仅支持 api_type=openai 的 OpenAI-compatible provider；未发送请求")
    return module_config, provider, provider_config


def live_settings(config: dict, provider_override: str | None) -> dict:
    module_config, provider, provider_config = _select_provider(config, provider_override)
    values = [provider_config.get(key) for key in ("api_key", "base_url", "model")]
    if any(not isinstance(value, str) or not value.strip() or "$" in value for value in values):
        raise LabError("提取 provider 的 api_key/base_url/model 未解析；未发送请求")
    module_config["llm"]["name"] = provider
    # Only construct the selected existing service interface, not unrelated providers/VLMs.
    return {
        "module": module_config,
        "service": {"available_llms": {provider: copy.deepcopy(provider_config)}},
        "description": {
            "base": "extraction_llm_module",
            "provider": provider,
            "api_type": "openai",
            "model": provider_config["model"],
            "provider_override": bool(provider_override),
            "use_json": module_config["llm"].get("use_json", False),
            "enable_thinking": module_config["llm"].get("enable_thinking", False),
        },
    }


def create_module(settings: dict, prompt_dir: Path, prompt_name: str):
    from src.infrastructure.models.service import LLMService

    service_config = copy.deepcopy(settings["service"])
    service_config["prompt_manager"] = {"template_dir": str(prompt_dir)}
    module_config = copy.deepcopy(settings["module"])
    module_config["prompt_name"] = prompt_name
    return LLMService(service_config).register_llm_module(MODULE_NAME, module_config)


def field_diff(before: dict, after: dict) -> dict:
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in ("infobox", "summary", "lyrics", "spaced_lyrics")
        if before.get(key) != after.get(key)
    }


def _record_error(record: dict, exc: Exception) -> None:
    record.update(status="error", error_type=type(exc).__name__)
    # Arbitrary provider exceptions may contain URLs, credentials or response bodies.
    record["error"] = str(exc) if isinstance(exc, LabError) else "实验失败；详见 error_type、stage 与已保留产物"


def _decode_and_record_response(response, record: dict, artifacts: Artifacts, label: str) -> dict:
    from src.world.get_new_songs.source_extraction import decode_extraction_response

    response_text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    record.update(response_chars=len(response_text), stage="decode_extraction_response")
    filename = f"response-{label}.txt"
    try:
        parsed = decode_extraction_response(response)
    except ValueError:
        record["response_storage"] = "withheld_invalid_response"
        artifacts.json(
            filename,
            {
                "response_withheld": True,
                "response_chars": len(response_text),
                "reason": "Invalid response body withheld to protect credentials",
            },
        )
        raise
    record["response_storage"] = "normalized_redacted_json"
    artifacts.json(filename, parsed)
    return parsed


def _call_and_merge(module, prepared: dict, record: dict, artifacts: Artifacts, label: str) -> None:
    from src.world.get_new_songs.source_extraction import merge_missing

    data, needed = copy.deepcopy(prepared["data"]), copy.deepcopy(prepared["needed"])
    record.update(stage="generate_response", model_call_attempted=True)
    response = asyncio.run(module.generate_response(**copy.deepcopy(prepared["variables"])))
    record["response_received"] = True
    parsed = _decode_and_record_response(response, record, artifacts, label)
    record["stage"] = "merge_missing"
    merge_missing(data, parsed, needed)
    record.update(status="ok", parsed=parsed, merged_diff=field_diff(prepared["data"], data), needed_after=needed)
    usage = (getattr(module, "recent_response", None) or {}).get("usage") or {}
    record["usage"] = {
        key: value
        for key, value in usage.items()
        if key in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(value, int)
    }
    artifacts.json(f"merged-{label}.json", data)


def run_prompt(label: str, prompt_file: Path, prepared: dict, settings: dict | None, artifacts: Artifacts) -> dict:
    record = {
        "file": str(prompt_file),
        "stage": "render_prompt",
        "model_call_attempted": False,
        "response_received": False,
        "needed_before": copy.deepcopy(prepared["needed"]),
    }
    try:
        with build_prompt_dir(prompt_file) as (directory, name):
            rendered, declared = render_prompt(directory, name, prepared["variables"])
            artifacts.text(f"prompt-{label}.txt", rendered)
            record.update(name=name, declared=declared, prompt_chars=len(rendered))
            if settings is None or not any(prepared["needed"].values()):
                record.update(status="skipped", reason="offline" if settings is None else "no_needed")
                record["needed_after"] = copy.deepcopy(prepared["needed"])
                return record
            if artifacts.redact(rendered) != rendered:
                raise LabError("提示词或材料包含 provider 凭据；未发送请求")
            record["stage"] = "register_module"
            module = create_module(settings, directory, name)
            _call_and_merge(module, prepared, record, artifacts, label)
    except Exception as exc:
        # A/B jobs are isolated, and any failed job makes the CLI fail after preserving both.
        _record_error(record, exc)
    return record


def _execute(args, artifacts: Artifacts, report: dict) -> None:
    prepared = prepare_material(args)
    report.update({key: value for key, value in prepared.items() if key != "variables"})
    report["variables_chars"] = {key: len(value) for key, value in prepared["variables"].items()}
    settings = None
    if args.live and any(prepared["needed"].values()):
        report["stage"] = "live_config"
        config = load_live_config(artifacts, args.provider)
        _remember_provider_secrets(config, artifacts)
        settings = live_settings(config, args.provider)
        report["configuration"] = settings["description"]
    report["stage"] = "prompts"
    for label, prompt_file in (("A", args.prompt), ("B", args.prompt_b)):
        if prompt_file is not None:
            record = run_prompt(label, prompt_file, prepared, settings, artifacts)
            if args.live and not any(prepared["needed"].values()):
                record["reason"] = "no_needed"
            report["runs"][label] = record
    report["status"] = "error" if any(run["status"] == "error" for run in report["runs"].values()) else "ok"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="VCPedia 提示词实验/输出记录（默认离线；不是完整 production coverage 证明）",
        epilog="不抓取页面、不执行片段 POST；live 仅支持 api_type=openai 的提取模块，无总结回退；非法响应正文不落盘。",
    )
    parser.add_argument(
        "--material",
        default="title:Foxy",
        help="title:<corpus标题> / file:<路径>；yishen、lyrics:<标题> 仅兼容实际 corpus 映射",
    )
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT, help="提示词 JSON")
    parser.add_argument("--prompt-b", type=Path, help="第二个提示词；A/B 使用独立数据与相同材料")
    parser.add_argument("--title", help="覆盖解析标题")
    parser.add_argument("--needed", help='覆盖缺项 JSON，例如 {"infobox":[],"summary":false,"lyrics":true}')
    parser.add_argument("--drop", help="在 needed 覆盖后制造缺项：lyrics,summary,infobox,infobox:<字段名>")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="显式允许真实模型调用，可能付费；无缺项则不请求")
    mode.add_argument("--dry-run", action="store_true", help="兼容选项：保持默认离线，不读凭据、不联网、不付费")
    parser.add_argument("--provider", help="仅 --live：覆盖已配置 api_type=openai 的提取 provider（报告标注）")
    parser.add_argument("--out", type=Path, help="新的/空的产物目录（默认 data/test_outputs/prompt-lab/<时间戳>）")
    args = parser.parse_args(argv)
    if args.provider and not args.live:
        parser.error("--provider 必须与 --live 一起使用")
    return args


def main(argv=None) -> int:
    args = _parse_args(argv)  # --help exits before imports, credentials or filesystem writes.
    out = args.out or OUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    report = {
        "purpose": "prompt_experiment_output_record",
        "full_production_coverage": False,
        "mode": "live" if args.live else "offline",
        "material": args.material,
        "fragment_post_attempts": 0,
        "merge_rendered_fragments": False,
        "network_note": "片段 POST 为 0；model_call_attempted 表示服务调用尝试，不代表已发出的 HTTP 次数",
        "stage": "prepare_material",
        "runs": {},
    }
    artifacts = Artifacts(out)
    try:
        if out.exists() and any(out.iterdir()):
            raise LabError("产物目录非空；请选择新目录，避免覆盖旧实验")
        out.mkdir(parents=True, exist_ok=True)
    except (OSError, LabError) as exc:
        print(str(exc) if isinstance(exc, LabError) else "无法创建产物目录", file=sys.stderr)
        return 1
    with _quiet_dependencies():
        try:
            _execute(args, artifacts, report)
        except Exception as exc:
            _record_error(report, exc)
        report["exit_code"] = 1 if report["status"] == "error" else 0
        artifacts.json("report.json", report)
    print(f"提示词实验：{report['mode']}；片段 POST=0；不证明完整生产覆盖")
    for label, run in report["runs"].items():
        print(f"[{label}] {run['status']}；模型调用尝试={run['model_call_attempted']}")
    if report["status"] == "error":
        print(artifacts.redact(report.get("error", "部分提示词实验失败；查看 report.json")), file=sys.stderr)
    print(artifacts.redact(f"产物: {out}"))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
