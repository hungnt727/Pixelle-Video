# Pixelle-Video

The AI video-generation engine: turns a topic (or user-supplied script/assets) into a finished short-form video, and optionally publishes it to one or more social platforms.

## Language

**Generation**:
The pipeline-driven act of producing a finished video file plus its `Storyboard` from input (topic, script, or assets). Ends when `VideoGenerationResult` is returned.
_Avoid_: Render, build, compile.

**Publishing**:
The act of uploading a generated video to an external platform (e.g. YouTube) and recording the resulting URL/ID. Distinct from and downstream of **Generation**.
_Avoid_: Upload (too generic — upload is one step of publishing), post.

**Publisher**:
A platform-specific component that takes a completed **Generation** and performs **Publishing** to one platform. Implements the `BasePublisher` interface so platforms are swappable.
_Avoid_: Uploader, poster, social-poster.

**PublishResult**:
The record returned by a **Publisher** after a successful upload — at minimum: platform name, remote video id, public URL, timestamp.
_Avoid_: UploadResult, PostResult.

**Storyboard.title** vs **YouTube title**:
`Storyboard.title` is the in-video / metadata title produced during **Generation** (LLM or user-supplied). The **YouTube title** is the title shown on the YouTube watch page; by default it reuses `Storyboard.title` but a **Publisher** may transform it (e.g. add emoji, truncate to 100 chars).
_Avoid_: Treating these as the same field — they live in different layers.

**auto_publish flag**:
Per-request opt-in. When `true`, the API router triggers **Publishing** automatically after **Generation** completes. Default `false` so test/dev runs don't burn YouTube quota.

## Relationships

- A **Generation** produces zero or more **Publishings** (one per target platform).
- A **Publishing** belongs to exactly one **Publisher**.
- A **Publisher** is invoked by `PixelleVideoCore`, never directly by a pipeline.

## Flagged ambiguities

- "title" was overloaded between in-video metadata and YouTube watch-page title — resolved: `Storyboard.title` (generation concern) vs platform-rendered title (publisher concern).
- "auto upload" in early discussion was ambiguous between "always-on" and "opt-in" — resolved: opt-in via `auto_publish` flag, default off.
