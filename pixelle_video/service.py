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
Pixelle-Video Core - Service Layer

Provides unified access to all capabilities (LLM, TTS, Image, etc.)
"""

import hashlib
import json
import re
from typing import Any, Callable, Optional

from comfykit import ComfyKit
from loguru import logger

from pixelle_video.config import config_manager
from pixelle_video.pipelines.asset_based import AssetBasedPipeline
from pixelle_video.pipelines.custom import CustomPipeline
from pixelle_video.pipelines.standard import StandardPipeline
from pixelle_video.publishers.base import BasePublisher, PublishResult
from pixelle_video.services.frame_processor import FrameProcessor
from pixelle_video.services.history_manager import HistoryManager
from pixelle_video.services.image_analysis import ImageAnalysisService
from pixelle_video.services.llm_service import LLMService
from pixelle_video.services.media import MediaService
from pixelle_video.services.persistence import PersistenceService
from pixelle_video.services.tts_service import TTSService
from pixelle_video.services.video import VideoService
from pixelle_video.services.video_analysis import VideoAnalysisService


class PixelleVideoCore:
    """
    Pixelle-Video Core - Service Layer
    
    Provides unified access to all capabilities.
    
    Usage:
        from pixelle_video import pixelle_video
        
        # Initialize
        await pixelle_video.initialize()
        
        # Use capabilities directly
        answer = await pixelle_video.llm("Explain atomic habits")
        audio = await pixelle_video.tts("Hello world")
        media = await pixelle_video.media(prompt="a cat")
        
        # Check active capabilities
        print(f"Using LLM: {pixelle_video.llm.active}")
        print(f"Available TTS: {pixelle_video.tts.available}")
    
    Architecture (Simplified):
        PixelleVideoCore (this class)
          ├── config (configuration)
          ├── llm (LLM service - direct OpenAI SDK)
          ├── tts (TTS service - ComfyKit workflows)
          ├── media (Media service - ComfyKit workflows, supports image & video)
          └── pipelines (video generation pipelines)
              ├── standard (standard workflow)
              ├── custom (custom workflow template)
              └── ... (extensible)
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize Pixelle-Video Core
        
        Args:
            config_path: Path to configuration file
        """
        # Use global config manager singleton
        self.config = config_manager.config.to_dict()
        self._initialized = False
        
        # ComfyKit lazy initialization (created on first use, recreated on config change)
        self._comfykit: Optional[ComfyKit] = None
        self._comfykit_config_hash: Optional[str] = None
        
        # Core services (initialized in initialize())
        self.llm: Optional[LLMService] = None
        self.tts: Optional[TTSService] = None
        self.media: Optional[MediaService] = None
        self.video: Optional[VideoService] = None
        self.frame_processor: Optional[FrameProcessor] = None
        self.persistence: Optional[PersistenceService] = None
        self.history: Optional[HistoryManager] = None
        
        # Video generation pipelines (dictionary of pipeline_name -> pipeline_instance)
        self.pipelines = {}

        # Publishers (dictionary of platform_name -> BasePublisher), populated in initialize()
        self._publishers: dict[str, BasePublisher] = {}

        # Default pipeline callable (for backward compatibility)
        self.generate_video = None
    
    def _get_comfykit_config(self) -> dict:
        """
        Get current ComfyKit configuration from config_manager
        
        Returns:
            ComfyKit configuration dict
        """
        # Reload config from global config_manager (to support hot reload)
        self.config = config_manager.config.to_dict()
        
        comfyui_config = self.config.get("comfyui", {})
        kit_config = {}
        
        if comfyui_config.get("comfyui_url"):
            kit_config["comfyui_url"] = comfyui_config["comfyui_url"]
        if comfyui_config.get("comfyui_api_key"):
            kit_config["api_key"] = comfyui_config["comfyui_api_key"]
        if comfyui_config.get("runninghub_api_key"):
            kit_config["runninghub_api_key"] = comfyui_config["runninghub_api_key"]
        # Only pass instance_type if it has a non-empty value
        instance_type = comfyui_config.get("runninghub_instance_type")
        if instance_type and instance_type.strip():
            kit_config["runninghub_instance_type"] = instance_type
        
        return kit_config
    
    def _compute_comfykit_config_hash(self, config: dict) -> str:
        """
        Compute hash of ComfyKit configuration for change detection
        
        Args:
            config: ComfyKit configuration dict
        
        Returns:
            MD5 hash of config
        """
        # Sort keys for consistent hash
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()
    
    async def _get_or_create_comfykit(self) -> ComfyKit:
        """
        Get or create ComfyKit instance (lazy initialization with config change detection)
        
        This method:
        1. Creates ComfyKit on first use (lazy initialization)
        2. Detects configuration changes and recreates instance if needed
        3. Ensures proper cleanup of old instances
        
        Returns:
            ComfyKit instance
        """
        current_config = self._get_comfykit_config()
        current_hash = self._compute_comfykit_config_hash(current_config)
        
        # Check if we need to create or recreate ComfyKit
        if self._comfykit is None or self._comfykit_config_hash != current_hash:
            # Close old instance if exists
            if self._comfykit is not None:
                logger.info("🔄 ComfyUI configuration changed, recreating ComfyKit instance...")
                try:
                    await self._comfykit.close()
                except Exception as e:
                    logger.warning(f"Failed to close old ComfyKit instance: {e}")
                self._comfykit = None
            
            # Create new instance with current config
            logger.info("✨ Creating ComfyKit instance...")
            logger.debug(f"ComfyKit config: {current_config}")
            self._comfykit = ComfyKit(**current_config)
            self._comfykit_config_hash = current_hash
            logger.info("✅ ComfyKit instance created")
        
        return self._comfykit
    
    async def initialize(self):
        """
        Initialize core capabilities
        
        This initializes all services and must be called before using any capabilities.
        Note: ComfyKit is NOT initialized here - it's lazily initialized on first use.
        
        Example:
            await pixelle_video.initialize()
        """
        if self._initialized:
            logger.warning("Pixelle-Video already initialized")
            return
        
        logger.info("🚀 Initializing Pixelle-Video...")
        
        # 1. Initialize core services (ComfyKit will be lazy-loaded later)
        # Initialize services
        self.llm = LLMService(self.config)
        self.tts = TTSService(self.config, core=self)
        self.media = MediaService(self.config, core=self)
        self.image = self.media  # Alias for backward compatibility
        self.image_analysis = ImageAnalysisService(self.config, core=self)
        self.video_analysis = VideoAnalysisService(self.config, core=self)
        self.video = VideoService()
        self.frame_processor = FrameProcessor(self)
        self.persistence = PersistenceService(output_dir="output")
        self.history = HistoryManager(self.persistence)
        
        # 2. Register video generation pipelines
        self.pipelines = {
            "standard": StandardPipeline(self),
            "custom": CustomPipeline(self),
            "asset_based": AssetBasedPipeline(self),
        }
        logger.info(f"📹 Registered pipelines: {', '.join(self.pipelines.keys())}")

        # 3. Register publishers (opt-in via config)
        self._init_publishers()

        # 4. Set default pipeline callable (for backward compatibility)
        self.generate_video = self._create_generate_video_wrapper()

        self._initialized = True
        logger.info("✅ Pixelle-Video initialized successfully\n")

    def _init_publishers(self):
        """Instantiate publishers whose `enabled` flag is true in config."""
        publishers_config = config_manager.config.publishers
        self._publishers = {}
        if publishers_config.youtube.enabled:
            from pixelle_video.publishers.youtube import YouTubePublisher

            self._publishers["youtube"] = YouTubePublisher(publishers_config.youtube)
            logger.info("📺 YouTube publisher enabled")
        if self._publishers:
            logger.info(f"📤 Registered publishers: {', '.join(self._publishers.keys())}")
        else:
            logger.debug("No publishers enabled in config")
    
    async def cleanup(self):
        """
        Cleanup resources (close ComfyKit session)
        
        Example:
            await pixelle_video.cleanup()
        """
        if self._comfykit:
            logger.info("🧹 Closing ComfyKit session...")
            try:
                await self._comfykit.close()
                logger.info("✅ ComfyKit session closed")
            except Exception as e:
                logger.error(f"Failed to close ComfyKit: {e}")
            finally:
                self._comfykit = None
                self._comfykit_config_hash = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.cleanup()
    
    def _create_generate_video_wrapper(self):
        """
        Create a wrapper function for generate_video that supports pipeline selection
        
        This maintains backward compatibility while adding pipeline support.
        """
        async def generate_video_wrapper(
            text: str,
            pipeline: str = "standard",
            **kwargs
        ):
            """
            Generate video using specified pipeline
            
            Args:
                text: Input text
                pipeline: Pipeline name ("standard", "book_summary", etc.)
                **kwargs: Pipeline-specific parameters
            
            Returns:
                VideoGenerationResult
            
            Examples:
                # Use standard pipeline (default)
                result = await pixelle_video.generate_video(
                    text="如何提高学习效率",
                    n_scenes=5
                )
                
                # Use custom pipeline
                result = await pixelle_video.generate_video(
                    text=your_content,
                    pipeline="custom",
                    custom_param_example="custom_value"
                )
            """
            if pipeline not in self.pipelines:
                available = ", ".join(self.pipelines.keys())
                raise ValueError(
                    f"Unknown pipeline: '{pipeline}'. "
                    f"Available pipelines: {available}"
                )
            
            pipeline_instance = self.pipelines[pipeline]
            return await pipeline_instance(text=text, **kwargs)
        
        return generate_video_wrapper
    
    async def publish(
        self,
        task_id: str,
        platform: str = "youtube",
        *,
        force: bool = False,
        title_override: Optional[str] = None,
        description_override: Optional[str] = None,
        tags_override: Optional[list[str]] = None,
        privacy_status: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[PublishResult, bool]:
        """
        Publish a previously generated video to one platform.

        Returns:
            (result, cached) — cached=True means an existing publish was found
            in metadata and no upload was performed.
        """
        if not self._initialized:
            raise RuntimeError(
                "PixelleVideoCore not initialized. Call await core.initialize() first."
            )

        publisher = self._publishers.get(platform)
        if publisher is None:
            raise ValueError(
                f"Publisher '{platform}' is not enabled. Set "
                f"config.publishers.{platform}.enabled=true and configure credentials."
            )

        metadata = await self.persistence.load_task_metadata(task_id)
        if not metadata:
            raise FileNotFoundError(f"Task metadata not found for task_id={task_id}")

        existing = (metadata.get("published_to") or {}).get(platform)
        if existing and not force:
            logger.info(f"⏭️ Task {task_id} already published to {platform}; returning cached")
            return PublishResult(**existing), True

        video_path = (metadata.get("result") or {}).get("video_path")
        if not video_path:
            raise ValueError(f"Task {task_id} has no result.video_path; cannot publish")

        storyboard = None
        title = title_override or (metadata.get("input") or {}).get("title")
        if not title:
            storyboard = await self.persistence.load_storyboard(task_id)
            if storyboard:
                title = storyboard.title
        if not title:
            raise ValueError(
                f"Task {task_id} has no title; pass title_override on the publish request."
            )

        if description_override is not None and tags_override is not None:
            description = description_override
            tags = list(tags_override)
        else:
            if storyboard is None:
                storyboard = await self.persistence.load_storyboard(task_id)
            narrations = [f.narration for f in storyboard.frames] if storyboard else []
            gen_description, gen_tags = await self._generate_publish_metadata(
                platform=platform, title=title, narrations=narrations
            )
            description = description_override if description_override is not None else gen_description
            tags = list(tags_override) if tags_override is not None else gen_tags

        upload_opts: dict[str, Any] = {}
        if privacy_status is not None:
            upload_opts["privacy_status"] = privacy_status

        result = await publisher.upload(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            progress_callback=progress_callback,
            **upload_opts,
        )

        published_to = metadata.get("published_to") or {}
        published_to[platform] = result.model_dump(mode="json")
        metadata["published_to"] = published_to
        await self.persistence.save_task_metadata(task_id, metadata)

        return result, False

    async def _generate_publish_metadata(
        self,
        platform: str,
        title: str,
        narrations: list[str],
    ) -> tuple[str, list[str]]:
        """Ask the LLM for a platform description + tags. YouTube only for now."""
        if platform != "youtube":
            return "", []

        from pixelle_video.prompts import build_description_generation_prompt

        yt_config = config_manager.config.publishers.youtube
        prompt = build_description_generation_prompt(
            title=title,
            narrations=narrations,
            max_tags=yt_config.max_tags,
            extra_instructions=yt_config.description_prompt_extra,
        )
        response = await self.llm(prompt, temperature=0.7, max_tokens=1500)

        parsed = _parse_publish_metadata_json(response)
        description = str(parsed.get("description", "")).strip()
        raw_tags = parsed.get("tags") or []
        tags: list[str] = []
        if isinstance(raw_tags, list):
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        return description, tags

    @property
    def project_name(self) -> str:
        """Get project name from config"""
        return self.config.get("project_name", "Pixelle-Video")
    
    def __repr__(self) -> str:
        """String representation"""
        status = "initialized" if self._initialized else "not initialized"
        pipelines = f"pipelines={list(self.pipelines.keys())}" if self._initialized else ""
        return f"<PixelleVideoCore project={self.project_name!r} status={status} {pipelines}>"


def _parse_publish_metadata_json(text: str) -> dict:
    """Extract the publish-metadata JSON object from an LLM response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    obj = re.search(r"\{[\s\S]*\}", text)
    if obj:
        try:
            return json.loads(obj.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError("No publish metadata JSON found in LLM response", text, 0)


# Global instance
pixelle_video = PixelleVideoCore()
