"""Shared startup preparation for CLI, systemd, and Windows launchers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from src.infrastructure.config.secrets import SecretStore
from src.utils.helpers import apply_env_variables
from src.utils.server_paths import ServerPaths


@dataclass
class StartupContext:
    paths: ServerPaths
    secrets: SecretStore
    config: dict


def prepare_startup() -> StartupContext:
    paths = ServerPaths.from_environment()
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    secrets = SecretStore(paths.config_dir / "secrets.local.env")
    secrets.load_into_environment()
    config_file = paths.config_dir / "config.json"
    with config_file.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    if not isinstance(raw, dict):
        raise ValueError("config.json must contain an object")
    config = paths.resolve_config(apply_env_variables(raw))
    os.chdir(paths.runtime_dir)
    return StartupContext(paths, secrets, config)
