from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

from .config import AppConfig


def create_demo(config: AppConfig) -> Path:
    """Create a tiny synthetic creator drop and a demo config for safe testing."""

    data_dir = config.storage_root
    source_dir = data_dir / "demo_source"
    if source_dir.exists():
        shutil.rmtree(source_dir)
    source_dir.mkdir(parents=True, exist_ok=True)

    panels = [
        ("Panel 1", "They meet every morning\nat the same tiny cafe."),
        ("Panel 2", "Neither of them calls it a date.\nEveryone else does."),
        ("Panel 3", "The confession happens quietly,\nlike it was always true."),
    ]
    for index, (label, text) in enumerate(panels, start=1):
        _panel(source_dir / f"panel_{index:02d}.png", label, text)

    metadata = {
        "id": "demo_slow_burn_comic",
        "title": "They Do Not Realize It Yet",
        "description": "A wholesome slow-burn romance demo comic for pipeline testing.",
        "creator": "Synthetic Demo Creator",
        "creator_handle": "@syntheticdemo",
        "credit_url": "https://example.com/synthetic-demo",
        "license": "EXPLICIT_PERMISSION",
        "permission_note": "Synthetic content generated locally for testing.",
        "tags": ["slow-burn romance", "wholesome couples", "heartwarming webcomics"],
    }
    (source_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    demo_config = dict(config.raw)
    demo_config["sources"] = [
        {
            "id": "demo_local_creator",
            "enabled": True,
            "type": "local_folder",
            "folder": str(source_dir),
            "creator": "Synthetic Demo Creator",
            "creator_handle": "@syntheticdemo",
            "license": "EXPLICIT_PERMISSION",
            "permission_note": "Synthetic content generated locally for testing.",
            "credit_url": "https://example.com/synthetic-demo",
        }
    ]
    demo_config.setdefault("posting", {})["dry_run"] = True
    output = data_dir / "demo_config.yaml"
    output.write_text(yaml.safe_dump(demo_config, sort_keys=False), encoding="utf-8")
    return output


def _panel(path: Path, label: str, text: str) -> None:
    image = Image.new("RGB", (1200, 1400), (246, 240, 232))
    draw = ImageDraw.Draw(image)
    title_font = _font(58)
    body_font = _font(66)
    draw.rounded_rectangle((70, 70, 1130, 1330), radius=24, outline=(55, 64, 72), width=8)
    draw.text((110, 110), label, fill=(70, 80, 88), font=title_font)
    draw.ellipse((430, 360, 590, 520), fill=(205, 95, 110), outline=(60, 60, 65), width=5)
    draw.ellipse((610, 360, 770, 520), fill=(92, 145, 158), outline=(60, 60, 65), width=5)
    draw.line((560, 670, 640, 730, 720, 670), fill=(210, 82, 96), width=10)
    y = 850
    for line in text.split("\n"):
        box = draw.textbbox((0, 0), line, font=body_font)
        draw.text(((1200 - (box[2] - box[0])) // 2, y), line, fill=(36, 38, 42), font=body_font)
        y += 96
    image.save(path)


def _font(size: int):
    windir = Path("C:/Windows/Fonts")
    for name in ["segoeui.ttf", "arial.ttf"]:
        candidate = windir / name
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()
