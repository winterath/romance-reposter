from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import MediaInfo, SourceItem, utc_now_iso


class Database:
    """SQLite persistence for assets, renders, queue state, and API outcomes."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.conn.close()

    def init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                canonical_url TEXT,
                media_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                license TEXT NOT NULL,
                permission_note TEXT,
                creator TEXT NOT NULL,
                creator_handle TEXT,
                title TEXT NOT NULL,
                description TEXT,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                duration_seconds REAL,
                checksum TEXT NOT NULL,
                emotion TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source_id, external_id),
                UNIQUE(checksum)
            );

            CREATE TABLE IF NOT EXISTS rendered_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                path TEXT NOT NULL,
                thumbnail_path TEXT,
                title TEXT NOT NULL,
                caption TEXT NOT NULL,
                hashtags_json TEXT NOT NULL,
                emotion TEXT,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(asset_id)
            );

            CREATE TABLE IF NOT EXISTS post_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rendered_video_id INTEGER NOT NULL REFERENCES rendered_videos(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                status TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                remote_id TEXT,
                posted_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(rendered_video_id, platform)
            );

            CREATE INDEX IF NOT EXISTS idx_post_queue_due
            ON post_queue(status, scheduled_at);
            """
        )
        self.conn.commit()

    def upsert_asset(
        self,
        item: SourceItem,
        media_path: Path,
        media_info: MediaInfo,
        checksum: str,
        metadata: dict[str, Any],
    ) -> int | None:
        """Insert a new asset. Return None when a duplicate already exists."""

        try:
            cursor = self.conn.execute(
                """
                INSERT INTO assets (
                    source_id, external_id, canonical_url, media_path, media_type,
                    license, permission_note, creator, creator_handle, title,
                    description, width, height, duration_seconds, checksum, emotion,
                    metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.source_id,
                    item.external_id,
                    item.credit_url,
                    str(media_path),
                    item.media_type,
                    item.license,
                    item.permission_note,
                    item.creator,
                    item.creator_handle,
                    item.title,
                    item.description,
                    media_info.width,
                    media_info.height,
                    media_info.duration_seconds,
                    checksum,
                    metadata.get("emotion"),
                    json.dumps(metadata, ensure_ascii=True),
                    utc_now_iso(),
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def list_unrendered_assets(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT assets.*
                FROM assets
                LEFT JOIN rendered_videos ON rendered_videos.asset_id = assets.id
                WHERE rendered_videos.id IS NULL
                ORDER BY assets.created_at ASC
                """
            )
        )

    def add_render(
        self,
        asset_id: int,
        path: Path,
        thumbnail_path: Path | None,
        title: str,
        caption: str,
        hashtags: Iterable[str],
        emotion: str,
        metadata: dict[str, Any],
    ) -> int | None:
        try:
            cursor = self.conn.execute(
                """
                INSERT INTO rendered_videos (
                    asset_id, path, thumbnail_path, title, caption, hashtags_json,
                    emotion, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    str(path),
                    str(thumbnail_path) if thumbnail_path else None,
                    title,
                    caption,
                    json.dumps(list(hashtags), ensure_ascii=True),
                    emotion,
                    json.dumps(metadata, ensure_ascii=True),
                    utc_now_iso(),
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def list_unqueued_renders(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT rendered_videos.*, assets.creator, assets.creator_handle, assets.canonical_url
                FROM rendered_videos
                JOIN assets ON assets.id = rendered_videos.asset_id
                ORDER BY rendered_videos.created_at ASC
                """
            )
        )

    def queue_post(self, rendered_video_id: int, platform: str, scheduled_at: str) -> int | None:
        try:
            cursor = self.conn.execute(
                """
                INSERT INTO post_queue (
                    rendered_video_id, platform, status, scheduled_at, created_at
                )
                VALUES (?, ?, 'queued', ?, ?)
                """,
                (rendered_video_id, platform, scheduled_at, utc_now_iso()),
            )
            self.conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def due_queue(self, now_iso: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT
                    post_queue.*,
                    rendered_videos.path,
                    rendered_videos.thumbnail_path,
                    rendered_videos.title,
                    rendered_videos.caption,
                    rendered_videos.hashtags_json,
                    rendered_videos.metadata_json,
                    assets.creator,
                    assets.creator_handle,
                    assets.canonical_url,
                    assets.duration_seconds
                FROM post_queue
                JOIN rendered_videos ON rendered_videos.id = post_queue.rendered_video_id
                JOIN assets ON assets.id = rendered_videos.asset_id
                WHERE post_queue.status = 'queued'
                  AND post_queue.scheduled_at <= ?
                ORDER BY post_queue.scheduled_at ASC
                """,
                (now_iso,),
            )
        )

    def mark_posted(self, queue_id: int, remote_id: str | None) -> None:
        self.conn.execute(
            """
            UPDATE post_queue
            SET status = 'posted', remote_id = ?, posted_at = ?, last_error = NULL
            WHERE id = ?
            """,
            (remote_id, utc_now_iso(), queue_id),
        )
        self.conn.commit()

    def mark_failed(self, queue_id: int, error: str, *, terminal: bool) -> None:
        status = "failed" if terminal else "queued"
        self.conn.execute(
            """
            UPDATE post_queue
            SET attempts = attempts + 1, last_error = ?, status = ?
            WHERE id = ?
            """,
            (error[:2000], status, queue_id),
        )
        self.conn.commit()

    def counts_by_status(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT platform, status, COUNT(*) AS count
                FROM post_queue
                GROUP BY platform, status
                ORDER BY platform, status
                """
            )
        )

    def recent_queue(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT post_queue.*, rendered_videos.title
                FROM post_queue
                JOIN rendered_videos ON rendered_videos.id = post_queue.rendered_video_id
                ORDER BY post_queue.scheduled_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )
