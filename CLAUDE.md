# Pixelle-Video — Development Guide for Claude

> Parent workspace conventions: `../CLAUDE.md`. Read that first for cross-project rules; this file only documents what's specific to Pixelle-Video.

## What this project is

Pixelle-Video is an **AI short-video generation engine**. Input: a topic string. Output: a finished social-ready video.

Pipeline: **topic → LLM script → per-line image/video prompts → AI image or video generation (ComfyUI / RunningHub) → TTS narration (Edge-TTS / ComfyUI TTS) → frame composition (HTML templates rendered with Playwright) → final video (MoviePy + FFmpeg) + BGM.**

Three layers stacked together:
- **Streamlit web UI** (`web/`) — what end-users interact with.
- **FastAPI backend** (`api/`) — REST API for programmatic use, exposed at `/docs`.
- **Core library** (`pixelle_video/`) — services, pipelines, models. The brains.

## Tech stack (what's actually in use)

- **Python 3.11+**, `uv` package manager (see `pyproject.toml`).
- **FastAPI 0.115+** + **Uvicorn 0.32+** (backend) — entry `api/app.py`.
- **Streamlit 1.40+** (frontend) — entry `web/app.py`.
- **Pydantic v2** for all DTOs and config schema.
- **Loguru** for logging — use this, not `print` or `logging`.
- **comfykit 0.1.12** — client for ComfyUI workflows (image/video/TTS generation).
- **openai 2.6+** SDK — used for OpenAI, Qwen, DeepSeek, Ollama (all OpenAI-compatible).
- **edge-tts 7.2.7** (version pinned for stability — don't bump without testing TTS).
- **moviepy 1.0.3** + **ffmpeg-python** — video composition.
- **Playwright** — renders HTML templates to PNG frames. Needs `playwright install` after `uv sync`.
- **pytest + pytest-asyncio** — tests (currently sparse; new tests welcome).
- **Ruff** — lint + format, line-length 100, target py311 (configured in `pyproject.toml`).

## Dev commands

Run from project root. All commands use `uv`.

```bash
# Install / sync dependencies
uv sync

# After uv sync (first time only), install Playwright browsers
uv run playwright install chromium

# Run the FastAPI backend (http://localhost:8000, docs at /docs)
uv run python api/app.py
# Optional flags: --host 0.0.0.0 --port 8000 --reload

# Run the Streamlit web UI (http://localhost:8501)
uv run streamlit run web/app.py

# Run everything via Docker (init → api on 8000 + web on 8501)
docker-compose up -d

# Lint & format
uv run ruff check .
uv run ruff format .

# Tests
uv run pytest
```

First-time config: copy `config.example.yaml` → `config.yaml` and fill in API keys (LLM provider, ComfyUI URL or RunningHub key). `docker-compose up` does this automatically via the `init` service.

## Repository map

```
api/                       FastAPI backend (thin — delegates to pixelle_video/)
  app.py                   App factory, lifespan, CORS, router registration
  config.py                API-specific config
  dependencies.py          FastAPI DI (PixelleVideoDep injects the core service)
  routers/                 Endpoints — one router per domain
    health.py              GET /health
    llm.py                 LLM inference
    tts.py                 Text-to-speech
    image.py               AI image generation
    video.py               POST /api/video/generate/sync | /async
    content.py             Script & title generation
    frame.py               Single-frame composition
    tasks.py               GET /api/tasks/{id} — async task status
    files.py               GET /api/files/{path} — serve generated output
    resources.py           List available templates / workflows / BGM
  schemas/                 Pydantic request/response models (one file per router)
  tasks/
    manager.py             TaskManager (in-memory, auto-cleanup)
    models.py              Task, TaskStatus, TaskType, TaskProgress

pixelle_video/             Core library (where business logic lives)
  service.py               PixelleVideoCore — main facade orchestrating everything
  config/
    schema.py              Pydantic config models (LLMConfig, ComfyUIConfig, ...)
    manager.py             ConfigManager singleton (load / reload / save)
    loader.py              YAML I/O
  services/
    llm_service.py         LLM calls + structured output
    tts_service.py         TTS (Edge-TTS local or ComfyUI workflows)
    media.py               Image / video generation dispatch
    comfy_base_service.py  comfykit wrapper base class
    image_analysis.py      Vision-API image understanding
    video_analysis.py      Video understanding (FFmpeg)
    video.py               Video composition (moviepy)
    frame_processor.py     HTML → PNG via Playwright
    persistence.py         Data storage
    history_manager.py     Generation history
  pipelines/               End-to-end workflows (Template Method over BasePipeline)
    base.py                BasePipeline (ABC) — extend this when adding a pipeline
    linear.py              LinearVideoPipeline (shared linear flow)
    standard.py            StandardPipeline (topic → script → images → video)
    custom.py              CustomPipeline (user supplies the script)
    asset_based.py         AssetBasedPipeline (user uploads photos/videos)
  models/
    storyboard.py          Storyboard, StoryboardFrame, VideoGenerationResult
    media.py               Media asset models
    progress.py            ProgressEvent — emitted to API/Web during generation
  prompts/                 LLM prompt templates (one file per prompt type)
  utils/                   llm_util, template_util, workflow_util, tts_util, ...
  tts_voices.py            Voice ID → engine/locale mapping
  llm_presets.py           Provider presets (Qwen, GPT, DeepSeek, Ollama)

web/                       Streamlit frontend (dumb — calls services/pipelines)
  app.py                   st.navigation entry point
  pages/                   1_🎬_Home.py (default), 2_📚_History.py
  components/              Header, settings, content_input, style_config, ...
  pipelines/               Thin web-layer adapters around pixelle_video.pipelines
  state/session.py         Streamlit session state
  utils/                   streamlit_helpers, async_helpers, batch_manager

templates/                 HTML video frame templates, grouped by dimension
  1080x1920/               Portrait (default for shorts/reels)
  1080x1080/               Square
  1920x1080/               Landscape

workflows/                 ComfyUI workflow JSON files
  selfhost/                For local ComfyUI
  runninghub/              For RunningHub cloud

bgm/                       Default background music (default.mp3)
data/                      User overrides — users/, bgm/, templates/, workflows/
output/                    Generated videos (runtime, gitignored)

docs/                      Bilingual docs (zh + en)
  en/development/architecture.md     ← read for high-level design
  en/reference/api-overview.md       ← full API reference
  en/user-guide/workflows.md         ← ComfyUI customization
  en/user-guide/templates.md         ← template authoring

config.example.yaml        Schema reference — copy to config.yaml for real use
pyproject.toml             Deps, ruff config, build config
Dockerfile, docker-compose.yml, docker-start.sh
```

## Coding conventions (project-specific)

The workspace conventions in `../CLAUDE.md` apply. Project-specific additions:

- **Facade pattern.** End-to-end work goes through `PixelleVideoCore` in `pixelle_video/service.py`. API routers and Streamlit pages should call into the core, not reach into `services/` or `pipelines/` directly unless they have a good reason.
- **Pipelines extend `BasePipeline`.** When adding a new generation flow (e.g. "podcast from RSS feed"), subclass `BasePipeline` and implement the abstract steps. Use `LinearVideoPipeline` as the parent if your flow is linear.
- **Progress callbacks.** Long-running pipelines emit `ProgressEvent` (see `pixelle_video/models/progress.py`) via a callback. API uses these to update `TaskManager`; Streamlit uses them to drive the progress bar. Don't print progress — emit events.
- **Async everywhere.** All service methods are `async`. Streamlit needs a sync bridge — use the helpers in `web/utils/async_helpers.py` rather than calling `asyncio.run` ad-hoc.
- **ComfyUI/RunningHub integration.** Don't talk to ComfyUI directly — go through `comfykit` via `services/comfy_base_service.py`. Workflows live in `workflows/`; reference them by name in `config.yaml`.
- **Templates are data.** HTML templates in `templates/<dimension>/<name>.html` are rendered by Playwright per frame. Adding a new visual style = adding a new HTML file with the right `<meta>` dimension tags. No Python code change needed.
- **Schema-first.** Add the Pydantic schema in `api/schemas/` (or `pixelle_video/config/schema.py`) before writing the endpoint or service method.
- **Logging style.** `from loguru import logger`. Use emojis sparingly in startup/shutdown logs (the codebase does this — match the style: `🚀 Starting...`, `🛑 Shutting down...`).

## Common tasks — where to look / what to change

| Task | Files |
|---|---|
| Add a new API endpoint | `api/schemas/<domain>.py` → `api/routers/<domain>.py` → wire in `api/app.py` |
| Add a new pipeline (generation flow) | Subclass `pixelle_video/pipelines/base.py:BasePipeline`, register in `service.py` |
| Add a new LLM provider | `pixelle_video/llm_presets.py` + `pixelle_video/services/llm_service.py` (it's OpenAI-SDK compatible, so usually just preset + base_url) |
| Add a new TTS voice | `pixelle_video/tts_voices.py` (and a ComfyUI workflow under `workflows/` if needed) |
| Add a new visual template | Drop HTML file in `templates/<dimension>/` — must include `<meta name="dimension" content="WxH">` |
| Add a new ComfyUI workflow | JSON under `workflows/selfhost/` or `workflows/runninghub/`, reference by name in `config.yaml` |
| Change config schema | `pixelle_video/config/schema.py` (Pydantic) + update `config.example.yaml` |
| Add a Streamlit page | New file under `web/pages/` named `N_<emoji>_<Name>.py` (number controls order) |

## Gotchas

- **`edge-tts==7.2.7` is pinned** — earlier and later versions have known instability with the public Edge endpoints. Don't bump it casually.
- **`moviepy==1.0.3`** — the 2.x API rewrite breaks the composition code. Stay on 1.x unless you migrate everything.
- **Playwright browsers aren't installed by `uv sync`.** First-time setup needs `uv run playwright install chromium` (or the devcontainer's `postCreate.sh`, which does it for you).
- **THREE.CapsuleGeometry equivalent:** N/A here — but note that some Three.js examples won't work; this project doesn't use Three.js, it uses Playwright HTML rendering.
- **`config.yaml` is gitignored.** Don't commit it. `config.example.yaml` is the schema-shaped example with dummy values.
- **`output/` and `data/` are gitignored.** User-generated content lives there; don't add anything to git from those folders.
- **Two run modes for media generation:** "selfhost" (your own ComfyUI) vs "runninghub" (cloud). Config schema gates which workflows are valid. When debugging "no image generated", check `config.yaml` mode first.
- **Async + Streamlit:** Streamlit is sync. Always use `web/utils/async_helpers.py` to bridge — manual `asyncio.run` will break Streamlit's reactivity.
- **Task manager is in-memory.** Restarting the API loses in-flight task status. For production, swap `TaskManager` for a Redis-backed implementation (not yet done).

## High-signal docs to read

- `docs/en/development/architecture.md` — layered design overview.
- `docs/en/reference/api-overview.md` — endpoint reference.
- `docs/en/reference/config-schema.md` — every config field documented.
- `docs/en/user-guide/workflows.md` — how to author/customize ComfyUI workflows.
- `docs/en/user-guide/templates.md` — how to author HTML video templates.
- `docs/en/tutorials/your-first-video.md` — end-to-end smoke test.

## Key files cheat sheet

- API app & lifespan: `api/app.py`
- Core facade: `pixelle_video/service.py`
- Default pipeline: `pixelle_video/pipelines/standard.py`
- Config schema: `pixelle_video/config/schema.py`
- Task tracking: `api/tasks/manager.py`
- Video request model: `api/schemas/video.py`
