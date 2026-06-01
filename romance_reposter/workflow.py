from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .captions import generate_caption
from .collection import collect_sources
from .config import AppConfig, ensure_storage
from .db import Database
from .media import render_asset
from .posting import poster_for
from .scheduler import next_schedule_times


def open_database(config: AppConfig) -> Database:
    ensure_storage(config)
    db = Database(config.database_path)
    db.init()
    return db


def collect(config: AppConfig, db: Database) -> tuple[int, int]:
    return collect_sources(config, db)


def render(config: AppConfig, db: Database) -> int:
    rendered = 0
    for asset in db.list_unrendered_assets():
        captions = generate_caption(asset, config)
        video_path, thumbnail_path = render_asset(asset, captions, config)
        render_id = db.add_render(
            asset["id"],
            video_path,
            thumbnail_path,
            captions.title,
            captions.platform_caption,
            captions.hashtags,
            captions.emotion,
            {
                "source_asset_id": asset["id"],
                "subtitle_lines": captions.subtitle_lines,
                "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
            },
        )
        if render_id is not None:
            rendered += 1
    return rendered


def queue(config: AppConfig, db: Database) -> int:
    targets = list(config.get("posting.targets", []))
    renders = db.list_unqueued_renders()
    schedule_count = len(renders) * len(targets)
    schedules = iter(next_schedule_times(config, schedule_count) if schedule_count else [])
    queued = 0
    for render_row in renders:
        for platform in targets:
            scheduled_at = next(schedules)
            queue_id = db.queue_post(render_row["id"], platform, scheduled_at)
            if queue_id is not None:
                queued += 1
    return queued


def post_due(config: AppConfig, db: Database) -> tuple[int, int]:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    posted = 0
    failed = 0
    max_attempts = int(config.get("posting.retry.max_attempts", 4))
    for row in db.due_queue(now_iso):
        try:
            poster = poster_for(row["platform"], config)
            result = poster.post(row)
            if not config.dry_run:
                db.mark_posted(row["id"], result.remote_id)
            posted += 1
        except Exception as exc:
            terminal = int(row["attempts"]) + 1 >= max_attempts
            db.mark_failed(row["id"], str(exc), terminal=terminal)
            failed += 1
    return posted, failed


def run_once(config: AppConfig, db: Database) -> dict[str, Any]:
    added, rejected = collect(config, db)
    rendered = render(config, db)
    queued = queue(config, db)
    posted, failed = post_due(config, db)
    return {
        "added": added,
        "rejected": rejected,
        "rendered": rendered,
        "queued": queued,
        "posted": posted,
        "failed": failed,
    }
