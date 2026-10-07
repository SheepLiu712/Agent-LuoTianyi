"""Runtime configuration persistence and validation are infrastructure."""

from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_runtime_configuration_is_owned_by_infrastructure() -> None:
    config = SERVER_ROOT / "src" / "infrastructure" / "config"

    assert (config / "store.py").is_file()
    assert (config / "secrets.py").is_file()
    assert (config / "validation.py").is_file()
    assert (config / "model_editor.py").is_file()


def test_admin_package_does_not_own_configuration_implementations() -> None:
    admin = SERVER_ROOT / "src" / "system" / "admin"

    for name in ("config_store.py", "secret_store.py", "config_validator.py", "llm_config_editor.py"):
        assert not (admin / name).exists()
