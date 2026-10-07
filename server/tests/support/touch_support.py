"""触摸行为测试共用的请求样例。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import src.domain.agent as d


def touch_request(
    *,
    regions: tuple[str, ...] = ("head",),
    frequency: d.TouchClickFrequency | None = None,
) -> d.HandleStimulusRequest:
    stimulus = d.TouchInteraction(
        stimulus_id="touch",
        schema_version=1,
        occurred_at=datetime.now(timezone.utc),
        source=d.StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="user",
        ephemeral=True,
        body_regions=tuple(d.BodyRegion(value=value) for value in regions),
        click_frequency=frequency,
    )
    interaction = d.ChatInteractionSnapshot(
        interaction_id="interaction",
        interaction_revision=3,
        user_id="user",
        pending_stimuli=(),
        now=datetime.now(timezone.utc),
        timezone=ZoneInfo("UTC"),
        supported_outputs=frozenset(
            {
                d.AgentOutputKind.AUDIO_CHUNK,
                d.AgentOutputKind.MESSAGE_END,
                d.AgentOutputKind.EXPRESSION,
            }
        ),
        response_deadline=None,
        connection_state=d.ConnectionState.CONNECTED,
    )
    return d.HandleStimulusRequest(
        request_id="request",
        stimulus=stimulus,
        interaction=interaction,
        cancellation=d.CancellationToken(),
    )
