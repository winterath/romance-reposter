from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


MediaType = Literal["video", "image", "image_sequence"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class SourceItem:
    """Normalized description of one media item from an approved source."""

    source_id: str
    external_id: str
    title: str
    description: str
    creator: str
    creator_handle: str | None
    credit_url: str | None
    license: str
    permission_note: str | None
    media_type: MediaType
    media_urls: list[str] = field(default_factory=list)
    local_paths: list[Path] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        return " ".join(
            [
                self.title,
                self.description,
                self.creator,
                self.creator_handle or "",
                " ".join(self.tags),
            ]
        ).lower()


@dataclass(frozen=True)
class MediaInfo:
    """Technical metadata returned by ffprobe or Pillow."""

    width: int
    height: int
    duration_seconds: float | None = None
    fps: float | None = None


@dataclass(frozen=True)
class CaptionPackage:
    """Generated metadata for one rendered short."""

    title: str
    caption: str
    hashtags: list[str]
    emotion: str
    subtitle_lines: list[str]

    @property
    def platform_caption(self) -> str:
        tag_text = " ".join(f"#{tag.lstrip('#')}" for tag in self.hashtags)
        if tag_text:
            return f"{self.caption}\n\n{tag_text}"
        return self.caption
