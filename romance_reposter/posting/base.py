from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import AppConfig


@dataclass(frozen=True)
class PostResult:
    platform: str
    remote_id: str | None
    message: str


class PlatformPoster:
    platform = "base"

    def __init__(self, config: AppConfig):
        self.config = config

    def post(self, queue_row: Any) -> PostResult:
        raise NotImplementedError


class DryRunPoster(PlatformPoster):
    """Records what would be posted without contacting a platform."""

    platform = "dry_run"

    def __init__(self, config: AppConfig, platform: str):
        super().__init__(config)
        self.platform = platform

    def post(self, queue_row: Any) -> PostResult:
        path = Path(queue_row["path"])
        return PostResult(
            platform=self.platform,
            remote_id=f"dry-run:{self.platform}:{queue_row['id']}",
            message=f"Dry run: would post {path.name}",
        )
