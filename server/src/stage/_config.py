"""仅校验 Stage 和管理器各自使用的配置。"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class _StageConfig:
    response_wait: float = 1.0
    typing_wait: float = 10.0
    image_selection_wait: float = 60.0
    first_login_wait: float = 1.0
    login_reminder_wait: float = 1.0
    proactive_idle_seconds: float = 30.0
    max_stimuli: int = 256
    max_plans: int = 64
    termination_timeout: float = 30.0

    @classmethod
    def from_dict(cls, config: dict) -> "_StageConfig":
        if not isinstance(config, dict):
            raise TypeError("stage config must be a dictionary")
        values = {
            key: config.get(key, default)
            for key, default in (
                ("max_stimuli", 256),
                ("max_plans", 64),
                ("termination_timeout", 30.0),
                ("response_wait", 1.0),
                ("typing_wait", 10.0),
                ("image_selection_wait", 60.0),
                ("first_login_wait", 1.0),
                ("login_reminder_wait", 1.0),
                ("proactive_idle_seconds", 30.0),
            )
        }
        for key in ("max_stimuli", "max_plans"):
            if type(values[key]) is not int or values[key] <= 0:
                raise ValueError(f"{key} must be a positive integer")
        for key in (
            "termination_timeout",
            "response_wait",
            "typing_wait",
            "image_selection_wait",
            "first_login_wait",
            "login_reminder_wait",
            "proactive_idle_seconds",
        ):
            value = values[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be positive and finite")
        return cls(**values)
