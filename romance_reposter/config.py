from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def _expand(value: Any) -> Any:
    """Expand environment variables in nested config values."""

    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


@dataclass
class AppConfig:
    """Thin wrapper around the YAML config that keeps path handling consistent."""

    raw: dict[str, Any]
    path: Path

    def get(self, dotted: str, default: Any = None) -> Any:
        current: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def path_value(self, dotted: str, default: str) -> Path:
        value = self.get(dotted, default)
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
        return (self.path.parent / candidate).resolve()

    @property
    def storage_root(self) -> Path:
        return self.path_value("storage.root", "data")

    @property
    def database_path(self) -> Path:
        return self.path_value("storage.database", "data/reposter.sqlite")

    @property
    def downloads_dir(self) -> Path:
        return self.path_value("storage.downloads", "data/downloads")

    @property
    def renders_dir(self) -> Path:
        return self.path_value("storage.renders", "data/renders")

    @property
    def dry_run(self) -> bool:
        return bool(self.get("posting.dry_run", True))


def load_config(path: str | Path) -> AppConfig:
    """Load YAML config plus a sibling/global .env file."""

    config_path = Path(path).resolve()
    load_dotenv(config_path.parent / ".env")
    load_dotenv()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return AppConfig(raw=_expand(data), path=config_path)


def ensure_storage(config: AppConfig) -> None:
    """Create local directories used by the pipeline."""

    for folder in [config.storage_root, config.downloads_dir, config.renders_dir]:
        folder.mkdir(parents=True, exist_ok=True)
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
