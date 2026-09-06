"""请求身份的确定编码与处理报告的版本化 JSON，禁止动态类型加载。"""
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

import src.domain.agent as d


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _value(value):
    if isinstance(value, Enum):
        return ["enum", _type_name(value), value.value]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat(), getattr(value.tzinfo, "key", None), value.fold]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, ZoneInfo):
        return ["zone", value.key]
    if is_dataclass(value) and not isinstance(value, type):
        return ["object", _type_name(value), {f.name: _value(getattr(value, f.name)) for f in fields(value)}]
    if isinstance(value, tuple):
        return ["tuple", [_value(item) for item in value]]
    if isinstance(value, frozenset):
        return ["set", sorted((_value(item) for item in value), key=_json)]
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("unsupported request value")


def _type_name(value):
    return f"{type(value).__module__}.{type(value).__qualname__}"


def fingerprint(character_id, request):
    """哈希全部不可变请求语义，排除作为键的请求 ID 和可变令牌。"""
    encoded = _json([1, character_id, _type_name(request), _value(request.stimulus), _value(request.interaction)])
    return "v1:" + sha256(encoded.encode("utf-8")).hexdigest()


def encode_report(report):
    values = {f.name: getattr(report, f.name) for f in fields(report)}
    values["reconsider_at"] = _value(report.reconsider_at)
    return _json({"version": 1, "report": values})


def decode_report(payload):
    data = json.loads(payload)
    if type(data) is not dict or set(data) != {"version", "report"} or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("unknown report format")
    values = data["report"]
    if type(values) is not dict or set(values) != {f.name for f in fields(d.HandlingReport)}:
        raise ValueError("invalid report fields")
    values["request_status"] = d.HandlingRequestStatus(values["request_status"])
    if values["error_code"] is not None:
        values["error_code"] = d.HandlingErrorCode(values["error_code"])
    for name in ("considered_pending_stimulus_ids", "consumed_pending_stimulus_ids",
                 "retained_pending_stimulus_ids", "emitted_plan_ids"):
        if type(values[name]) is not list:
            raise ValueError("invalid report identities")
        values[name] = tuple(values[name])
    stamp = values["reconsider_at"]
    if stamp is not None:
        if type(stamp) is not list or len(stamp) != 4 or stamp[0] != "datetime" or type(stamp[3]) is not int:
            raise ValueError("invalid report timestamp")
        instant = datetime.fromisoformat(stamp[1])
        if stamp[2] is not None:
            instant = instant.astimezone(ZoneInfo(stamp[2]))
        values["reconsider_at"] = instant.replace(fold=stamp[3])
        if _value(values["reconsider_at"]) != stamp:
            raise ValueError("inconsistent report timestamp")
    return d.HandlingReport(**values)
