"""回复处理器的具名能力依赖；仅组合引用，不执行场景编排。"""

from dataclasses import dataclass

from src.agent.skills.cognitive.reply import ReplySkill
from src.agent.skills.cognitive.topic_extraction import TopicExtractionSkill
from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.memory_retrieval import MemoryRetrievalSkill


@dataclass(frozen=True)
class ReplySkills:
    topic_extraction: TopicExtractionSkill
    retrieval: MemoryRetrievalSkill
    singing: SingingSkill
    reply: ReplySkill
