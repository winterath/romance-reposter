from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import requests

from .base import PlatformPoster, PostResult
from ..retry import RetryableError, with_retry


class TikTokPoster(PlatformPoster):
    """Upload a local MP4 through TikTok Content Posting API."""

    platform = "tiktok"
    api_root = "https://open.tiktokapis.com"

    def post(self, queue_row: Any) -> PostResult:
        token = os.getenv("TIKTOK_ACCESS_TOKEN")
        if not token:
            raise RuntimeError("TIKTOK_ACCESS_TOKEN is required")
        if not self.config.get("platforms.tiktok.confirm_creator_consent", False):
            raise RuntimeError(
                "Set platforms.tiktok.confirm_creator_consent: true after the creator/account "
                "has authorized this app and consented to posting"
            )

        creator_info = self._creator_info(token)
        privacy = self.config.get("platforms.tiktok.privacy_level", "SELF_ONLY")
        allowed_privacy = creator_info.get("privacy_level_options", [])
        if allowed_privacy and privacy not in allowed_privacy:
            privacy = "SELF_ONLY" if "SELF_ONLY" in allowed_privacy else allowed_privacy[0]

        max_duration = creator_info.get("max_video_post_duration_sec")
        duration = queue_row["duration_seconds"]
        if max_duration and duration and float(duration) > float(max_duration):
            raise RuntimeError(f"Video duration exceeds TikTok account max: {max_duration}s")

        path = Path(queue_row["path"])
        init_payload = self._init_upload(token, path, queue_row["caption"], privacy)
        upload_url = init_payload.get("upload_url")
        publish_id = init_payload.get("publish_id")
        if not upload_url:
            raise RuntimeError(f"TikTok did not return upload_url: {init_payload}")
        self._upload_chunks(upload_url, path)
        return PostResult("tiktok", publish_id, f"Uploaded TikTok video {publish_id}")

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _creator_info(self, token: str) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            response = requests.post(
                f"{self.api_root}/v2/post/publish/creator_info/query/",
                headers=self._headers(token),
                timeout=30,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RetryableError(response.text)
            response.raise_for_status()
            payload = response.json()
            if payload.get("error", {}).get("code") not in {None, "ok"}:
                raise RuntimeError(payload["error"])
            return payload.get("data", {})

        return with_retry(_send)

    def _init_upload(self, token: str, path: Path, caption: str, privacy: str) -> dict[str, Any]:
        file_size = path.stat().st_size
        chunk_size = _chunk_size(file_size)
        total_chunks = math.ceil(file_size / chunk_size)
        payload = {
            "post_info": {
                "title": caption[:2200],
                "privacy_level": privacy,
                "disable_duet": bool(self.config.get("platforms.tiktok.disable_duet", False)),
                "disable_comment": bool(self.config.get("platforms.tiktok.disable_comment", False)),
                "disable_stitch": bool(self.config.get("platforms.tiktok.disable_stitch", False)),
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        }

        def _send() -> dict[str, Any]:
            response = requests.post(
                f"{self.api_root}/v2/post/publish/video/init/",
                headers=self._headers(token),
                json=payload,
                timeout=60,
            )
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RetryableError(response.text)
            response.raise_for_status()
            body = response.json()
            if body.get("error", {}).get("code") not in {None, "ok"}:
                raise RuntimeError(body["error"])
            return body.get("data", {})

        return with_retry(_send)

    def _upload_chunks(self, upload_url: str, path: Path) -> None:
        file_size = path.stat().st_size
        chunk_size = _chunk_size(file_size)
        with path.open("rb") as handle:
            start = 0
            while start < file_size:
                chunk = handle.read(chunk_size)
                end = start + len(chunk) - 1
                headers = {
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                }
                response = requests.put(upload_url, headers=headers, data=chunk, timeout=120)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RetryableError(response.text)
                response.raise_for_status()
                start = end + 1


def _chunk_size(file_size: int) -> int:
    five_mb = 5 * 1024 * 1024
    sixty_four_mb = 64 * 1024 * 1024
    if file_size < five_mb:
        return file_size
    return min(sixty_four_mb, max(five_mb, file_size))
