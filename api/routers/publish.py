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

"""Publish endpoints — upload a previously generated video to a social platform."""

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.dependencies import PixelleVideoDep
from api.schemas.publish import PublishRequest, PublishResponse
from api.tasks import TaskType, task_manager

router = APIRouter(prefix="/publish", tags=["Publish"])


async def enqueue_publish_task(
    task_id: str,
    request_body: PublishRequest,
    pixelle_video,
) -> tuple[str, bool]:
    """
    Shared helper: enqueue a PUBLISH task in TaskManager and return its id.

    Used both by POST /api/publish/{task_id} and by the auto_publish chain on
    the generate endpoints. Returns (publish_task_id, cached).

    `cached` here is a best-effort *pre-check*: we peek at metadata first to
    tell the caller whether the actual upload was skipped — but the publish
    coroutine runs through TaskManager unconditionally so progress and
    final result land in the same place.
    """
    metadata = await pixelle_video.persistence.load_task_metadata(task_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    pre_cached = bool(
        (metadata.get("published_to") or {}).get(request_body.platform) and not request_body.force
    )

    publish_task = task_manager.create_task(
        task_type=TaskType.PUBLISH,
        request_params={
            "task_id": task_id,
            **request_body.model_dump(exclude_none=True),
        },
    )

    async def execute_publish():
        def _progress(uploaded: int, total: int):
            task_manager.update_progress(
                publish_task.task_id,
                uploaded,
                total or 1,
                message=f"Uploading to {request_body.platform}",
            )

        result, cached = await pixelle_video.publish(
            task_id=task_id,
            platform=request_body.platform,
            force=request_body.force,
            title_override=request_body.title_override,
            description_override=request_body.description_override,
            tags_override=request_body.tags_override,
            privacy_status=request_body.privacy_status,
            progress_callback=_progress,
        )
        return {
            "platform": result.platform,
            "url": result.url,
            "remote_id": result.remote_id,
            "title": result.title,
            "privacy_status": result.privacy_status,
            "cached": cached,
        }

    await task_manager.execute_task(publish_task.task_id, execute_publish)
    return publish_task.task_id, pre_cached


@router.post("/{task_id}", response_model=PublishResponse)
async def publish_task(
    task_id: str,
    request_body: PublishRequest,
    pixelle_video: PixelleVideoDep,
):
    """
    Publish a previously generated video to a social platform.

    The request returns immediately with a `publish_task_id`. Poll
    `GET /api/tasks/{publish_task_id}` for status and final URL.

    Idempotent: if `task_id` was already published to the given platform,
    the publish task completes immediately with `cached=true` (unless
    `force=true` is passed).
    """
    try:
        logger.info(f"Publish requested for task {task_id} → {request_body.platform}")
        publish_task_id, pre_cached = await enqueue_publish_task(
            task_id=task_id,
            request_body=request_body,
            pixelle_video=pixelle_video,
        )
        return PublishResponse(
            publish_task_id=publish_task_id,
            task_id=task_id,
            cached=pre_cached,
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Publish error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
