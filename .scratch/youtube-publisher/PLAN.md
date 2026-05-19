# Plan — YouTube Publisher for Pixelle-Video

Status: ready-for-human (chờ approve trước khi implement)
Owner: hungnt3@vnvc.vn
Created: 2026-05-20

## Context

Pixelle-Video hiện chỉ generate ra file MP4 trong `output/`. Việc đẩy lên các nền tảng social vẫn phải làm thủ công. Workspace CLAUDE.md đã quy định contract cho khâu này (interface `Publisher`, idempotent, ghi URL/ID vào history) nhưng chưa có implementation nào. Mục tiêu của thay đổi này: thêm `YouTubePublisher` đầu tiên + scaffolding `BasePublisher` để các platform sau (Facebook, TikTok) cắm vào sau này không phải refactor.

Outcome:
- Người dùng cấu hình OAuth YouTube một lần (CLI), sau đó mọi generation có thể opt-in `auto_publish=true` để tự upload và trả về URL.
- Khâu publish là một bước **tách biệt khỏi pipeline**, có thể retry độc lập, idempotent, được theo dõi qua `TaskManager` y như generation.

## Decisions locked in (từ grilling)

| # | Quyết định | Hệ quả |
|---|---|---|
| 1 | Opt-in qua flag `auto_publish` (default `false`) | Tránh cháy YouTube quota khi test; pipeline không biết publish tồn tại |
| 2 | `PixelleVideoCore.publish(task_id, platform, **opts)` là entry point duy nhất | API router + Streamlit cùng gọi vào facade, không duplicate logic |
| 3 | Publish chạy như TaskManager task riêng (`TaskType.PUBLISH`), chained sau GENERATION | `/generate/sync` trả response khi MP4 sẵn sàng; client poll task PUBLISH riêng nếu cần |
| 4 | Standalone CLI cho OAuth first-time setup: `uv run python -m pixelle_video.publishers.youtube.auth` | Refresh token lưu vào `data/credentials/youtube_token.json`, deploy headless sau đó dùng OK |
| 5 | Title reuse `Storyboard.title`; description LLM sinh **tại thời điểm publish**; cả hai có thể override qua request body | `StandardPipeline` KHÔNG đổi (surgical) |

## Architecture

```
API router /api/video/generate/*  ──┐
                                    ├─► TaskManager(GENERATION) ──► pipeline.standard ──► VideoGenerationResult
                                    │                                          │
                                    │   if auto_publish=true ◄─────────────────┘
                                    │
                                    ▼
                           core.publish(task_id, ...) 
                                    │
                                    ▼
                      TaskManager(PUBLISH) ──► YouTubePublisher.upload()
                                                       │
                                                       ▼
                                    persistence.save_task_metadata(
                                       task_id, {..., "published_to": {"youtube": {...}}}
                                    )
```

Key invariants:
- Pipeline layer (`pixelle_video/pipelines/`) **không** import publishers.
- Publisher layer (`pixelle_video/publishers/`) **không** import pipelines (chỉ đọc storyboard qua persistence).
- Idempotency check sống ở `core.publish` — đọc `metadata.json`, nếu `published_to.youtube` đã tồn tại và `force=False`, trả về cached `PublishResult` không gọi API.

## Files to create

| File | Trách nhiệm |
|---|---|
| `pixelle_video/publishers/__init__.py` | Re-export `BasePublisher`, `PublishResult` |
| `pixelle_video/publishers/base.py` | `BasePublisher` ABC; `PublishResult` Pydantic v2 model (fields: `platform`, `remote_id`, `url`, `uploaded_at`, `metadata`) |
| `pixelle_video/publishers/youtube/__init__.py` | Re-export `YouTubePublisher` |
| `pixelle_video/publishers/youtube/publisher.py` | `YouTubePublisher(BasePublisher)`: load credentials → resumable upload qua `asyncio.to_thread` → trả `PublishResult` |
| `pixelle_video/publishers/youtube/auth.py` | CLI: `python -m pixelle_video.publishers.youtube.auth`. Dùng `google_auth_oauthlib.flow.InstalledAppFlow.run_local_server(port=0)` với scope `https://www.googleapis.com/auth/youtube.upload`. Lưu credentials JSON vào `token_file` path từ config |
| `pixelle_video/prompts/description_generation.py` | Prompt template cho LLM sinh description + tags (5 tags max, kèm `#shorts` nếu tỷ lệ portrait) |
| `api/schemas/publish.py` | `PublishRequest` (optional `title_override`, `description_override`, `tags_override`, `privacy_status`, `force`), `PublishResponse` (gồm `publish_task_id`, `cached: bool`) |
| `api/routers/publish.py` | `POST /api/publish/{task_id}` — gọi `core.publish(...)` qua TaskManager, trả `publish_task_id` |
| `tests/test_youtube_publisher.py` | Unit tests với `googleapiclient` mock |
| `tests/test_publish_idempotency.py` | Test gọi publish 2 lần → lần 2 return cached, không tăng API call count |

