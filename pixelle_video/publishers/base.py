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
BasePublisher — interface for per-platform video publishers.

Each Publisher takes a completed Generation (identified by task_id + on-disk
metadata) and uploads to one social platform. Idempotency lives outside the
Publisher (in PixelleVideoCore.publish); a Publisher's job is the upload itself.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class PublishResult(BaseModel):
    """Record returned by a Publisher after a successful upload."""

    platform: str = Field(..., description="Platform identifier (e.g. 'youtube')")
    remote_id: str = Field(..., description="Platform-specific video ID")
    url: str = Field(..., description="Public URL to the uploaded video")
    uploaded_at: datetime = Field(default_factory=datetime.now)
    title: Optional[str] = Field(default=None, description="Title actually sent to the platform")
    privacy_status: Optional[str] = Field(
        default=None, description="Privacy state applied at upload time"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Platform-specific extras (e.g. category_id, language, etag)",
    )


class BasePublisher(ABC):
    """
    Interface every platform publisher implements.

    Implementations are constructed once at PixelleVideoCore.initialize() and
    reused across requests. They must be safe to call concurrently (the upload
    method itself can serialise internally if the platform requires it).
    """

    platform: str  # subclasses set this class attribute, e.g. "youtube"

    @abstractmethod
    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        **opts: Any,
    ) -> PublishResult:
        """
        Upload one video.

        Args:
            video_path: Absolute path to the local MP4 file.
            title: Title to set on the platform.
            description: Description body.
            tags: Tag strings (will be truncated by the implementation if needed).
            **opts: Platform-specific overrides (privacy_status, category_id, ...).

        Returns:
            PublishResult with the resulting URL/ID.
        """
        ...
