from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat

from .config import AppConfig
from .models import MediaInfo

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def run_command(command: list[str]) -> None:
    """Run ffmpeg/ffprobe and surface a compact error message."""

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(details[-2000:] or f"Command failed: {command[0]}")


def checksum_path(path: Path) -> str:
    """Compute a stable checksum for one file or a deterministic folder listing."""

    digest = hashlib.sha256()
    if path.is_dir():
        for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(str(file_path.relative_to(path)).encode("utf-8"))
            digest.update(checksum_path(file_path).encode("ascii"))
        return digest.hexdigest()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe(path: Path, ffprobe_path: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return json.loads(result.stdout)


def probe_media(path: Path, media_type: str, config: AppConfig) -> MediaInfo:
    """Read width, height, duration, and fps for a video/image/sequence."""

    if media_type == "video":
        data = ffprobe(path, config.get("ffmpeg.ffprobe_path", "ffprobe"))
        video_stream = next(
            (stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            raise ValueError(f"No video stream found in {path}")
        duration = float(data.get("format", {}).get("duration") or video_stream.get("duration") or 0)
        fps = _parse_fps(video_stream.get("avg_frame_rate"))
        return MediaInfo(
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            duration_seconds=duration,
            fps=fps,
        )

    files = _image_files(path)
    if not files:
        raise ValueError(f"No image files found for {path}")
    dimensions = []
    for file_path in files:
        with Image.open(file_path) as image:
            dimensions.append(image.size)
    width = max(item[0] for item in dimensions)
    height = max(item[1] for item in dimensions)
    return MediaInfo(width=width, height=height, duration_seconds=None, fps=None)


def quality_ok(info: MediaInfo, config: AppConfig) -> bool:
    min_width = int(config.get("content.min_width", 720))
    min_height = int(config.get("content.min_height", 720))
    max_duration = float(config.get("content.max_duration_seconds", 180))
    if info.width < min_width or info.height < min_height:
        return False
    if info.duration_seconds is not None and info.duration_seconds > max_duration:
        return False
    return True


def render_asset(asset_row: Any, caption_package: Any, config: AppConfig) -> tuple[Path, Path | None]:
    """Render one collected asset into a 1080x1920 MP4 plus thumbnail."""

    output_dir = config.renders_dir / f"asset_{asset_row['id']}"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_path = output_dir / "short.mp4"
    thumbnail_path = output_dir / "thumbnail.jpg"
    media_path = Path(asset_row["media_path"])
    media_type = asset_row["media_type"]

    with tempfile.TemporaryDirectory(prefix="romance_reposter_") as tmp_name:
        tmp_dir = Path(tmp_name)
        base_video = tmp_dir / "base.mp4"
        overlaid_video = tmp_dir / "overlaid.mp4"

        if media_type == "video":
            _normalize_video(media_path, base_video, config)
        else:
            _render_image_sequence(media_path, media_type, base_video, config)

        overlay = _make_text_overlay(
            tmp_dir / "overlay.png",
            caption_package.subtitle_lines,
            asset_row["creator"],
            config,
        )
        _overlay_video(base_video, overlay, overlaid_video, config)
        _add_audio(overlaid_video, final_path, config)

    _extract_best_thumbnail(final_path, thumbnail_path, config)
    return final_path, thumbnail_path if thumbnail_path.exists() else None


def _parse_fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        top, bottom = value.split("/", 1)
        return float(top) / float(bottom)
    return float(value)


def _image_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in IMAGE_EXTENSIONS else []
    return sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)


def _normalize_video(input_path: Path, output_path: Path, config: AppConfig) -> None:
    ffmpeg_path = config.get("ffmpeg.ffmpeg_path", "ffmpeg")
    filter_graph = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,format=yuv420p"
    )
    run_command(
        [
            ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-vf",
            filter_graph,
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-an",
            str(output_path),
        ]
    )


def _render_image_sequence(input_path: Path, media_type: str, output_path: Path, config: AppConfig) -> None:
    ffmpeg_path = config.get("ffmpeg.ffmpeg_path", "ffmpeg")
    target_duration = float(config.get("content.target_duration_seconds", 36))

    with tempfile.TemporaryDirectory(prefix="romance_panels_") as panel_tmp:
        panel_dir = Path(panel_tmp)
        images = _prepare_canvases(input_path, media_type, panel_dir / "canvases")
        per_image = max(2.5, target_duration / max(1, len(images)))
        segment_paths: list[Path] = []
        for index, image_path in enumerate(images):
            segment = panel_dir / f"segment_{index:03d}.mp4"
            frames = max(1, int(per_image * 30))
            zoom_expr = "min(zoom+0.00045,1.045)"
            run_command(
                [
                    ffmpeg_path,
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(image_path),
                    "-t",
                    f"{per_image:.3f}",
                    "-vf",
                    f"zoompan=z='{zoom_expr}':d={frames}:s=1080x1920:fps=30,format=yuv420p",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-an",
                    str(segment),
                ]
            )
            segment_paths.append(segment)

        concat_file = panel_dir / "concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{path.as_posix()}'" for path in segment_paths),
            encoding="utf-8",
        )
        run_command(
            [
                ffmpeg_path,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(output_path),
            ]
        )