## Files to modify

| File | Sửa gì |
|---|---|
| `pixelle_video/config/schema.py` | Thêm `YouTubeConfig` + `PublishersConfig` (chỉ chứa `youtube` cho v1). Mount vào `PixelleVideoConfig.publishers`. Fields: `enabled`, `client_secrets_file`, `token_file`, `default_privacy_status` (`private`/`unlisted`/`public`, default `private`), `default_category_id` (default `"22"`), `default_made_for_kids` (default `false`), `default_language` (Optional, default `None`), `max_tags` (default `5`), `description_prompt_extra` (default `""`) |
| `config.example.yaml` | Thêm section `publishers.youtube` với comments giải thích từng field + link tới Google Cloud Console docs |
| `api/tasks/models.py` | Thêm `TaskType.PUBLISH = "publish"` |
| `pixelle_video/service.py` | Thêm method `async def publish(self, task_id: str, platform: str = "youtube", force: bool = False, **overrides) -> PublishResult`. Bước: (a) load `metadata.json` qua `persistence.load_task_metadata`; (b) idempotency check trên `published_to.{platform}`; (c) resolve publisher từ một dict `self._publishers = {"youtube": YouTubePublisher(self.config)}` được khởi tạo trong `initialize()` (lazy, chỉ tạo nếu `config.publishers.youtube.enabled`); (d) gọi `publisher.upload(metadata, **overrides)`; (e) merge result vào metadata.json và save |
| `api/app.py` | Register `publish_router` từ `api/routers/publish.py` |
| `api/schemas/video.py` | Thêm `auto_publish: bool = False` + `publish: Optional[PublishRequest] = None` vào `VideoGenerateRequest` |
| `api/routers/video.py` | Nếu `request.auto_publish`: sau khi generation task `COMPLETED`, **tự gọi** logic giống `POST /api/publish/{task_id}` (qua một helper `_enqueue_publish_task(task_id, opts)`) và trả thêm `publish_task_id` trong response. Generation response **không đợi** publish. Helper được dùng chung với router publish |
| `pyproject.toml` | Thêm deps: `google-auth>=2.30`, `google-auth-oauthlib>=1.2`, `google-api-python-client>=2.140` |
| `.gitignore` | Append: `secrets/`, `data/credentials/` (nếu chưa có dòng `data/` thì thêm 2 dòng này; nếu đã có `data/` thì thêm `secrets/`) |
| `CLAUDE.md` (Pixelle-Video) | Thêm dòng `pixelle_video/publishers/` vào repository map; thêm hàng "Add a new publisher" trong bảng Common tasks |

## Reusable functions / patterns đã có (KHÔNG tái invent)

- `PersistenceService.load_task_metadata(task_id) / save_task_metadata(task_id, dict)` — `pixelle_video/services/persistence.py`. Đã hỗ trợ overwrite full → thêm key top-level `published_to` an toàn.
- `TaskManager.create_task / execute_task / update_progress / get_task` — `api/tasks/manager.py`. Dùng nguyên bản cho task PUBLISH; chỉ thêm enum value mới.
- `LLMService` qua `core.llm` — pattern hiện có cho việc gọi LLM với prompt template (xem `pixelle_video/utils/content_generators.py:generate_title` để bắt chước cho description).
- Loguru: `from loguru import logger`, dùng `logger.info/.debug/.error` (style hiện tại trong `services/`).
- Async wrapper cho sync client: dùng `asyncio.to_thread(sync_call, *args)` — chưa có ví dụ trong codebase nhưng đây là pattern Python chuẩn; thêm trong `YouTubePublisher.upload`.

