from __future__ import annotations

from ..config import AppConfig
from .base import DryRunPoster, PlatformPoster


def poster_for(platform: str, config: AppConfig) -> PlatformPoster:
    if config.dry_run:
        return DryRunPoster(config, platform)
    if platform == "youtube":
        from .youtube import YouTubePoster

        return YouTubePoster(config)
    if platform == "instagram":
        from .instagram import InstagramPoster

        return InstagramPoster(config)
    if platform == "tiktok":
        from .tiktok import TikTokPoster

        return TikTokPoster(config)
    raise ValueError(f"Unsupported platform: {platform}")
