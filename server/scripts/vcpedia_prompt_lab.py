"""Prompt lab: edit the extraction prompt and see what the model extracts.

Runs the real provider by default and prints the extraction result, so a prompt edit
shows its effect immediately:

    python scripts/vcpedia_prompt_lab.py --material lyrics:煌 --drop lyrics
    python scripts/vcpedia_prompt_lab.py --material yishen --drop lyrics --prompt my.json
    python scripts/vcpedia_prompt_lab.py --material lyrics:煌 --drop lyrics \\
        --prompt a.json --prompt-b b.json          # A/B: same input, two prompts

Use --dry-run to only render the prompt locally (no request). Artifacts land under
server/data/test_outputs/prompt-lab/<timestamp>/ (gitignored).

Material is a frozen fixture, so two runs differ only by the prompt. The live path
reuses the project chain (SecretStore -> ConfigStore -> LLMService -> register_llm_module)
and merges the answer with the real ``merge_missing``, so what you see is what the
crawler would store.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import difflib
import io
import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

FIXTURES = SERVER / "tests" / "world" / "fixtures"
DEFAULT_PROMPT = SERVER / "res" / "agent" / "prompts" / "song_knowledge_extraction_prompt.json"
OUT_ROOT = SERVER / "data" / "test_outputs" / "prompt-lab"
MODULE_NAME = "song_knowledge_extractor"


def load_material(spec: str, title_override: str | None):
    """Return (source_wikitext, title) for one frozen input."""
    if spec == "yishen":
        path = FIXTURES / "vcpedia_recorded_yishen.wikitext"
        return path.read_text(encoding="utf-8"), title_override or "疑神疑鬼"
    if spec.startswith("lyrics:"):
        name = spec.split(":", 1)[1]
        data = json.loads((FIXTURES / "vcpedia_recorded_lyrics.json").read_text(encoding="utf-8"))
        if name not in data:
            raise SystemExit(f"未找到材料 {name}；可选：{', '.join(data)}")
        return data[name]["wikitext"], title_override or name
    for prefix, filename in (("fixed:", "vcpedia_fixed_acceptance.json"),
                             ("consecutive:", "vcpedia_frozen_consecutive.json")):
        if spec.startswith(prefix):
            index = int(spec.split(":", 1)[1])
            records = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
            page = records[index]["response"]["parse"]
            return page["wikitext"]["*"], title_override or page["title"]
    if spec.startswith("file:"):
        path = Path(spec.split(":", 1)[1])
        return path.read_text(encoding="utf-8"), title_override or path.stem
    raise SystemExit(f"无法识别的 --material：{spec}（可用 yishen / lyrics:<标题> / fixed:<0..2> / "
                     f"consecutive:<0..2> / file:<路径>）")


def build_prompt_dir(prompt_file: Path) -> tuple[Path, str]:
    """Copy the tested prompt into a scratch template dir; return (dir, prompt_name)."""
    payload = json.loads(prompt_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("name") or "template" not in payload:
        raise SystemExit(f"{prompt_file} 不是有效的提示词文件（需要 name 与 template）")
    name = payload["name"]
    scratch = Path(tempfile.mkdtemp(prefix="prompt-lab-"))
    shutil.copyfile(prompt_file, scratch / f"{name}.json")
    return scratch, name


def render_prompt(prompt_dir: Path, prompt_name: str, variables: dict) -> tuple[str, list[str]]:
    """Render exactly as LLMModule does, without touching any model."""
    from src.utils.llm.prompt_manager import PromptManager

    manager = PromptManager({"template_dir": str(prompt_dir)})
    template = manager.get_template(prompt_name)
    if template is None:
        raise SystemExit(f"提示词未被加载：{prompt_name}（检查 name 字段与文件名）")
    declared = sorted(template.get_variables())
    missing = [key for key in declared if key not in variables]
    if missing:
        raise SystemExit(f"提示词声明了未提供的变量：{missing}")
    return manager.render_template(prompt_name, **variables), declared


def diff_text(left: str, right: str, left_name: str, right_name: str) -> str:
    return "".join(difflib.unified_diff(left.splitlines(keepends=True), right.splitlines(keepends=True),
                                        fromfile=left_name, tofile=right_name))


def field_diff(before: dict, after: dict) -> dict:
    changed = {}
    for key in ("infobox", "summary", "lyrics", "spaced_lyrics"):
        if before.get(key) != after.get(key):
            changed[key] = {"before": before.get(key), "after": after.get(key)}
    return changed


def run_live(prompt_dir: Path, prompt_name: str, variables: dict, data: dict, needed: dict,
             provider_override: str | None = None):
    """Call the configured provider once through the project's own registration path."""
    from src.system.admin.config_store import ConfigStore
    from src.system.admin.secret_store import SecretStore
    from src.utils.llm_service import LLMService
    from src.world.get_new_songs.source_extraction import merge_missing

    SecretStore(SERVER / "config" / "secrets.local.env").load_into_environment()
    with contextlib.redirect_stdout(io.StringIO()):
        # Absolute path: ConfigStore.read_raw resolves the relative form against the CWD.
        config = ConfigStore(SERVER / "config" / "config.json", root_dir=SERVER).read_resolved()
    if "world" not in config:
        raise SystemExit("配置缺少 world 段；请确认 server/config/config.json 存在且可解析")
    crawler = copy.deepcopy(config["world"]["song_knowledge"]["crawler"])
    configured = crawler.get("extraction_llm_module")
    module_cfg = copy.deepcopy(configured or crawler["llm_module"])
    base = "extraction_llm_module" if configured else "llm_module（配置未启用补提，回退）"
    module_cfg["prompt_name"] = prompt_name
    if provider_override:
        module_cfg["llm"]["name"] = provider_override
    # The extraction contract is JSON mode with thinking off; the summary module that
    # this falls back to has use_json=false, so force it instead of measuring the wrong thing.
    module_cfg["llm"]["use_json"] = True
    module_cfg["llm"]["enable_thinking"] = False
    provider = module_cfg["llm"]["name"]
    service_cfg = copy.deepcopy(config["llm_service"])
    providers = service_cfg.get("available_llms") or {}
    if provider not in providers:
        raise SystemExit(f"provider {provider} 不在 llm_service.available_llms：{sorted(providers)}")
    provider_cfg = providers[provider]
    unresolved = [key for key in ("api_key", "base_url", "model")
                  if not isinstance(provider_cfg.get(key), str) or not provider_cfg[key].strip()
                  or "${" in provider_cfg[key] or provider_cfg[key].startswith("$")]
    if unresolved:
        raise SystemExit(f"provider {provider} 的 {unresolved} 未解析；未发送任何请求")
    secret = provider_cfg["api_key"]
    service_cfg["prompt_manager"] = {"template_dir": str(prompt_dir)}
    service = LLMService(service_cfg)
    module = service.register_llm_module(MODULE_NAME, module_cfg)
    if any(secret in value for value in variables.values() if isinstance(value, str)):
        raise SystemExit("材料中包含 provider 凭据；已中止，避免外发")
    response = asyncio.run(module.generate_response(**variables))
    usage = (module.recent_response or {}).get("usage") or {}
    before = copy.deepcopy(data)
    parsed = None
    try:
        parsed = json.loads(response)
    except ValueError as exc:
        print(f"  [警告] 模型返回不是合法 JSON：{exc}")
    if isinstance(parsed, dict):
        merge_missing(data, parsed, needed)
    return {"response": response, "parsed": parsed, "usage": usage,
            "merged_diff": field_diff(before, data), "merged": data,
            "provider": provider, "base": base, "module": module_cfg}