## Idempotency contract

`metadata.json` mở rộng (chỉ thêm key, không động vào các key sẵn có):
```json
{
  "task_id": "...",
  "status": "completed",
  "input": {...},
  "result": {...},
  "config": {...},
  "published_to": {
    "youtube": {
      "video_id": "dQw4w9WgXcQ",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "uploaded_at": "2026-05-20T10:30:00Z",
      "title": "...",
      "privacy_status": "private"
    }
  }
}
```
- `core.publish(task_id, platform="youtube", force=False)` → nếu `published_to.youtube` tồn tại trả về cached `PublishResult` (no API call). `force=True` → re-upload (tạo video mới trên YouTube, ghi đè `published_to.youtube` với entry mới — không xoá video cũ trên YouTube để tránh hỏng link đã share).

## Out of scope (v1)

- Multi-channel YouTube (1 channel duy nhất xác định bởi refresh_token).
- Scheduled publish (`publishAt`).
- Custom thumbnail upload (YouTube tự pick).
- Hậu kiểm việc YouTube xử lý xong video (kiểm tra `processingDetails`).
- Các platform khác (Facebook/TikTok) — chỉ scaffold `BasePublisher` cho dễ thêm sau.
- Streamlit UI cho publish — endpoint API là đủ cho v1; Streamlit page sẽ là phase 2.

## Verification

1. **Static checks**:
   - `uv run ruff check . && uv run ruff format --check .`
   - `uv run python -c "from pixelle_video.publishers.youtube import YouTubePublisher; print(YouTubePublisher)"`

2. **Unit tests** (`uv run pytest tests/test_youtube_publisher.py tests/test_publish_idempotency.py`):
   - Mock `googleapiclient.discovery.build`. Assert `videos().insert(...)` được gọi với đúng `snippet.title`, `snippet.description`, `snippet.tags`, `status.privacyStatus`, `status.madeForKids`, và `media_body` là `MediaFileUpload(resumable=True)`.
   - Idempotency: gọi `core.publish` 2 lần liên tiếp → lần 2 `mock_youtube_build.call_count == 1` (không tạo lại client).

3. **End-to-end smoke** (trên máy có browser, channel test):
   - Chạy CLI: `uv run python -m pixelle_video.publishers.youtube.auth` → browser mở, authorize, token file được tạo.
   - Generate một video ngắn: `curl -X POST http://localhost:8000/api/video/generate/sync -d '{"text":"test", "auto_publish": true, "publish": {"privacy_status": "private"}}'`.
   - Verify: response chứa `publish_task_id`; poll `GET /api/tasks/{publish_task_id}` thấy `status=completed`, `result.url` là link YouTube hợp lệ; `output/{task_id}/metadata.json` có khoá `published_to.youtube`.
   - Lặp lại `POST /api/publish/{task_id}` không `force` → response `cached: true`, không tạo video YouTube mới.

4. **Manual**: vào YouTube Studio kiểm tra video upload đúng title/description/privacy.

## Risk notes (không action ngay, chỉ ghi nhận)

- **YouTube quota**: 1 upload = 1600 units, daily default = 10000 → ~6 upload/ngày. Cần document trong CLAUDE.md để user không bất ngờ.
- **Token expiry**: refresh token có thể bị Google revoke sau 6 tháng inactive. Lúc đó `auto_publish` fail; log error rõ ràng + hướng dẫn chạy lại CLI auth.
- **Resumable upload chunk size**: mặc định 1MB → progress smooth nhưng nhiều HTTP request. Để default, không sa đà tuning ở v1.

## Cross-references

- Workspace conventions for publishers: `../../CLAUDE.md` → section "Social publishing".
- Domain glossary: `../../CONTEXT.md` (Pixelle-Video context).
- Plan đã ghi song song tại: `~/.claude/plans/dreamy-jingling-riddle.md` (plan-mode artifact).
