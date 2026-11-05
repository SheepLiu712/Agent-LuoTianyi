from __future__ import annotations

import copy
from typing import Any


def build_llm_config_view(config: dict[str, Any]) -> dict[str, Any]:
    llm_service = config.get("llm_service", {})
    return {
        "available_llms": llm_service.get("available_llms", {}),
        "available_vlms": llm_service.get("available_vlms", {}),
        "available_audio_models": llm_service.get("available_audio_models", {}),
        "call_transport": copy.deepcopy(config.get("call_transport", {})),
        "client_model_types": llm_service.get("client_model_types", []),
        "module_bindings": collect_module_bindings(config),
    }


def collect_module_bindings(config: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []

    def walk(value: Any, path: list[str]) -> None:
        if isinstance(value, dict):
            for kind in ("llm", "vlm", "audio"):
                model_cfg = value.get(kind)
                if not isinstance(model_cfg, dict) or model_cfg.get("name") is None:
                    continue
                settings = model_cfg if kind == "llm" else {**model_cfg, **value}
                bindings.append(
                    {
                        "path": ".".join(path),
                        "kind": kind,
                        "interface_name": model_cfg.get("name", ""),
                        "prompt_name": value.get("prompt_name", ""),
                        "enable_thinking": bool(settings.get("enable_thinking", False)),
                        "use_json": bool(settings.get("use_json", kind == "audio")),
                        "client_model_type": str(model_cfg.get("client_model_type") or ""),
                        "params": copy.deepcopy(settings.get("params", {})),
                    }
                )
            for key, item in value.items():
                walk(item, [*path, str(key)])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, [*path, str(index)])

    walk(config, [])
    return sorted(bindings, key=lambda item: (item["kind"], item["path"]))


def apply_llm_config_draft(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    next_config = copy.deepcopy(config)
    llm_service = next_config.setdefault("llm_service", {})
    llm_service["available_llms"] = _normalize_interfaces(payload.get("available_llms", {}))
    llm_service["available_vlms"] = _normalize_interfaces(payload.get("available_vlms", {}))
    if "available_audio_models" in payload:
        llm_service["available_audio_models"] = _normalize_interfaces(payload["available_audio_models"])
    if "call_transport" in payload:
        if not isinstance(payload["call_transport"], dict):
            raise ValueError("call_transport 必须是对象")
        next_config["call_transport"] = copy.deepcopy(payload["call_transport"])
    llm_service["client_model_types"] = _normalize_client_model_types(payload.get("client_model_types"))

    for binding in payload.get("module_bindings", []):
        kind = str(binding.get("kind") or "").strip()
        path = str(binding.get("path") or "").strip()
        interface_name = str(binding.get("interface_name") or "").strip()
        if kind not in {"llm", "vlm", "audio"} or not path:
            continue
        module_cfg = _get_by_path(next_config, path)
        if not isinstance(module_cfg, dict):
            continue
        interface_cfg = module_cfg.setdefault(kind, {})
        interface_cfg["name"] = interface_name
        interface_cfg["client_model_type"] = str(binding.get("client_model_type") or "").strip()
        enable_thinking = bool(binding.get("enable_thinking", False))
        use_json = bool(binding.get("use_json", False))
        params = _normalize_params(binding)
        if kind == "llm":
            interface_cfg["enable_thinking"] = enable_thinking
            interface_cfg["use_json"] = use_json
            interface_cfg["params"] = params
        else:
            module_cfg["enable_thinking"] = enable_thinking
            module_cfg["use_json"] = use_json
            module_cfg["params"] = params
    return next_config


def _normalize_client_model_types(value: Any) -> list[dict[str, Any]]:
    """规范化客户端委托需求；服务端不保存任何客户端供应商或模型目录。"""
    if not isinstance(value, list):
        return []
    types: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        type_id = str(item.get("id") or "").strip()
        if not type_id or type_id in seen_ids:
            continue
        seen_ids.add(type_id)
        model_kind = str(item.get("model_kind") or "").strip().lower()
        types.append(
            {
                "id": type_id,
                "name": str(item.get("name") or "").strip(),
                "description": str(item.get("description") or "").strip(),
                "model_kind": model_kind if model_kind in {"llm", "vlm", "audio"} else "llm",
                "requires_json": bool(item.get("requires_json", False)),
                "requires_thinking": bool(item.get("requires_thinking", False)),
            }
        )
    return types


def _normalize_interfaces(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw_name, raw_cfg in value.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_cfg, dict):
            continue
        cfg = copy.deepcopy(raw_cfg)
        cfg["api_type"] = str(cfg.get("api_type") or "openai").strip()
        cfg["model"] = str(cfg.get("model") or "").strip()
        cfg["api_key"] = str(cfg.get("api_key") or "").strip()
        cfg["base_url"] = str(cfg.get("base_url") or "").strip()
        cfg.pop("default_params_text", None)
        result[name] = cfg
    return result


def _normalize_params(binding: dict[str, Any]) -> dict[str, Any]:
    params = binding.get("params", {})
    if isinstance(params, dict):
        return copy.deepcopy(params)
    return {}


def _get_by_path(config: dict[str, Any], path: str) -> Any:
    current: Any = config
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return None
    return current
