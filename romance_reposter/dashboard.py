from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .db import Database


def show_dashboard(db: Database) -> None:
    """Render a compact local terminal dashboard."""

    console = Console()
    counts = Table(title="Post Queue Status")
    counts.add_column("Platform")
    counts.add_column("Status")
    counts.add_column("Count", justify="right")
    for row in db.counts_by_status():
        counts.add_row(row["platform"], row["status"], str(row["count"]))
    console.print(counts)

    recent = Table(title="Recent Queue Items")
    recent.add_column("ID", justify="right")
    recent.add_column("Platform")
    recent.add_column("Status")
    recent.add_column("Scheduled")
    recent.add_column("Title")
    recent.add_column("Last Error")
    for row in db.recent_queue(limit=20):
        recent.add_row(
            str(row["id"]),
            row["platform"],
            row["status"],
            row["scheduled_at"],
            row["title"][:46],
            (row["last_error"] or "")[:46],
        )
    console.print(recent)
