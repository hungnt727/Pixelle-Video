# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
YouTubePublisher — uploads a generated MP4 to YouTube via the Data API v3.

Reads OAuth client + cached refresh token from paths in `config.publishers.youtube`.
Uses resumable upload so large files survive transient network blips; reports
chunk progress via the optional `progress_callback`.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger
from pydantic import BaseModel

from pixelle_video.config import YouTubeConfig
from pixelle_video.publishers.base import BasePublisher, PublishResult

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
WATCH_URL_TEMPLATE = "https://www.youtube.com/watch?v={video_id}"


class YouTubeUploadError(RuntimeError):
    """Raised when the YouTube upload cannot proceed."""


class YouTubePublisher(BasePublisher):
    """Upload a local MP4 to YouTube using OAuth 2.0 + Data API v3 resumable upload."""

    platform = "youtube"

    def __init__(self, config: YouTubeConfig):
        self.config = config

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        **opts: Any,
    ) -> PublishResult:
        if not Path(video_path).exists():
            raise YouTubeUploadError(f"Video file does not exist: {video_path}")

        privacy_status = opts.get("privacy_status") or self.config.default_privacy_status
        category_id = opts.get("category_id") or self.config.default_category_id
        made_for_kids = opts.get("made_for_kids")
        if made_for_kids is None:
            made_for_kids = self.config.default_made_for_kids
        language = opts.get("language") or self.config.default_language

        max_tags = self.config.max_tags
        capped_tags = list(tags)[:max_tags] if max_tags >= 0 else list(tags)

        snippet: dict[str, Any] = {
            "title": title[:100],
            "description": description[:5000],
            "tags": capped_tags,
            "categoryId": category_id,
        }
        if language:
            snippet["defaultLanguage"] = language
            snippet["defaultAudioLanguage"] = language

        status_body = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        }

        body = {"snippet": snippet, "status": status_body}

        logger.info(
            f"📤 Uploading to YouTube: title='{snippet['title']}' "
            f"privacy={privacy_status} category={category_id}"
        )
        response = await asyncio.to_thread(
            _do_resumable_upload,
            config=self.config,
            video_path=video_path,
            body=body,
            progress_callback=progress_callback,
        )

        video_id = response.get("id")
        if not video_id:
            raise YouTubeUploadError(f"YouTube response missing 'id': {response}")
        url = WATCH_URL_TEMPLATE.format(video_id=video_id)
        logger.success(f"✅ YouTube upload complete: {url}")

        return PublishResult(
            platform=self.platform,
            remote_id=video_id,
            url=url,
            title=snippet["title"],
            privacy_status=privacy_status,
            metadata={
                "category_id": category_id,
                "language": language,
                "tags": capped_tags,
                "made_for_kids": bool(made_for_kids),
            },
        )


# ---------------------------------------------------------------------------
# Sync helpers (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------

# The Google API helpers below are defined as plain `def` because
# `google-api-python-client` is sync. Keeping them at module scope (rather than
# methods) makes them trivially mockable in tests and avoids passing `self`
# through `asyncio.to_thread`.


class _LoadedCredentials(BaseModel):
    """Internal shape returned by the credentials loader."""

    client_secrets_path: str
    token_path: str


def _resolve_credentials_paths(config: YouTubeConfig) -> _LoadedCredentials:
    client_secrets = Path(config.client_secrets_file)
    token_path = Path(config.token_file)

    if not client_secrets.exists():
        raise YouTubeUploadError(
            f"YouTube OAuth client secrets file not found: {client_secrets}. "
            "Download it from Google Cloud Console → APIs & Services → Credentials → "
            "OAuth 2.0 Client IDs (Desktop app), and save it at the configured path."
        )
    if not token_path.exists():
        raise YouTubeUploadError(
            f"YouTube refresh token not found at {token_path}. "
            "Run: `uv run python -m pixelle_video.publishers.youtube.auth` to "
            "complete the one-time OAuth flow."
        )

    return _LoadedCredentials(
        client_secrets_path=str(client_secrets),
        token_path=str(token_path),
    )


def _build_youtube_client(config: YouTubeConfig):
    """Construct an authenticated YouTube Data API v3 client (sync)."""
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    paths = _resolve_credentials_paths(config)

    with open(paths.token_path, "r", encoding="utf-8") as f:
        token_data = json.load(f)

    creds = Credentials.from_authorized_user_info(token_data, scopes=[YOUTUBE_UPLOAD_SCOPE])
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            # Persist refreshed token so we don't burn refresh calls every upload
            Path(paths.token_path).write_text(creds.to_json(), encoding="utf-8")
        else:
            raise YouTubeUploadError(
                "Cached YouTube credentials are invalid and cannot be refreshed. "
                "Re-run the OAuth CLI to obtain a new refresh token."
            )

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _do_resumable_upload(
    config: YouTubeConfig,
    video_path: str,
    body: dict[str, Any],
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict[str, Any]:
    """Drive the resumable upload loop. Returns the final API response dict."""
    from googleapiclient.http import MediaFileUpload

    youtube = _build_youtube_client(config)

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response: Optional[dict[str, Any]] = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            try:
                progress_callback(int(status.resumable_progress), int(status.total_size))
            except Exception as e:
                logger.warning(f"YouTube progress callback raised: {e}")
    return response
