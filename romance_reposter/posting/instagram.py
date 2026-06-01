from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .base import PlatformPoster, PostResult
from ..retry import RetryableError, with_retry


class InstagramPoster(PlatformPoster):
    """Publish Reels through Instagram Graph API content publishing."""

    platform = "instagram"

    def post(self, queue_row: Any) -> PostResult:
        token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        ig_user_id = os.getenv("INSTAGRAM_USER_ID")
        if not token or not ig_user_id:
            raise RuntimeError("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID are required")
        video_url = self._public_url(queue_row["path"])
        if not video_url:
            raise RuntimeError(
                "Instagram posting requires platforms.instagram.public_asset_base_url "
                "mapped to a public HTTPS copy of the rendered video"
            )

        version = self.config.get("platforms.instagram.graph_api_version", "v24.0")
        base = f"https://graph.facebook.com/{version}"
        caption = queue_row["caption"]
        container = self._post_json(
            f"{base}/{ig_user_id}/media",
            {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": str(bool(self.config.get("platforms.instagram.share_to_feed", True))).lower(),
                "access_token": token,
            },
        )
        container_id = container["id"]
        self._wait_until_ready(base, container_id, token)
        published = self._post_json(
            f"{base}/{ig_user_id}/media_publish",
            {"creation_id": container_id, "access_token": token},
        )
        return PostResult("instagram", published.get("id"), f"Published Instagram Reel {published.get('id')}")

    def _public_url(self, local_path: str) -> str | None:
        base_url = self.config.get("platforms.instagram.public_asset_base_url")
        if not base_url:
            return None
        root = self.config.path_value("platforms.instagram.public_asset_root", "data/renders")
        path = Path(local_path).resolve()
        try:
            relative = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            relative = path.name
        return base_url.rstrip("/") + "/" + quote(relative)

    def _post_json(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            response = requests.post(url, data=data, timeout=60)
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RetryableError(response.text)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload

        return with_retry(_send)

    def _wait_until_ready(self, base: str, container_id: str, token: str) -> None:
        for _ in range(24):
            response = requests.get(
                f"{base}/{container_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=30,
            )
            response.raise_for_status()
            status = response.json().get("status_code")
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status == "ERROR":
                raise RuntimeError(f"Instagram container failed: {container_id}")
            time.sleep(10)
        raise TimeoutError(f"Instagram container was not ready: {container_id}")
