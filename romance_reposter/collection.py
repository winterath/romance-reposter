from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .captions import classify_emotion
from .config import AppConfig
from .db import Database
from .media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, checksum_path, probe_media, quality_ok
from .models import SourceItem
from .retry import RetryableError, with_retry


def collect_sources(config: AppConfig, db: Database) -> tuple[int, int]:
    """Collect all enabled approved sources and insert valid assets into SQLite."""

    added = 0
    rejected = 0
    for source_config in config.get("sources", []):
        if not source_config.get("enabled", False):
            continue
        collector = _collector_for(source_config, config)
        for item in collector.items():
            if not _passes_policy(item, config):
                rejected += 1
                continue
            try:
                media_path = _materialize_item(item, config)
                info = probe_media(media_path, item.media_type, config)
                if not quality_ok(info, config):
                    rejected += 1
                    continue
                checksum = checksum_path(media_path)
                metadata = {
                    "tags": item.tags,
                    "credit_url": item.credit_url,
                    "raw": item.raw,
                    "emotion": classify_emotion(item.search_text),
                    "files": _file_list(media_path),
                }
                asset_id = db.upsert_asset(item, media_path, info, checksum, metadata)
                if asset_id is None:
                    rejected += 1
                else:
                    added += 1
            except Exception:
                rejected += 1
    return added, rejected


class BaseCollector:
    def __init__(self, source_config: dict[str, Any], config: AppConfig):
        self.source_config = source_config
        self.config = config

    def items(self) -> list[SourceItem]:
        raise NotImplementedError

    def normalize_item(self, raw: dict[str, Any]) -> SourceItem:
        source_id = self.source_config["id"]
        creator = raw.get("creator") or self.source_config.get("creator") or "Unknown creator"
        return SourceItem(
            source_id=source_id,
            external_id=str(raw.get("id") or raw.get("external_id") or raw.get("title")),
            title=str(raw.get("title") or "Untitled"),
            description=str(raw.get("description") or ""),
            creator=str(creator),
            creator_handle=raw.get("creator_handle") or self.source_config.get("creator_handle"),
            credit_url=raw.get("credit_url") or self.source_config.get("credit_url"),
            license=str(raw.get("license") or self.source_config.get("license") or ""),
            permission_note=raw.get("permission_note") or self.source_config.get("permission_note"),
            media_type=raw.get("media_type", "video"),
            media_urls=list(raw.get("media_urls") or ([raw["media_url"]] if raw.get("media_url") else [])),
            local_paths=[Path(p) for p in raw.get("local_paths", [])],
            tags=list(raw.get("tags") or []),
            raw=raw,
        )


class ManifestCollector(BaseCollector):
    """Read a creator-approved JSON manifest over HTTPS or from a local file."""

    def items(self) -> list[SourceItem]:
        manifest_url = self.source_config["manifest_url"]
        if manifest_url.startswith("http://") or manifest_url.startswith("https://"):
            response = with_retry(
                lambda: _get_json(manifest_url),
                max_attempts=int(self.config.get("posting.retry.max_attempts", 4)),
            )
            payload = response
        else:
            path = self.config.path.parent / manifest_url
            payload = json.loads(path.read_text(encoding="utf-8"))
        return [self.normalize_item(item) for item in payload.get("items", [])]


class LocalFolderCollector(BaseCollector):
    """Read approved assets from a local creator drop folder."""

    def items(self) -> list[SourceItem]:
        folder = Path(self.source_config["folder"])
        if not folder.is_absolute():
            folder = (self.config.path.parent / folder).resolve()
        if not folder.exists():
            return []

        items: list[SourceItem] = []
        grouped_images = sorted(
            p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS and not p.name.startswith(".")
        )
        videos = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)

        if grouped_images:
            raw = self._sidecar(folder / "metadata.json")
            raw.update(
                {
                    "id": raw.get("id") or folder.name,
                    "title": raw.get("title") or folder.name.replace("_", " ").title(),
                    "media_type": "image_sequence" if len(grouped_images) > 1 else "image",
                    "local_paths": [str(path) for path in grouped_images],
                }
            )
            items.append(self.normalize_item(raw))

        for video in videos:
            raw = self._sidecar(video.with_suffix(video.suffix + ".json"))
            raw.update(
                {
                    "id": raw.get("id") or video.stem,
                    "title": raw.get("title") or video.stem.replace("_", " ").title(),
                    "media_type": "video",
                    "local_paths": [str(video)],
                }
            )
            items.append(self.normalize_item(raw))
        return items

    def _sidecar(self, path: Path) -> dict[str, Any]:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}


def _collector_for(source_config: dict[str, Any], config: AppConfig) -> BaseCollector:
    source_type = source_config.get("type")
    if source_type == "manifest":
        return ManifestCollector(source_config, config)
    if source_type == "local_folder":
        return LocalFolderCollector(source_config, config)
    raise ValueError(f"Unsupported source type: {source_type}")


def _passes_policy(item: SourceItem, config: AppConfig) -> bool:
    allowed = {license_name.upper() for license_name in config.get("content.allowed_licenses", [])}
    if item.license.upper() not in allowed:
        return False
    if config.get("content.require_permission_note", True) and not item.permission_note:
        return False
    keywords = [keyword.lower() for keyword in config.get("content.keywords", [])]
    if keywords and not any(keyword in item.search_text for keyword in keywords):
        return False
    if not item.media_urls and not item.local_paths:
        return False
    return True


def _materialize_item(item: SourceItem, config: AppConfig) -> Path:
    target_dir = config.downloads_dir / _safe_name(item.source_id) / _safe_name(item.external_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    if item.local_paths:
        copied: list[Path] = []
        for local_path in item.local_paths:
            resolved = local_path if local_path.is_absolute() else (config.path.parent / local_path).resolve()
            destination = target_dir / resolved.name
            if not destination.exists():
                shutil.copyfile(resolved, destination)
            copied.append(destination)
        return copied[0] if len(copied) == 1 and item.media_type != "image_sequence" else target_dir

    downloaded: list[Path] = []
    for index, media_url in enumerate(item.media_urls):
        parsed = urlparse(media_url)
        if parsed.scheme != "https":
            raise ValueError(f"Only HTTPS downloads are allowed: {media_url}")
        suffix = Path(parsed.path).suffix or (".mp4" if item.media_type == "video" else ".jpg")
        destination = target_dir / f"media_{index:03d}{suffix}"
        if not destination.exists():
            _download(media_url, destination)
        downloaded.append(destination)
    return downloaded[0] if len(downloaded) == 1 and item.media_type != "image_sequence" else target_dir


def _download(url: str, destination: Path) -> None:
    def _do_download() -> None:
        with requests.get(url, stream=True, timeout=30) as response:
            if response.status_code in {429, 500, 502, 503, 504}:
                raise RetryableError(f"Transient download error {response.status_code}: {url}")
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        handle.write(chunk)

    with_retry(_do_download)


def _get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=30)
    if response.status_code in {429, 500, 502, 503, 504}:
        raise RetryableError(f"Transient manifest error {response.status_code}: {url}")
    response.raise_for_status()
    return response.json()


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)[:90]


def _file_list(path: Path) -> list[str]:
    if path.is_file():
        return [str(path)]
    return [str(p) for p in sorted(path.iterdir()) if p.is_file()]
