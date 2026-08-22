from __future__ import annotations

import copy
from typing import Any


def build_llm_config_view(config: dict[str, Any]) -> dict[str, Any]:
    llm_service = config.get("llm_service", {})
    return {
        "available_llms": llm_service.get("available_llms", {}),
        "available_vlms": llm_service.get("available_vlms", {}),
        "client_model_types": llm_service.get("client_model_types", []),
        "module_bindings": collect_module_bindings(config),
    }


def collect_module_bindings(config: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []

    def walk(value: Any, path: list[str]) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("llm"), dict) and value["llm"].get("name") is not None:
                llm_cfg = value["llm"]
                bindings.append(
                    {
                        "path": ".".join(path),
                        "kind": "llm",
                        "interface_name": llm_cfg.get("name", ""),
                        "prompt_name": value.get("prompt_name", ""),
                        "enable_thinking": bool(llm_cfg.get("enable_thinking", False)),
                        "use_json": bool(llm_cfg.get("use_json", False)),
                        "client_model_type": str(llm_cfg.get("client_model_type") or ""),
                        "params": copy.deepcopy(llm_cfg.get("params", {})),
                    }
                )
            if isinstance(value.get("vlm"), dict) and value["vlm"].get("name") is not None:
                vlm_cfg = value["vlm"]
                bindings.append(
                    {
                        "path": ".".join(path),
                        "kind": "vlm",
                        "interface_name": vlm_cfg.get("name", ""),
                        "prompt_name": value.get("prompt_name", ""),
                        "enable_thinking": bool(value.get("enable_thinking", vlm_cfg.get("enable_thinking", False))),
                        "use_json": bool(value.get("use_json", vlm_cfg.get("use_json", False))),
                        "client_model_type": str(vlm_cfg.get("client_model_type") or ""),
                        "params": copy.deepcopy(value.get("params", vlm_cfg.get("params", {}))),
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
    llm_service["client_model_types"] = _normalize_client_model_types(
        payload.get("client_model_types")
    )

    for binding in payload.get("module_bindings", []):
        kind = str(binding.get("kind") or "").strip()
        path = str(binding.get("path") or "").strip()
        interface_name = str(binding.get("interface_name") or "").strip()
        if kind not in {"llm", "vlm"} or not path:
            continue
        module_cfg = _get_by_path(next_config, path)
        if not isinstance(module_cfg, dict):
            continue
        interface_cfg = module_cfg.setdefault(kind, {})
        interface_cfg["name"] = interface_name
        interface_cfg["client_model_type"] = str(
            binding.get("client_model_type") or ""
        ).strip()
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
    """规范化客户端模型类型配置：去空白、去重、勾选默认 false。"""
    if not isinstance(value, list):
        return []
    types: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        type_name = str(item.get("type") or "").strip()
        if not type_name or type_name in seen_types:
            continue
        seen_types.add(type_name)
        description = str(item.get("description") or "").strip()
        providers: list[dict[str, Any]] = []
        seen_providers: set[str] = set()
        for provider in item.get("providers") or []:
            if not isinstance(provider, dict):
                continue
            name = str(provider.get("name") or "").strip()
            if not name or name in seen_providers:
                continue
            seen_providers.add(name)
            base_url = str(provider.get("base_url") or "").strip().rstrip("/")
            models: list[dict[str, Any]] = []
            seen_models: set[str] = set()
            for model in provider.get("models") or []:
                if isinstance(model, dict):
                    model_id = str(model.get("id") or "").strip()
                    can_thinking = bool(model.get("can_enable_thinking", False))
                    can_json = bool(model.get("can_use_json", False))
                elif isinstance(model, str):
                    model_id = model.strip()
                    can_thinking = False
                    can_json = False
                else:
                    continue
                if not model_id or model_id in seen_models:
                    continue
                seen_models.add(model_id)
                models.append(
                    {
                        "id": model_id,
                        "can_enable_thinking": can_thinking,
                        "can_use_json": can_json,
                    }
                )
            providers.append(
                {"name": name, "base_url": base_url, "models": models}
            )
        types.append(
            {"type": type_name, "description": description, "providers": providers}
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