def _prepare_canvases(input_path: Path, media_type: str, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_images = _image_files(input_path)
    canvases: list[Path] = []
    panel_index = 0

    for image_path in source_images:
        with Image.open(image_path).convert("RGB") as original:
            panels = _split_tall_comic(original) if media_type == "image" and len(source_images) == 1 else [original.copy()]
        for panel in panels:
            canvas = Image.new("RGB", (1080, 1920), (12, 12, 16))
            panel.thumbnail((1020, 1740), Image.Resampling.LANCZOS)
            x = (1080 - panel.width) // 2
            y = (1920 - panel.height) // 2
            canvas.paste(panel, (x, y))
            canvas_path = output_dir / f"panel_{panel_index:03d}.jpg"
            canvas.save(canvas_path, quality=92)
            canvases.append(canvas_path)
            panel.close()
            panel_index += 1
    return canvases


def _split_tall_comic(image: Image.Image) -> list[Image.Image]:
    ratio = image.height / max(1, image.width)
    if ratio < 2.4:
        return [image.copy()]
    viewport_height = int(image.width * 1.55)
    overlap = int(viewport_height * 0.14)
    step = max(1, viewport_height - overlap)
    crops: list[Image.Image] = []
    top = 0
    while top < image.height:
        bottom = min(image.height, top + viewport_height)
        crops.append(image.crop((0, top, image.width, bottom)))
        if bottom == image.height:
            break
        top += step
    return crops


def _make_text_overlay(
    path: Path,
    subtitle_lines: list[str],
    creator: str,
    config: AppConfig,
) -> Path:
    overlay = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    title_font = _font(58)
    small_font = _font(34)

    if config.get("content.subtitles.burn_in", True):
        lines = subtitle_lines[:3]
        line_heights = [draw.textbbox((0, 0), line, font=title_font)[3] for line in lines]
        total_height = sum(line_heights) + 22 * max(0, len(lines) - 1)
        y = 1450 - total_height // 2
        for line in lines:
            box = draw.textbbox((0, 0), line, font=title_font)
            text_width = box[2] - box[0]
            x = (1080 - text_width) // 2
            draw.rounded_rectangle(
                (x - 34, y - 18, x + text_width + 34, y + 78),
                radius=18,
                fill=(0, 0, 0, 150),
            )
            draw.text((x, y), line, fill=(255, 255, 255, 255), font=title_font)
            y += 92

    watermark = config.get("content.watermark", {}) or {}
    if watermark.get("enabled", False):
        template = watermark.get("text_template", "Credit: {creator}")
        credit = template.format(creator=creator)
        draw.text((44, 1818), credit[:80], fill=(255, 255, 255, 210), font=small_font)

    overlay.save(path)
    return path


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _overlay_video(base_video: Path, overlay: Path, output_path: Path, config: AppConfig) -> None:
    ffmpeg_path = config.get("ffmpeg.ffmpeg_path", "ffmpeg")
    run_command(
        [
            ffmpeg_path,
            "-y",
            "-i",
            str(base_video),
            "-i",
            str(overlay),
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-an",
            str(output_path),
        ]
    )


def _add_audio(input_video: Path, output_path: Path, config: AppConfig) -> None:
    ffmpeg_path = config.get("ffmpeg.ffmpeg_path", "ffmpeg")
    music_config = config.get("content.music", {}) or {}
    music_path = config.path_value("content.music.path", "assets/music/background.mp3")
    volume = float(music_config.get("volume", 0.12))

    if music_config.get("enabled", True) and music_path.exists():
        run_command(
            [
                ffmpeg_path,
                "-y",
                "-i",
                str(input_video),
                "-stream_loop",
                "-1",
                "-i",
                str(music_path),
                "-filter_complex",
                f"[1:a]volume={volume}[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-shortest",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(output_path),
            ]
        )
        return

    run_command(
        [
            ffmpeg_path,
            "-y",
            "-i",
            str(input_video),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-shortest",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            str(output_path),
        ]
    )


def _extract_best_thumbnail(video_path: Path, thumbnail_path: Path, config: AppConfig) -> None:
    ffmpeg_path = config.get("ffmpeg.ffmpeg_path", "ffmpeg")
    with tempfile.TemporaryDirectory(prefix="romance_thumb_") as tmp_name:
        tmp_dir = Path(tmp_name)
        pattern = tmp_dir / "frame_%03d.jpg"
        run_command(
            [
                ffmpeg_path,
                "-y",
                "-i",
                str(video_path),
                "-vf",
                "fps=1/3,scale=540:-1",
                "-frames:v",
                "12",
                str(pattern),
            ]
        )
        frames = sorted(tmp_dir.glob("frame_*.jpg"))
        if not frames:
            return
        best = max(frames, key=_emotional_frame_score)
        shutil.copyfile(best, thumbnail_path)


def _emotional_frame_score(path: Path) -> float:
    with Image.open(path).convert("RGB") as image:
        stat = ImageStat.Stat(image)
        brightness = sum(stat.mean) / 3
        contrast = sum(stat.stddev) / 3
        saturation = ImageStat.Stat(image.convert("HSV")).mean[1]
    # Favor bright, saturated, higher-contrast frames without over-optimizing.
    return brightness * 0.25 + contrast * 0.45 + saturation * 0.30
