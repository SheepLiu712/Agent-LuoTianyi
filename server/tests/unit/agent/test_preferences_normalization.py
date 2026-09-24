"""角色回复生成器只消费已经规范化的用户上下文。"""

from src.agent.context.models import UserContextSnapshot, UserPreferences
from src.agent.skills.cognitive.response_generation import CharacterReplyGenerator


def test_reply_generator_renders_typed_preferences():
    context = UserContextSnapshot(
        preferences=UserPreferences(
            relationship="伙伴",
            speaking_style="简洁",
            personality_traits=("温柔", "坦率"),
            custom_context="我喜欢音乐",
            personality_text="不要使用敬语",
        )
    )

    rendered = CharacterReplyGenerator._build_preference_context(context)

    assert "用户希望你是他的：伙伴" in rendered
    assert "用户希望你的表达风格偏向：简洁" in rendered
    assert "用户希望你的性格特点：温柔、坦率" in rendered
    assert "用户喜欢音乐" in rendered
    assert "不要使用敬语" in rendered
