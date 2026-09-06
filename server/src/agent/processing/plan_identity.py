"""稳定计划身份与显式白名单 JSON；不按存储中的名称动态导入类型。"""
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from hashlib import sha256
import json

import src.domain.agent as d

_types = {cls.__name__: cls for cls in (
    d.ActionPlan, d.StartThinking, d.Say, d.Sing, d.WriteDiary, d.PublishDynamic,
    d.ReplyDynamic, d.RequestSongLearning, d.MediaRef, d.Tone, d.ChangeExpression,
    d.DynamicSource, d.DynamicReplyTarget, d.OutputDelivery, d.Visibility,
)}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def plan_id(character_id, request_id, ordinal):
    """角色、请求 ID 和槽位共同决定 v1 身份，内容变化不改变身份。"""
    return "plan-v1-" + sha256(_json([1, character_id, request_id, ordinal]).encode("utf-8")).hexdigest()


def _encode(value):
    if type(value) in _types.values():
        payload = value.value if isinstance(value, Enum) else {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)}
        return [type(value).__name__, payload]
    if type(value) is date:
        return ["date", value.isoformat()]
    if type(value) is tuple:
        return ["tuple", [_encode(item) for item in value]]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("unsupported plan value")


def _decode(value):
    if type(value) is not list:
        if value is None or type(value) in (str, int, bool):
            return value
        raise ValueError("invalid plan value")
    name, payload = value
    if name == "date":
        return date.fromisoformat(payload)
    if name == "tuple":
        return tuple(_decode(item) for item in payload)
    cls = _types[name]
    if not is_dataclass(cls):
        return cls(payload)
    if set(payload) != {field.name for field in fields(cls)}:
        raise ValueError("invalid plan fields")
    return cls(**{name: _decode(item) for name, item in payload.items()})


def encode_plan(plan):
    """编码完整计划；拒绝白名单以外的 Action 或嵌套值。"""
    return _json([1, _encode(plan)])


def decode_plan(payload):
    """重建领域对象并重新校验规范编码；损坏或未知版本抛异常。"""
    version, value = json.loads(payload)
    plan = _decode(value)
    if type(version) is not int or version != 1 or type(plan) is not d.ActionPlan or encode_plan(plan) != payload:
        raise ValueError("invalid plan encoding")
    return plan


def plan_fingerprint(payload):
    return sha256(payload.encode("utf-8")).hexdigest()
