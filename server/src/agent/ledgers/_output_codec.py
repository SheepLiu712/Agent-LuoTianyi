"""完整输出的版本化白名单编码，音频使用无损 Base64。"""
from base64 import b64decode, b64encode
from dataclasses import fields
from enum import Enum
import json

import src.domain.agent as d
from src.agent.outputs import drafts


OUTPUTS = (d.TextFinalOutput, d.AudioChunkOutput, d.MessageEndOutput, d.ExpressionOutput)
DRAFTS = (drafts.TextFinalDraft, drafts.AudioChunkDraft, drafts.MessageEndDraft, drafts.ExpressionDraft)
_TYPES = {cls.__name__: cls for cls in (*OUTPUTS, d.ChangeExpression, d.OutputDelivery,
                                       d.AudioFraming, d.MessageEndStatus, d.AudioErrorCode)}


def bind(draft, context, action_id, sequence):
    """只接受四种草稿，通过领域构造器校验内容后绑定身份。"""
    if type(draft) not in DRAFTS:
        raise ValueError("invalid output draft")
    return OUTPUTS[DRAFTS.index(type(draft))](
        interaction_id=context.interaction_id, execution_id=context.execution_id,
        action_id=action_id, sequence_no=sequence,
        **{field.name: getattr(draft, field.name) for field in fields(draft)})


def _encode(value):
    if type(value) in _TYPES.values():
        return [type(value).__name__, value.value if isinstance(value, Enum) else
                {field.name: _encode(getattr(value, field.name)) for field in fields(value)}]
    if type(value) is bytes:
        return ["bytes", b64encode(value).decode("ascii")]
    if value is None or type(value) in (str, int):
        return value
    raise ValueError("invalid output value")


def _decode(value):
    if type(value) is not list:
        return value
    name, payload = value
    if name == "bytes":
        return b64decode(payload, validate=True)
    cls = _TYPES[name]
    if issubclass(cls, Enum):
        return cls(payload)
    if set(payload) != {field.name for field in fields(cls)}:
        raise ValueError("invalid output fields")
    return cls(**{name: _decode(item) for name, item in payload.items()})


def encode(output):
    return json.dumps([1, _encode(output)], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode(payload):
    version, value = json.loads(payload)
    output = _decode(value)
    if type(version) is not int or version != 1 or type(output) not in OUTPUTS or encode(output) != payload:
        raise ValueError("invalid output encoding")
    return output
