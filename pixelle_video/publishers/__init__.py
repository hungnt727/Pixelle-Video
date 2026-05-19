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
Publishers package — per-platform upload integrations.

Each platform is implemented as a `BasePublisher` subclass. PixelleVideoCore
resolves and invokes them; pipelines never import publishers.
"""

from pixelle_video.publishers.base import BasePublisher, PublishResult

__all__ = ["BasePublisher", "PublishResult"]
