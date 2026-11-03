"""将既有生成桩接入回复草稿流；真实角色资源使用生产技能。"""

from src.agent.skills.cognitive._reply_resources import ReplyResources
from src.agent.skills.cognitive.reply import ReplySkill


class StubReplySkill:
    def __init__(self, generators):
        self.generators = generators

    async def generate(self, character_id, **kwargs):
        for draft in await self.generators[character_id].generate(**kwargs):
            yield draft


def make_reply_skill(resources):
    if all(isinstance(resource, ReplyResources) for resource in resources.values()):
        return ReplySkill(resources)
    return StubReplySkill(resources)
