"""所有角色共享的业务技能与一次性调用上下文。"""

from .contracts import SkillInvocation
from .facade import SharedSkills

__all__ = ["SharedSkills", "SkillInvocation"]
