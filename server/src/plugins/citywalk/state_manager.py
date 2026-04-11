from dataclasses import replace

from .types import CitywalkState


class CitywalkStateManager:
    def __init__(
        self,
        initial_energy: int = 100,
        max_minutes: int = 240,
        move_energy_per_km: int = 5,
        activity_energy_per_30min: int = 8,
    ):
        self.max_minutes = max_minutes
        self.move_energy_per_km = move_energy_per_km
        self.activity_energy_per_30min = activity_energy_per_30min
        self.state = CitywalkState(energy=initial_energy, elapsed_minutes=0)

    def apply_move(self, distance_m: int, duration_s: int) -> CitywalkState:
        distance_km = max(distance_m, 0) / 1000.0
        energy_loss = int(round(distance_km * self.move_energy_per_km))
        duration_min = max(int(round(duration_s / 60)), 0)

        self.state = replace(
            self.state,
            energy=max(self.state.energy - energy_loss, 0),
            elapsed_minutes=self.state.elapsed_minutes + duration_min,
        )
        return self.state

    def apply_activity(self, duration_min: int) -> CitywalkState:
        ratio = max(duration_min, 0) / 30.0
        energy_loss = int(round(ratio * self.activity_energy_per_30min))

        self.state = replace(
            self.state,
            energy=max(self.state.energy - energy_loss, 0),
            elapsed_minutes=self.state.elapsed_minutes + max(duration_min, 0),
        )
        return self.state

    def should_end(self) -> bool:
        return self.state.energy <= 0 or self.state.elapsed_minutes >= self.max_minutes
