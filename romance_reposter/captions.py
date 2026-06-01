from __future__ import annotations

import json
import random
import re
from textwrap import wrap
from typing import Any

from .config import AppConfig
from .models import CaptionPackage


EMOTION_KEYWORDS = {
    "cute": ["cute", "wholesome", "soft", "sweet", "cuddle", "couple"],
    "sad": ["sad", "cry", "heartbreak", "destroyed", "miss", "goodbye"],
    "comfort": ["comfort", "healing", "safe", "home", "gentle"],
    "flirty": ["flirty", "crush", "tease", "blush", "confess"],
    "slow_burn": ["slow burn", "slow-burn", "almost", "confess", "pining"],
}

CAPTION_TEMPLATES = {
    "slow_burn": [
        "they do not realize they are already in love",
        "slow burn relationships hit different",
        "the almost-confession energy is unreal",
    ],
    "sad": [
        "this comic actually destroyed me emotionally",
        "the quiet heartbreak got me",
        "some panels do emotional damage gently",
    ],
    "comfort": [
        "this is what feeling safe with someone looks like",
        "soft comfort stories always stay with me",
        "the gentle kind of love wins every time",
    ],
    "flirty": [
        "the way they are both pretending not to notice",
        "that blush gave the whole plot away",
        "they are flirting like nobody can see them",
    ],
    "cute": [
        "wholesome couples make the timeline softer",
        "tiny romantic moments, maximum feelings",
        "this is aggressively adorable",
    ],
}


def classify_emotion(text: str) -> str:
    """Classify the emotional lane with a local keyword heuristic."""

    lowered = text.lower()
    scores = {
        emotion: sum(1 for needle in needles if needle in lowered)
        for emotion, needles in EMOTION_KEYWORDS.items()
    }
    best, score = max(scores.items(), key=lambda item: item[1])
    return best if score > 0 else "cute"


def _clean_hashtag(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", value.replace(" ", ""))
    return cleaned[:40]


def _keyword_hashtags(text: str, keywords: list[str]) -> list[str]:
    tags: list[str] = []
    lowered = text.lower()
    for keyword in keywords:
        if keyword.lower() in lowered:
            tags.append(_clean_hashtag(keyword))
    return [tag for tag in tags if tag]


def generate_caption(asset_row: Any, config: AppConfig) -> CaptionPackage:
    """Generate title, caption, hashtags, emotion, and simple subtitle lines."""

    metadata = json.loads(asset_row["metadata_json"])
    keywords = list(config.get("content.keywords", []))
    default_hashtags = list(config.get("content.default_hashtags", []))
    max_hashtags = int(config.get("content.max_hashtags", 7))

    text = " ".join(
        [
            asset_row["title"] or "",
            asset_row["description"] or "",
            " ".join(metadata.get("tags", [])),
        ]
    )
    emotion = classify_emotion(text)
    template = random.choice(CAPTION_TEMPLATES.get(emotion, CAPTION_TEMPLATES["cute"]))

    creator_handle = asset_row["creator_handle"] or asset_row["creator"]
    credit = f"Credit: {creator_handle}"
    caption = f"{template}\n\n{credit}"

    keyword_tags = _keyword_hashtags(text, keywords)
    hashtags = []
    for tag in keyword_tags + default_hashtags:
        clean = _clean_hashtag(tag)
        if clean and clean.lower() not in {existing.lower() for existing in hashtags}:
            hashtags.append(clean)
        if len(hashtags) >= max_hashtags:
            break

    title_suffix = config.get("platforms.youtube.title_suffix", "")
    title_base = asset_row["title"] or template
    title = f"{title_base}{title_suffix}".strip()

    words_per_line = int(config.get("content.subtitles.max_words_per_line", 7))
    subtitle_lines = wrap(template, width=max(18, words_per_line * 8))
    if not subtitle_lines:
        subtitle_lines = [template]

    return CaptionPackage(
        title=title[:100],
        caption=caption[:1800],
        hashtags=hashtags,
        emotion=emotion,
        subtitle_lines=subtitle_lines[:3],
    )
