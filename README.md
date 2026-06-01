# Romance Short-Form Reposter

Python automation for collecting approved romance animatics, comic-strip posts, and short videos, rendering them into vertical videos, queueing them safely, and posting through official platform APIs where available.

This project is deliberately conservative. It does not scrape TikTok, Instagram, YouTube, or creator sites, does not bypass logins or captchas, and does not fake engagement. It only collects from source feeds or folders that you explicitly approve and that include a reposting license or permission note.

## Folder Structure

```text
.
+-- romance_reposter/
|   +-- cli.py                 # Command-line entry points
|   +-- collection.py          # Approved-source collection and download logic
|   +-- config.py              # YAML/.env configuration loading
|   +-- dashboard.py           # Local terminal dashboard
|   +-- db.py                  # SQLite schema and persistence helpers
|   +-- media.py               # ffmpeg rendering, probing, thumbnails
|   +-- captions.py            # Caption, hashtags, title, emotion heuristics
|   +-- scheduler.py           # Queue windows and randomized scheduling
|   +-- workflow.py            # End-to-end orchestration
|   +-- posting/
|       +-- base.py
|       +-- youtube.py
|       +-- instagram.py
|       +-- tiktok.py
+-- config.example.yaml        # Example approved-source and platform config
+-- .env.example               # API credential placeholders
+-- requirements.txt
+-- scripts/
    +-- run_once.ps1           # Windows helper script
```

## Platform Compliance Notes

- **TikTok:** Uses TikTok Content Posting API Direct Post / Upload flow. TikTok requires an approved app, user authorization, and the relevant scopes. Unaudited clients may be restricted to private visibility. Official docs: <https://developers.tiktok.com/doc/content-posting-api-get-started>
- **Instagram Reels:** Uses Instagram Graph API Content Publishing flow. Reels publishing requires an Instagram professional account, permissions, a media container, and a public HTTPS video URL or approved upload flow. Official docs: <https://developers.facebook.com/docs/instagram-platform/content-publishing/>
- **YouTube Shorts:** Uses YouTube Data API `videos.insert` through OAuth. Unverified projects may upload videos as private until app verification is complete. Official docs: <https://developers.google.com/youtube/v3/docs/videos/insert>

## Setup on Windows

1. Install Python 3.11+.
2. Install ffmpeg and make sure `ffmpeg.exe` and `ffprobe.exe` are on your PATH.
   - Winget: `winget install Gyan.FFmpeg`
   - Chocolatey: `choco install ffmpeg`
3. Create a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Copy the examples:

   ```powershell
   Copy-Item .env.example .env
   Copy-Item config.example.yaml config.yaml
   ```

5. Edit `config.yaml`:
   - Add only creators/accounts you have permission to repost.
   - Keep `posting.dry_run: true` until you have tested collection, rendering, queueing, and API credentials.
   - Add royalty-free music files under `assets/music/` or update the configured music path.

6. Edit `.env` with platform credentials after you have official API access.

## Source Rules

Every source item must pass all of these checks before download/render:

- The source is listed in `config.yaml`.
- The source item license is in `content.allowed_licenses`.
- If `content.require_permission_note` is true, the item includes a permission note.
- The source item matches at least one configured keyword, such as `slow-burn romance` or `heartwarming webcomics`.
- The downloaded media meets minimum resolution rules.
- The checksum has not already been processed.

## Approved Source Manifest Format

Creators can publish a JSON manifest, or you can maintain one yourself for creators who gave explicit permission.

```json
{
  "items": [
    {
      "id": "slow-burn-001",
      "title": "They keep almost confessing",
      "description": "A wholesome slow-burn comic strip.",
      "creator": "Example Creator",
      "creator_handle": "@examplecreator",
      "credit_url": "https://example.com/slow-burn-001",
      "license": "EXPLICIT_PERMISSION",
      "permission_note": "Creator granted repost permission by email on 2026-05-01.",
      "media_type": "image_sequence",
      "media_urls": [
        "https://example.com/panel-1.png",
        "https://example.com/panel-2.png"
      ],
      "tags": ["slow-burn romance", "wholesome couples"]
    }
  ]
}
```

You can also use a local folder source. Add images/videos plus optional `.json` sidecars with license, credit, tags, and permission details.

## Basic Workflow

Create demo content and render it in dry-run mode:

```powershell
python -m romance_reposter demo --config config.yaml
python -m romance_reposter collect --config data\demo_config.yaml
python -m romance_reposter render --config data\demo_config.yaml
python -m romance_reposter queue --config data\demo_config.yaml
python -m romance_reposter dashboard --config data\demo_config.yaml
```

Run the normal workflow:

```powershell
python -m romance_reposter run-once --config config.yaml
```

Post anything due in the queue:

```powershell
python -m romance_reposter post-due --config config.yaml
```

The helper script does the same:

```powershell
.\scripts\run_once.ps1 -Config config.yaml
```

## Adding New Creators or Sources

1. Get written permission or confirm the license allows reposting on TikTok, Instagram, and YouTube.
2. Add a `sources` entry in `config.yaml`.
3. Add or confirm `license`, `permission_note`, `creator`, `credit_url`, and `tags`.
4. Run `collect` in dry-run mode and inspect `data/reposter.sqlite` or the dashboard.
5. Render and review videos locally before enabling real posting.

## API Credentials

Environment variables are loaded from `.env`.

- `YOUTUBE_CLIENT_SECRETS`: path to Google OAuth client JSON.
- `YOUTUBE_TOKEN_FILE`: local OAuth token cache path.
- `INSTAGRAM_ACCESS_TOKEN`: Instagram Graph API access token.
- `INSTAGRAM_USER_ID`: Instagram professional account ID.
- `TIKTOK_ACCESS_TOKEN`: TikTok user access token authorized for posting.

Instagram requires the rendered video to be reachable by a public HTTPS URL. Configure `platforms.instagram.public_asset_base_url` and host the rendered files on infrastructure you control. TikTok can use local file upload through its upload URL.

## Safety Defaults

- `posting.dry_run` defaults to true.
- TikTok defaults to `SELF_ONLY`.
- Instagram posting is skipped unless a public video URL can be built.
- The queue prevents duplicate platform posts for the same rendered video.
- Retry logic uses exponential backoff and records failures in SQLite.

## What This Does Not Do

- It does not download or repost videos from TikTok/Instagram/YouTube by scraping.
- It does not bypass platform reviews, login challenges, captchas, or rate limits.
- It does not auto-like, auto-comment, follow, or generate fake engagement.
- It does not override copyright or creator terms.
