from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .base import PlatformPoster, PostResult

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubePoster(PlatformPoster):
    """Upload Shorts through the official YouTube Data API."""

    platform = "youtube"

    def post(self, queue_row: Any) -> PostResult:
        service = self._service()
        tags = json.loads(queue_row["hashtags_json"])
        body = {
            "snippet": {
                "title": queue_row["title"][:100],
                "description": self._description(queue_row),
                "tags": tags,
                "categoryId": self.config.get("platforms.youtube.category_id", "22"),
            },
            "status": {
                "privacyStatus": self.config.get("platforms.youtube.privacy_status", "private"),
                "selfDeclaredMadeForKids": bool(
                    self.config.get("platforms.youtube.made_for_kids", False)
                ),
            },
        }
        media = MediaFileUpload(str(queue_row["path"]), chunksize=-1, resumable=True)
        request = service.videos().insert(part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            _, response = request.next_chunk()
        remote_id = response.get("id")
        return PostResult("youtube", remote_id, f"Uploaded YouTube video {remote_id}")

    def _service(self):
        client_secrets = os.getenv("YOUTUBE_CLIENT_SECRETS")
        if not client_secrets:
            raise RuntimeError("YOUTUBE_CLIENT_SECRETS is required for YouTube posting")
        token_file = Path(os.getenv("YOUTUBE_TOKEN_FILE", "data/youtube_token.json"))
        token_file.parent.mkdir(parents=True, exist_ok=True)

        credentials = None
        if token_file.exists():
            credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        if not credentials or not credentials.valid:
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets, SCOPES)
            credentials = flow.run_local_server(port=0)
            token_file.write_text(credentials.to_json(), encoding="utf-8")
        return build("youtube", "v3", credentials=credentials)

    def _description(self, queue_row: Any) -> str:
        caption = queue_row["caption"]
        creator = queue_row["creator_handle"] or queue_row["creator"]
        credit = f"Original creator: {creator}"
        url = queue_row["canonical_url"]
        permission = "Reposted from an approved/licensed source."
        parts = [caption, credit, permission]
        if url:
            parts.append(f"Source: {url}")
        return "\n\n".join(parts)[:5000]
