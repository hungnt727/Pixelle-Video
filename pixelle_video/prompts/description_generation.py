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
Description + tags generation prompt — used by the publisher layer at publish
time (NOT during the generation pipeline) so unpublished runs don't pay the
LLM cost.
"""


DESCRIPTION_GENERATION_PROMPT = """You are writing the YouTube description and tags for a short-form video.

Title (already chosen):
{title}

Narrations (each line is one scene of the video, in order):
{narrations}

{extra}

Return a SINGLE JSON object with this exact shape:
{{
  "description": "<string, max 4500 chars, plain text, no markdown>",
  "tags": ["<tag 1>", "<tag 2>", ...]
}}

Rules:
1. **Language**: Match the language of the narrations. Do not translate.
2. **Description structure**:
   - First paragraph (1-2 sentences): hook that captures the core message.
   - Optional second paragraph: a few extra lines of detail.
   - Final line: 2-5 hashtags (start with `#`, space-separated).
3. **No fake URLs, emails, phone numbers, prices, or promises** the original
   narration did not mention.
4. **Tags**:
   - {tag_count_hint}.
   - Each tag is 1-3 words, lowercase except proper nouns, no `#`.
   - Avoid generic noise tags like "video", "youtube", "viral".
5. **Output the JSON only** — no markdown fence, no explanation.
"""


def build_description_generation_prompt(
    title: str,
    narrations: list[str],
    max_tags: int = 5,
    extra_instructions: str = "",
) -> str:
    """
    Build the LLM prompt for YouTube description + tags.

    Args:
        title: Final title chosen for the video.
        narrations: Ordered list of per-scene narration strings.
        max_tags: How many tags the LLM should aim to produce (0 disables).
        extra_instructions: Channel-specific extras appended verbatim.

    Returns:
        Fully formatted prompt string.
    """
    narrations_block = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(narrations))

    if max_tags <= 0:
        tag_hint = 'Return an empty array `"tags": []`'
    else:
        tag_hint = f"Produce between 3 and {max_tags} tags"

    extra = f"Extra channel guidance:\n{extra_instructions}\n" if extra_instructions.strip() else ""

    return DESCRIPTION_GENERATION_PROMPT.format(
        title=title,
        narrations=narrations_block,
        extra=extra,
        tag_count_hint=tag_hint,
    )