def apply_drop(data: dict, needed: dict, spec: str) -> None:
    """Simulate a gap page by removing fields, since frozen material is complete."""
    for item in (part.strip() for part in spec.split(",")):
        if not item:
            continue
        if item == "lyrics":
            data["lyrics"] = ""
            data.pop("spaced_lyrics", None)
            needed["lyrics"] = True
        elif item == "summary":
            data["summary"] = []
            needed["summary"] = True
        elif item == "infobox":
            data["infobox"] = {}
            needed["infobox"] = []
        elif item.startswith("infobox:"):
            key = item.split(":", 1)[1]
            data.setdefault("infobox", {}).pop(key, None)
            if key not in needed["infobox"]:
                needed["infobox"].append(key)
        else:
            raise SystemExit(f"无法识别的 --drop 项：{item}（可用 lyrics / summary / infobox / infobox:字段名）")


def main() -> int:
    parser = argparse.ArgumentParser(description="VCPedia 提取提示词实验室（默认离线）")
    parser.add_argument("--material", default="yishen",
                        help="yishen / lyrics:<标题> / fixed:<0..2> / consecutive:<0..2> / file:<路径>")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT, help="要测试的提示词 JSON")
    parser.add_argument("--prompt-b", type=Path, help="第二个提示词，用于 A/B 对比")
    parser.add_argument("--title", help="覆盖 parse_details 使用的标题")
    parser.add_argument("--needed", help='覆盖缺项，例如 {"infobox":["UP主"],"summary":true,"lyrics":true}')
    parser.add_argument("--drop", help="制造缺项：lyrics,summary,infobox,infobox:字段名（冻结材料本身是完整的）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只本地渲染提示词，不调用模型（默认会真实调用）")
    parser.add_argument("--provider", help="覆盖 provider 名（默认取配置里的 extraction_llm_module 或回退 llm_module）")
    parser.add_argument("--out", type=Path, help="产物目录（默认 data/test_outputs/prompt-lab/<时间戳>）")
    args = parser.parse_args()

    from src.utils import logger
    logger._DEFAULT_CONFIG.update(file_output=False, console_output=False)
    logging.disable(logging.CRITICAL)

    from src.world.get_new_songs.wikitext_parser import parse_details

    source, title = load_material(args.material, args.title)
    parsed = parse_details(source, title, with_missing=True)
    data, needed = parsed if isinstance(parsed, tuple) else (parsed, {})
    if args.drop:
        apply_drop(data, needed, args.drop)
    if args.needed:
        needed = json.loads(args.needed)
    materials = {"raw": source[:24000]}
    variables = {"song_data": json.dumps(data, ensure_ascii=False),
                 "needed": json.dumps(needed, ensure_ascii=False),
                 "materials": json.dumps(materials, ensure_ascii=False)}

    out = args.out or OUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    print(f"材料: {args.material}  标题: {title}  源码: {len(source)} 字符")
    print(f"缺项: {json.dumps(needed, ensure_ascii=False)}")
    if not any(needed.values()):
        print("  提示：该材料没有缺项，生产路径不会调用模型；用 --drop lyrics,summary 造出缺项再迭代提示词")
    print(f"材料键: {sorted(materials)}（渲染片段由程序本地合并，不作为模型材料）")
    print(f"明文提示词字符数: {len(variables['song_data']) + len(variables['needed']) + len(variables['materials'])}")
    print()

    payloads = {}
    for label, prompt_file in (("A", args.prompt), ("B", args.prompt_b)):
        if prompt_file is None:
            continue
        prompt_dir, prompt_name = build_prompt_dir(prompt_file)
        rendered, declared = render_prompt(prompt_dir, prompt_name, variables)
        payloads[label] = {"file": str(prompt_file), "name": prompt_name, "rendered": rendered,
                           "declared": declared, "dir": prompt_dir}
        (out / f"prompt-{label}.txt").write_text(rendered, encoding="utf-8")
        print(f"[{label}] {prompt_file}")
        print(f"    提示词名: {prompt_name}  变量: {declared}  渲染后 {len(rendered)} 字符")

    if "B" in payloads:
        print()
        print("=== 渲染提示词差异（A → B） ===")
        print(diff_text(payloads["A"]["rendered"], payloads["B"]["rendered"], "A", "B") or "  （无差异）")

    if args.dry_run:
        print()
        print("--dry-run：只渲染提示词，未调用模型。去掉该参数即真实调用。")
        (out / "report.json").write_text(json.dumps(
            {"material": args.material, "title": title, "needed": needed,
             "materials": materials, "variables_chars": {k: len(v) for k, v in variables.items()},
             "prompts": {k: {"file": v["file"], "name": v["name"], "chars": len(v["rendered"])}
                         for k, v in payloads.items()}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"产物: {out}")
        return 0

    print()
    print("=== 真实调用 provider；每个提示词 1 次请求 ===")
    print("    强制提取契约：use_json=True、enable_thinking=False、无工具")
    report = {"material": args.material, "title": title, "needed": needed, "runs": {}}
    results = {}
    for label, payload in payloads.items():
        print(f"[{label}] 调用 {payload['name']} ...")
        run_data = copy.deepcopy(data)
        try:
            result = run_live(payload["dir"], payload["name"], variables, run_data,
                              copy.deepcopy(needed), args.provider)
        except Exception as exc:  # a failed call must not lose the other side of the A/B
            print(f"    失败：{type(exc).__name__}: {exc}")
            report["runs"][label] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        results[label] = result
        report["runs"][label] = {k: v for k, v in result.items() if k != "merged"}
        (out / f"response-{label}.txt").write_text(result["response"], encoding="utf-8")
        (out / f"merged-{label}.json").write_text(
            json.dumps(result["merged"], ensure_ascii=False, indent=2), encoding="utf-8")
        usage = result["usage"]
        print(f"    provider: {result['provider']}（基准配置：{result['base']}）")
        print(f"    usage: prompt={usage.get('prompt_tokens', '?')} completion={usage.get('completion_tokens', '?')}"
              f" total={usage.get('total_tokens', '?')}")
        print()
        print(f"    --- 模型返回（原样，{len(result['response'])} 字符）---")
        print("    " + result["response"].strip().replace("\n", "\n    ")[:2000])
        if result["parsed"] is None:
            print()
            print("    [警告] 返回不是合法 JSON，未合并任何字段。")
        else:
            print()
            print("    --- 合并后的提取结果 ---")
            for key, change in result["merged_diff"].items():
                print(f"    {key}:")
                print(f"      之前: {json.dumps(change['before'], ensure_ascii=False)[:300]}")
                print(f"      之后: {json.dumps(change['after'], ensure_ascii=False)[:300]}")
            if not result["merged_diff"]:
                print("    （没有字段被改动：模型未填任何请求项，或填的值与现状相同）")
            print(f"    请求的缺项: {json.dumps(needed, ensure_ascii=False)}")

    if "A" in results and "B" in results:
        print()
        print("=== 合并结果差异（A → B） ===")
        left = json.dumps(results["A"]["merged"], ensure_ascii=False, indent=2, sort_keys=True)
        right = json.dumps(results["B"]["merged"], ensure_ascii=False, indent=2, sort_keys=True)
        print(diff_text(left, right, "A", "B") or "  （完全一致）")

    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"产物: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
