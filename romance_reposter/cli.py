from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .config import load_config
from .dashboard import show_dashboard
from .demo import create_demo
from .workflow import collect as collect_workflow
from .workflow import open_database, post_due, queue as queue_workflow
from .workflow import render as render_workflow
from .workflow import run_once as run_once_workflow

app = typer.Typer(help="Compliant romance short-form reposting automation.")
console = Console()


def _config(path: Path):
    return load_config(path)


@app.command()
def collect(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Collect approved, licensed source content into SQLite."""

    cfg = _config(config)
    db = open_database(cfg)
    try:
        added, rejected = collect_workflow(cfg, db)
        console.print(f"Collected {added} new asset(s); rejected/skipped {rejected}.")
    finally:
        db.close()


@app.command()
def render(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Render collected assets into vertical short-form videos."""

    cfg = _config(config)
    db = open_database(cfg)
    try:
        count = render_workflow(cfg, db)
        console.print(f"Rendered {count} video(s).")
    finally:
        db.close()


@app.command(name="queue")
def queue_command(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Queue rendered videos for configured platforms."""

    cfg = _config(config)
    db = open_database(cfg)
    try:
        count = queue_workflow(cfg, db)
        console.print(f"Queued {count} platform post(s).")
    finally:
        db.close()


@app.command(name="post-due")
def post_due_command(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Post queued items whose scheduled time has arrived."""

    cfg = _config(config)
    db = open_database(cfg)
    try:
        posted, failed = post_due(cfg, db)
        verb = "Simulated" if cfg.dry_run else "Posted"
        console.print(f"{verb} {posted}; failed {failed}.")
    finally:
        db.close()


@app.command()
def dashboard(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Show local queue, posted, and failed-upload status."""

    cfg = _config(config)
    db = open_database(cfg)
    try:
        show_dashboard(db)
    finally:
        db.close()


@app.command(name="run-once")
def run_once(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Run collect, render, queue, and post-due once."""

    cfg = _config(config)
    db = open_database(cfg)
    try:
        result = run_once_workflow(cfg, db)
        if cfg.dry_run:
            result["posting_mode"] = "dry_run"
        console.print(result)
    finally:
        db.close()


@app.command()
def demo(config: Path = typer.Option("config.yaml", "--config", "-c")) -> None:
    """Create a local synthetic demo source and demo config."""

    cfg = _config(config)
    demo_config = create_demo(cfg)
    console.print(f"Demo content created. Use --config {demo_config}")
