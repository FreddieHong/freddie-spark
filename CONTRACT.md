# Freddie Lingua implementation contract

Approved UI: immersive workbench from the design at `/Users/freddie/.codex/visualizations/2026/11/19/01a1f1d0-ef82-7b23-93de-194e8b23c311/freddie-lingua-design.html`.

Build a real macOS desktop app: native AppKit/WKWebView shell, a loopback-only Python service, plain HTML/CSS/JS frontend. The native app starts the service and loads its ephemeral loopback port. Python and models run locally. Cloud receives transcript text only. No fake processing/results. Python should use standard library server/storage and lazy imports for MLX model packages.

## Shared API

All JSON endpoints return JSON. Errors use HTTP >=400 with `{error: "Chinese human-readable message"}`. Serve UI at `/`. Bind only 127.0.0.1. A launch token is passed via `/?token=...` and becomes a HttpOnly SameSite=Strict session cookie. Reject unauthorized API/media requests and untrusted origins for writes. GET /api/health may be unauthenticated and contains no personal data.

- GET /api/health -> `{ok:true, version:"0.1.0"}`
- GET /api/settings -> `{mode:"auto"|"cloud"|"local", recognition_language:"auto", cloud:{base_url,model,has_api_key},credential_persistent:boolean}`
- PUT /api/settings accepts same structure and optional `cloud.api_key`; empty or absent key preserves the existing key, `cloud.clear_api_key:true` explicitly deletes it. Never return the key. Use macOS Keychain where possible, session-only fallback with visible warning when unavailable.
- GET /api/models -> `{models:[{id:"asr"|"llm",name,description,size_label,installed:boolean,downloading:boolean,progress:number,error:string|null}]}`
- POST /api/models/{asr|llm}/download -> 202; starts explicit background download, no automatic initial downloads.
- GET /api/projects -> `{projects:[project without full segments]}`
- POST /api/import-path -> `{paths:[absolute path]}` (native shell only via API); response `{project}`. Validate real readable local video and allow common video/audio extensions. Import only first file, explain single-task queue in frontend.
- POST /api/import -> raw file body, URL-encoded `X-Filename` header; copies into app data. response `{project}`. Used for browser fallback.
- GET /api/projects/{id} -> `{project}`
- POST /api/projects/{id}/process -> 202 `{project}`. Start or retry processing, guard concurrent jobs.
- POST /api/projects/{id}/cancel -> 200; cooperatively cancel.
- GET /api/projects/{id}/media -> source video, support single byte Range with 206/416 and no loading whole file into RAM.
- GET /api/projects/{id}/export?format=md|txt|srt&content=summary|bilingual|chinese|original -> downloadable actual content, reject incompatible summary/SRT.

Project fields:
`{id,title,file_name,duration,detected_language,status,progress,error,segments,chapters,overview,mode_used,created_at,warnings}`.
Statuses: `imported,queued,extracting,transcribing,translating,summarizing,completed,partial,error,cancelled`.
Segment: `{id,start,end,text,translation}` seconds numeric. Chapter: `{id,start,end,title,summary,bullets:[]}`. `mode_used` is `cloud`, `local`, or empty; warnings are strings. Persist data in SQLite/JSON in data_dir; project original file remains at its path. Never delete source media. Keep processed results on failures/cancel.

## Engine interface: backend/engines.py

`class EngineService(data_dir: pathlib.Path)` owns model locations and lazy model caches.

- `models_status() -> list[dict]` containing model fields above.
- `download_model(kind: str, progress: Callable[[float,str],None]) -> None` synchronous; server runs it in background and merges progress/error flags. Use Hugging Face snapshot_download to explicit local directories. Never download during inference. Only load an installed model using local paths/offline mode.
- `transcribe(audio_path: Path, language: str, progress: Callable[[float,str],None], cancelled: Callable[[],bool]) -> tuple[str,list[dict]]`. ASR MLX whisper multilingual base; output segment keys id/start/end/text/translation. Whitespace trimming, skip empty segments, bounded times.
- `translate(segments: list[dict], settings: dict, api_key: str, progress: Callable[[float,str],None], cancelled: Callable[[],bool], on_segments: Callable[[list[dict]],None]) -> tuple[list[dict],str,list[str]]`. Mode auto: cloud if configured, cloud failure falls back local if installed. Local mode never makes remote calls. Cloud mode explicit failure remains a clear error if not possible; automatic fallback controlled by mode. On partial completion retain translated segments through callback. All cloud calls use OpenAI-compatible chat/completions with urllib and validated endpoint, bounded timeouts. Batch context with ID-preserving JSON; validate IDs and never silently lose source sentences.
- `summarize(segments: list[dict], settings: dict, api_key: str, progress: Callable[[float,str],None], cancelled: Callable[[],bool]) -> tuple[str,list[dict],str,list[str]]`. Chinese overview + semantic chapters with valid start/end from original segments. Do not fabricate unsupported facts. Local LLM uses MLX Qwen2.5-1.5B-Instruct 4bit. Chunk long inputs hierarchically with bounded contexts, avoid huge prompts. Summaries reference original times. Errors clear and Chinese.

Engine raises `RuntimeError` with Chinese message; cancellation raises `InterruptedError`. Settings cloud shape above; no credentials in project metadata, warnings, logs or exceptions.

## Native bridge

Frontend detects `window.webkit?.messageHandlers?.freddie`. Send messages `{action:"chooseVideo"}`, `{action:"export",url:"/api/..."}`, `{action:"openDataFolder"}`, `{action:"openExternal",url:"https://..."}`. Native import/drop dispatches `window.dispatchEvent(new CustomEvent("freddie:import",{detail:{paths:[...]}}))`. Native errors dispatch `freddie:error` detail `{message}`. Native shell mediates saving exports. Browser fallback uses a file input + raw local upload and regular download anchor. Never send local media to external cloud.

## UI

Use approved dark graphite/cyan design, Chinese controls, default two columns. Start empty with a prominent drop area, brief local/cloud explanation, and model readiness. Show real HTML video on import, original/bilingual/Chinese tabs, time clickable transcript, current sentence highlight, original+translation editable if feasible later (do not promise unfinished features). Right Chinese overview and semantic chapter summaries. Explicit stages/progress/error/retry/cancel. Settings: auto/cloud/local, service endpoint/model/key, offline pack downloads, manual language override. Library opens prior projects. Export available only when actual data exists. Preserve language tab and reading position across polls. Escape dialogs, keyboard tabs, reduced motion, responsive down to 320px.

## Development ownership

- Frontend agent: `frontend/` only.
- Server agent: `backend/server.py`, `backend/storage.py`, `backend/exports.py`, `backend/__init__.py`, and related tests.
- Engine agent: `backend/engines.py`, `requirements.txt`, and related tests.
- Root: `native/`, `scripts/`, README, build/runtime packaging, integration and fixes after coordination.

Default dev data location is workspace `.freddie-data` via `FREDDIE_DATA_DIR`, production app uses Application Support/Freddie Lingua. Model downloads are user initiated and can be ~150 MB ASR and ~1 GB local language model. Models are excluded from .app. Never claim that local model is ready before verified installed.
