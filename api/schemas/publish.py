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

"""Publish API schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PublishRequest(BaseModel):
    """Body for POST /api/publish/{task_id} and the `publish` sub-object on a generate request."""

    platform: Literal["youtube"] = Field(default="youtube", description="Target platform")
    force: bool = Field(
        default=False,
        description="If true, re-upload even when this task was already published.",
    )
    title_override: Optional[str] = Field(
        default=None,
        description="Custom title. If omitted, uses Storyboard.title.",
    )
    description_override: Optional[str] = Field(
        default=None,
        description="Custom description. If omitted, the LLM generates one at publish time.",
    )
    tags_override: Optional[list[str]] = Field(
        default=None,
        description="Custom tag list. If omitted, the LLM generates tags alongside the description.",
    )
    privacy_status: Optional[Literal["private", "unlisted", "public"]] = Field(
        default=None,
        description="Override the default privacy status from config.",
    )


class PublishResponse(BaseModel):
    """Response from POST /api/publish/{task_id}."""

    success: bool = True
    message: str = "Publish task created successfully"
    publish_task_id: str = Field(..., description="Task ID for tracking publish progress")
    task_id: str = Field(..., description="The generation task ID being published")
    cached: bool = Field(
        default=False,
        description="True if this task was already published and no new upload was started.",
    )
