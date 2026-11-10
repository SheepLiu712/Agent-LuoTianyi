"""Resolve deployment paths without depending on process working directory."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ServerPaths:
    code_root: Path
    config_dir: Path
    resource_dir: Path
    asset_dir: Path
    data_dir: Path
    runtime_dir: Path

    @classmethod
    def from_environment(cls, code_root: str | Path | None = None, *, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        root = Path(code_root or Path(__file__).resolve().parents[2]).resolve()

        def directory(name, default):
            value = Path(env.get(name) or default).expanduser()
            return (root / value).resolve() if not value.is_absolute() else value.resolve()

        return cls(
            root,
            directory("AGENTLUO_CONFIG_DIR", "config"),
            directory("AGENTLUO_RESOURCE_DIR", "res"),
            directory("AGENTLUO_ASSET_DIR", "res"),
            directory("AGENTLUO_DATA_DIR", "data"),
            directory("AGENTLUO_RUNTIME_DIR", ".runtime"),
        )

    def resolve(self, raw: str | Path) -> Path:
        path = Path(raw).expanduser()
        if path.is_absolute():
            return path
        mappings = (
            (Path("res/tts"), self.asset_dir / "tts"),
            (Path("res/song_learner"), self.asset_dir / "song_learner"),
            (Path("res"), self.resource_dir),
            (Path("config"), self.config_dir),
            (Path("data"), self.data_dir),
            (Path(".runtime"), self.runtime_dir),
            (Path("logs"), self.runtime_dir / "logs"),
            (Path("temp"), self.runtime_dir / "temp"),
        )
        for prefix, base in mappings:
            try:
                relative = path.relative_to(prefix)
            except ValueError:
                continue
            if ".." in relative.parts:
                raise ValueError(f"Deployment path escapes its root: {raw}")
            return base / relative
        return self.code_root / path

    def resolve_config(self, value: Any, *, key: str = "") -> Any:
        """Resolve path fields in a copy; never rewrite persisted JSON or prompt text."""
        if isinstance(value, dict):
            return {name: self.resolve_config(item, key=name) for name, item in value.items()}
        if isinstance(value, list):
            return [self.resolve_config(item, key=key) for item in value]
        is_path = key.endswith(("_path", "_dir", "_file", "_folder")) or key in {
            "root",
            "manifest",
            "file",
            "reference_audio_lyrics",
            "songname_file",
            "lyric_file",
            "lyrics_file",
        }
        if is_path and isinstance(value, str) and value and not value.startswith(("http:", "https:", "${")):
            # Bare filenames (e.g. sql_db_file) remain relative to their configured folder.
            if "/" in value or "\\" in value:
                return str(self.resolve(value))
        return value


def resolve_server_path(raw: str | Path) -> Path:
    return ServerPaths.from_environment().resolve(raw)
