from dataclasses import replace

from .types import CitywalkState, POIFeedBack


class CitywalkStateManager:
    def __init__(
        self,
        initial_energy: int = 100,
        initial_fullness: int = 70,
        initial_mood: int = 70,
        max_minutes: int = 240,
        move_energy_per_km: int = 5,
        activity_energy_per_30min: int = 8,
    ):
        self.max_minutes = max_minutes
        self.move_energy_per_km = move_energy_per_km
        self.activity_energy_per_30min = activity_energy_per_30min
        self.state = CitywalkState(
            energy=max(min(initial_energy, 100), 0),
            fullness=max(min(initial_fullness, 150), 0),
            mood=max(min(initial_mood, 100), 0),
            elapsed_minutes=0,
        )

    def _derive_mood(self, energy: int, fullness: int) -> int:
        mood = self.state.mood
        if energy < 20:
            mood -= 25
        elif energy < 40:
            mood -= 12

        if fullness < 20:
            mood -= 18
        elif fullness > 140:
            mood -= 15
        elif 45 <= fullness <= 110:
            mood += 8

        return max(min(mood, 100), 0)

    @staticmethod
    def _energy_label(energy: int) -> str:
        if energy <= 10:
            return "几乎走不动"
        if energy <= 30:
            return "明显疲惫"
        if energy <= 60:
            return "还有余力"
        return "状态不错"

    @staticmethod
    def _fullness_label(fullness: int) -> str:
        if fullness < 20:
            return "很饿"
        if fullness < 45:
            return "有点饿"
        if fullness <= 100:
            return "刚刚好"
        if fullness <= 140:
            return "有点撑"
        return "很撑"

    @staticmethod
    def _mood_label(mood: int) -> str:
        if mood < 25:
            return "情绪低落"
        if mood < 50:
            return "有点烦躁"
        if mood < 75:
            return "情绪平稳"
        return "心情很好"

    def render_state_for_llm(self) -> str:
        s = self.state
        return (
            f"体力：{s.energy}/100({self._energy_label(s.energy)})；"
            f"饱腹度：{s.fullness}/100({self._fullness_label(s.fullness)})；"
            f"心情：{s.mood}/100({self._mood_label(s.mood)})；"
            f"已逛时长：{s.elapsed_minutes}分钟"
        )

    def apply_move(self, distance_m: int, duration_s: int) -> CitywalkState:
        distance_km = max(distance_m, 0) / 1000.0
        energy_loss = int(round(distance_km * self.move_energy_per_km))
        duration_min = max(int(round(duration_s / 60)), 0)
        fullness_after = max(self.state.fullness - max(int(round(duration_min / 20.0)), 1 if duration_min > 0 else 0), 0)
        energy_after = max(self.state.energy - energy_loss, 0)
        mood_after = self._derive_mood(energy_after, fullness_after)

        self.state = replace(
            self.state,
            energy=energy_after,
            fullness=fullness_after,
            mood=mood_after,
            elapsed_minutes=self.state.elapsed_minutes + duration_min,
        )
        return self.state
    
    def change_state_by_feedback(self, feedback: "POIFeedBack") -> CitywalkState:
        next_energy = max(min(self.state.energy + feedback.energy_change, 100), 0)
        next_fullness = max(min(self.state.fullness + feedback.fullness_change, 150), 0)
        next_mood = max(min(self.state.mood + feedback.mood_change, 100), 0)
        next_minutes = max(self.state.elapsed_minutes + max(feedback.stay_minutes, 0), 0)
        self.state = replace(
            self.state,
            energy=next_energy,
            fullness=next_fullness,
            mood=next_mood,
            elapsed_minutes=next_minutes,
        )
        return self.state
        

    def apply_activity(self, duration_min: int) -> CitywalkState:
        ratio = max(duration_min, 0) / 30.0
        energy_loss = int(round(ratio * self.activity_energy_per_30min))
        fullness_loss = max(int(round(max(duration_min, 0) / 25.0)), 0)
        energy_after = max(self.state.energy - energy_loss, 0)
        fullness_after = max(self.state.fullness - fullness_loss, 0)
        mood_after = self._derive_mood(energy_after, fullness_after)

        self.state = replace(
            self.state,
            energy=energy_after,
            fullness=fullness_after,
            mood=mood_after,
        )
        return self.state

    def apply_adjustments(self, delta_energy: int, delta_minutes: int, delta_fullness: int = 0) -> CitywalkState:
        # 体力在一次逛街中单调递减，不允许通过反馈回升。
        safe_energy_delta = min(delta_energy, 0)
        energy_after = max(min(self.state.energy + safe_energy_delta, 100), 0)
        fullness_after = max(min(self.state.fullness + delta_fullness, 150), 0)
        mood_after = self._derive_mood(energy_after, fullness_after)
        self.state = replace(
            self.state,
            energy=energy_after,
            fullness=fullness_after,
            mood=mood_after,
            elapsed_minutes=max(self.state.elapsed_minutes + max(delta_minutes, 0), 0),
        )
        return self.state

    def should_end(self) -> bool:
        return self.state.energy <= 0 or self.state.elapsed_minutes >= self.max_minutes
