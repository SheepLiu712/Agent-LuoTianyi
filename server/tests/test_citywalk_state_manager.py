from src.plugins.citywalk.state_manager import CitywalkStateManager


def test_state_move_and_activity():
    manager = CitywalkStateManager(initial_energy=100, max_minutes=240, move_energy_per_km=5, activity_energy_per_30min=8)

    state = manager.apply_move(distance_m=1500, duration_s=900)
    assert state.energy == 92
    assert state.elapsed_minutes == 15

    state = manager.apply_activity(duration_min=30)
    assert state.energy == 84
    assert state.elapsed_minutes == 45


def test_state_should_end():
    manager = CitywalkStateManager(initial_energy=1, max_minutes=10, move_energy_per_km=5, activity_energy_per_30min=8)
    manager.apply_activity(duration_min=30)
    assert manager.should_end()
