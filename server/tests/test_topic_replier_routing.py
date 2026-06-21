import os
import sys
from types import SimpleNamespace

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.chat.topic_planner import ExtractedTopic
from src.agent.chat.topic_replier import TopicReplier


class FakeRuntime:
    def __init__(self):
        self.agents = {
            "luotianyi": object(),
            "yanhe": object(),
        }

    def get_agent(self, character_id):
        return self.agents[character_id]


def test_topic_replier_routes_topic_to_target_character_agent():
    runtime = FakeRuntime()
    replier = TopicReplier(username="tester", user_id="user-1", send_reply_callback=lambda response: None)
    replier.system_runtime = SimpleNamespace(agent=runtime.agents["luotianyi"], agent_runtime=runtime)
    topic = ExtractedTopic(
        topic_id="topic-1",
        source_messages=[],
        topic_content="hello",
        memory_attempts=[],
        fact_constraints=[],
        sing_attempts=[],
        target_character_ids=("yanhe",),
    )

    assert replier._agent_for_topic(topic) is runtime.agents["yanhe"]


def test_topic_replier_falls_back_to_default_agent_for_unknown_character():
    runtime = FakeRuntime()
    default_agent = runtime.agents["luotianyi"]
    replier = TopicReplier(username="tester", user_id="user-1", send_reply_callback=lambda response: None)
    replier.system_runtime = SimpleNamespace(agent=default_agent, agent_runtime=runtime)
    topic = ExtractedTopic(
        topic_id="topic-1",
        source_messages=[],
        topic_content="hello",
        memory_attempts=[],
        fact_constraints=[],
        sing_attempts=[],
        target_character_ids=("missing",),
    )

    assert replier._agent_for_topic(topic) is default_agent
