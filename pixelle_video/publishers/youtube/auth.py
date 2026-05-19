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
One-time interactive OAuth setup for the YouTube publisher.

Run on a machine with a browser:

    uv run python -m pixelle_video.publishers.youtube.auth

A local browser window opens, the user authorises the `youtube.upload` scope,
and the resulting refresh token is written to the path configured in
`config.publishers.youtube.token_file`. After this, the API service can run
headless and upload without re-prompting until Google revokes the token
(typically after ~6 months of inactivity).
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

from pixelle_video.config import config_manager
from pixelle_video.publishers.youtube.publisher import YOUTUBE_UPLOAD_SCOPE


def run_oauth_flow(config_path: str = "config.yaml") -> Path:
    """Open browser, run the InstalledAppFlow, save refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    yt = config_manager.config.publishers.youtube
    client_secrets = Path(yt.client_secrets_file)
    token_path = Path(yt.token_file)

    if not client_secrets.exists():
        raise SystemExit(
            f"❌ Client secrets file not found: {client_secrets}\n"
            "Download OAuth 2.0 client (type: Desktop app) JSON from\n"
            "https://console.cloud.google.com/apis/credentials and save it there."
        )

    logger.info(f"🔐 Starting OAuth flow with client secrets: {client_secrets}")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets), scopes=[YOUTUBE_UPLOAD_SCOPE]
    )
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.success(f"✅ Refresh token saved to: {token_path}")
    return token_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-time YouTube OAuth setup for Pixelle-Video")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    args = parser.parse_args(argv)

    try:
        run_oauth_flow(args.config)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"OAuth flow failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
