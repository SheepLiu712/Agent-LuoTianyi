"""处理器测试使用假的模型服务与存储端口装配统一动态能力。"""

import json
from types import SimpleNamespace

from src.agent.skills.expression.diary import DiaryDraft, DiarySkill
from src.agent.skills.expression.dynamic import DynamicSkill


def make_dynamic(backend, narratives):
    replier = getattr(backend, "replier", None)

    class Models:
        def register_llm_module(self, name, config):
            async def generate_response(**kwargs):
                if name == "skill.dynamic.generate_reply":
                    if replier.fail:
                        raise RuntimeError("回复模型不可用")
                    decision = ({"should_reply": True, "reply": replier.post_reply}
                                if kwargs["item_type"] == "dynamic_post" else replier.comment_decision)
                    return json.dumps(decision, ensure_ascii=False)
                return await backend.generate_world_dynamic_content(**kwargs)
            return SimpleNamespace(generate_response=generate_response)

    def create_dynamic(**kwargs):
        values = dict(kwargs)
        values["character_id"] = values.pop("author_id")
        for key in ("author_type", "memory_policy", "memory_status", "reply_status"):
            values.pop(key, None)
        return backend.publish_agent_dynamic(**values)

    def create_agent_reply(**kwargs):
        ok, message, item = backend.publish_agent_comment(
            dynamic_id=kwargs["dynamic_id"], owner_user_id=kwargs["owner_user_id"], content=kwargs["content"],
            character_id=kwargs["character_id"], parent_comment_id=kwargs["parent_comment_id"],
        )
        if not ok:
            raise RuntimeError(message)
        return item["id"], True

    database = getattr(backend, "database_manager", None) or SimpleNamespace(
        dynamic_store=SimpleNamespace(create_dynamic=create_dynamic, create_agent_reply=create_agent_reply)
    )
    config = {"dynamic_composer": {"llm_module": {"llm": {"name": "fake"}}}}
    if replier is not None and getattr(replier, "available", False):
        config["dynamic_replier"] = {"llm_module": {"llm": {"name": "fake"}}}
    return DynamicSkill(config, llm_service=Models(), database=database, narratives=narratives)


def make_diary(material, backend, narratives):
    dynamic = make_dynamic(backend, narratives)
    skill = DiarySkill({}, dynamic=dynamic, database=None)
    async def generate(invocation, *, local_date):
        narrative = narratives[invocation.character_id]
        body = await material.generate_diary_body(
            user_id=invocation.require_user_id(), character_id=invocation.character_id,
            character_name=narrative.name, character_persona=narrative.persona, speaking_style=narrative.speaking_style,
            target_date=local_date.isoformat(),
        )
        return DiaryDraft(body, local_date, invocation.require_user_id())
    return SimpleNamespace(generate=generate, publish=skill.publish)
