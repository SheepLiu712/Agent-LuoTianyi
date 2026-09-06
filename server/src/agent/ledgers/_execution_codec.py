"""执行事实的显式 JSON 编码和按计划校验，不动态加载存储类型。"""
from dataclasses import asdict, dataclass, replace
import json

import src.domain.agent as d


COMPLETED = (d.ActionExecutionStatus.COMPLETED, d.ActionExecutionStatus.ALREADY_COMPLETED)


@dataclass
class ActionFact:
    """单项行动的持久开始标记、可信返回和累计输出事实。"""
    started: bool = False
    result: d.ActionResult | None = None
    confirmed: bool = False
    unknown: bool = False

    @property
    def complete(self):
        return self.result is not None and self.result.status in COMPLETED

    @property
    def safe(self):
        return self.complete or (not self.confirmed and not self.unknown and (
            not self.started or (self.result is not None and not self.result.irreversible_effect_committed)))


def encode_facts(facts):
    return json.dumps([asdict(item) for item in facts], ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode_facts(payload, plan):
    """校验每项身份、状态与顺序；损坏记录抛异常且不自动重建。"""
    values = json.loads(payload)
    if type(values) is not list or len(values) != len(plan.actions):
        raise ValueError("invalid execution facts")
    facts, stopped = [], False
    for value, action in zip(values, plan.actions):
        if type(value) is not dict or set(value) != {"started", "result", "confirmed", "unknown"}:
            raise ValueError("invalid action facts")
        if any(type(value[key]) is not bool for key in ("started", "confirmed", "unknown")):
            raise ValueError("invalid action flags")
        result = value["result"]
        if result is not None:
            result = dict(result)
            result["status"] = d.ActionExecutionStatus(result["status"])
            result["error_code"] = d.ExecutionErrorCode(result["error_code"]) if result["error_code"] else None
            if result["effect_ref"] is not None:
                effect = result["effect_ref"]
                result["effect_ref"] = d.EffectRef(kind=d.EffectKind(effect["kind"]), effect_id=effect["effect_id"])
            result = d.ActionResult(**result)
            if result.action_id != action.action_id or result.status is d.ActionExecutionStatus.NOT_STARTED:
                raise ValueError("invalid action settlement")
        fact = ActionFact(**{**value, "result": result})
        if (not fact.started and (result is not None or fact.confirmed or fact.unknown)) or (stopped and fact.started):
            raise ValueError("invalid action order")
        stopped = stopped or not fact.complete
        facts.append(fact)
    if encode_facts(facts) != payload:
        raise ValueError("noncanonical action facts")
    return facts


def completed_prefix(facts):
    """重投只保留连续完成前缀，将其状态转换为 ALREADY_COMPLETED。"""
    results = []
    for fact in facts:
        if not fact.complete:
            break
        results.append(replace(fact.result, status=d.ActionExecutionStatus.ALREADY_COMPLETED))
    return results
