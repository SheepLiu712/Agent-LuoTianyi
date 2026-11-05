"""维护算法测试装配；生产接口仍自行创建内部策略。"""

from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill


def make_maintenance(*, memories, compaction, call_maintenance=None):
    skill = CognitiveMaintenanceSkill({}, llm_service=None, memories=memories)
    skill._compaction = compaction
    if call_maintenance is not None:
        skill._call_maintenance = call_maintenance
    return skill
