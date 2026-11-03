"""所有角色共享的回复生成技能；每次调用独立解析并输出草稿流。"""

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict
from typing import Literal

from src.agent.context.models import UserContextSnapshot
from src.agent.skills.contracts import CharacterNarrative, ReplyDraft
from src.infrastructure.config.skills import SkillsConfig
from src.utils.logger import get_logger

from ._reply_resources import ReplyResources
from ._streaming_reply_parser import StreamingReplyParser


class ReplySkill:
    """按角色标识选择已绑定资源，不持有当前交互或写入聊天记录。"""

    def __init__(self, config: dict, *, llm_service, characters: Mapping) -> None:
        if not characters:
            raise ValueError("回复技能至少需要一个角色的生成资源")
        self._resources = {}
        for character_id, profile in characters.items():
            character_config = {**config, **config.get("characters", {}).get(character_id, {})}
            module_config = SkillsConfig.require_model(character_config, f"agent_runtime.skills.reply.{character_id}")
            module = llm_service.register_llm_module(
                f"skill.reply.generate.{character_id}",
                module_config,
                stream=True,
            )
            self._resources[character_id] = ReplyResources(character_config, module, profile)

    def narratives(self) -> dict[str, CharacterNarrative]:
        """提供已校验的人设资料，供其他内容生成能力共享。"""
        return {
            key: CharacterNarrative(
                name=value.character_name, persona=value.character_persona, speaking_style=value.speaking_style
            )
            for key, value in self._resources.items()
        }

    async def generate(
        self,
        character_id: str,
        *,
        reply_topic: str,
        scene: Literal["chat", "call"] = "chat",
        user_context: UserContextSnapshot,
        conversation_history: str = "",
        fact_hits: list[str] | None = None,
        memory_hits: list[str] | None = None,
        sing_plan: tuple[str, str] | None = None,
    ) -> AsyncIterator[ReplyDraft]:
        """输出已完成解析的草稿；调用方提前结束消费时必须关闭此异步流。"""
        if scene not in ("chat", "call"):
            raise ValueError(f"未知回复场景: {scene}")
        resource = self._resources[character_id]
        prompt = resource.prompt_assembler.build(
            scene=scene,
            character_name=resource.character_name,
            character_persona=resource.character_persona,
            speaking_style=resource.speaking_style,
            reply_topic=reply_topic,
            user_nickname="你",
            user_description=user_context.profile.description,
            preference_context=resource._build_preference_context(user_context),
            conversation_history=conversation_history,
            fact_hits=fact_hits,
            memory_hits=memory_hits,
            sing_plan=sing_plan,
        )
        queue: asyncio.Queue[ReplyDraft] = asyncio.Queue(maxsize=1)
        available = asyncio.Event()

        async def emit(draft):
            await queue.put(draft)
            available.set()

        async def produce():
            try:
                await self._generate(resource, asdict(prompt), sing_plan, emit)
            except Exception as error:
                get_logger(__name__).error(
                    "回复生成失败 character_id=%s error_type=%s", character_id, type(error).__name__
                )
                raise

        task = asyncio.create_task(produce())
        task.add_done_callback(lambda _: available.set())
        try:
            while True:
                await available.wait()
                available.clear()
                while not queue.empty():
                    yield queue.get_nowait()
                if task.done():
                    await task
                    break
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    async def _generate(resource, prompt, sing_plan, emit):
        if sing_plan is not None:
            # 演唱指令需要完整结果，不将歌曲名按标点切成多段。
            response = (
                await resource.llm.generate_response(**prompt)
                if getattr(resource.llm, "stream", False)
                else await resource._call_llm(**prompt)
            )
            for draft in resource.response_parser.parse(response, sing_plan):
                await emit(draft)
            return

        parser = StreamingReplyParser(resource.response_parser)

        async def delta(text):
            for draft in parser.feed(text):
                await emit(draft)

        if getattr(resource.llm, "stream", False):
            await resource.llm.generate_response(on_delta=delta, **prompt)
        else:
            await delta(await resource._call_llm(**prompt))
        for draft in parser.finish():
            await emit(draft)
