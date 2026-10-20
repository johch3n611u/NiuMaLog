from __future__ import annotations

import os
from datetime import date
from typing import Any, Dict, Optional

from worklog.core.ai import AIService, KeyStore, ProviderError, build_prompt
from worklog.core.domain import ReportInstructions
from worklog.core.importers import ImportService
from worklog.core.service import WorklogService, week_bounds
from worklog.core.storage import Storage


DB_PATH = os.getenv("WORKLOG_DB", ".worklog/worklog.db")
storage = Storage(DB_PATH)
service = WorklogService(storage)
ai = AIService(KeyStore())


def _payload(request: Any) -> Dict[str, Any]:
    return request if isinstance(request, dict) else {}


try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Worklog", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/import")
    def import_sources(body: Dict[str, Any]) -> Dict[str, Any]:
        path = body.get("path")
        if not path:
            raise HTTPException(400, "path is required")
        result = ImportService(storage).import_path(path)
        return {"scanned": result.scanned, "imported": result.imported, "skipped": result.skipped, "errors": result.errors, "conversations": [conversation.to_dict() for conversation in result.conversations]}

    @app.get("/api/conversations")
    def conversations() -> Any:
        return [conversation.to_dict() for conversation in storage.list_conversations()]

    @app.get("/api/messages")
    def messages() -> Any:
        return [message.to_dict() for message in storage.list_all_messages()]

    @app.get("/api/events")
    def events(start: Optional[date] = None, end: Optional[date] = None, project: Optional[str] = None) -> Any:
        # 資料有變才重算；原本只在「一個事件都沒有」時才分析，導致匯入後看不到新資料。
        service.refresh_events_if_stale()
        return [event.to_dict() for event in storage.list_events(start, end, project)]

    @app.patch("/api/events/{event_id}")
    def update_event(event_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if not storage.update_event_project(event_id, str(body.get("project", "未分类"))):
            raise HTTPException(404, "event not found")
        event = next((item for item in storage.list_events() if item.id == event_id), None)
        return event.to_dict() if event else {"status": "updated"}

    @app.delete("/api/events/{event_id}")
    def delete_event(event_id: str) -> Dict[str, bool]:
        if not storage.delete_event(event_id):
            raise HTTPException(404, "event not found")
        return {"deleted": True}

    @app.post("/api/events/merge")
    def merge_events(body: Dict[str, Any]) -> Dict[str, bool]:
        target = body.get("target_id")
        sources = body.get("source_ids", [])
        if not target or not storage.merge_events(target, sources):
            raise HTTPException(400, "target_id must refer to an existing event")
        return {"merged": True}

    @app.post("/api/reports/{kind}")
    def reports(kind: str, body: Dict[str, Any]) -> Dict[str, Any]:
        if kind not in ("daily", "weekly"):
            raise HTTPException(400, "kind must be daily or weekly")
        if kind == "daily":
            start = date.fromisoformat(body.get("date"))
            end = start
        else:
            start, end = week_bounds(body.get("week") or body.get("date"))
        mode = body.get("mode", "deterministic")
        if mode == "ai":
            try:
                provider = ai.provider(body.get("provider", "openai"), body.get("model"), body.get("protocol"), body.get("base_url"))
            except ProviderError as exc:
                raise HTTPException(400, str(exc))
            report = service.generate_ai_draft(kind, start, end, provider, body.get("message_ids"), bool(body.get("include_raw", False)), body.get("project"))
        else:
            report = service.generate(kind, start, end, mode, body.get("project"))
        return report.to_dict()

    @app.get("/api/reports/{kind}/download")
    def download_report(kind: str, date_value: Optional[str] = None, week: Optional[str] = None, format: str = "xlsx") -> Any:
        if kind not in ("daily", "weekly") or format not in ("xlsx", "md", "html"):
            raise HTTPException(400, "kind or format is invalid")
        try:
            if kind == "daily":
                start = date.fromisoformat(date_value or date.today().isoformat())
                end = start
            else:
                start, end = week_bounds(week or date.today().isoformat())
            report = service.generate(kind, start, end)
            if format == "xlsx":
                path = report.metadata.get("xlsx_path")
            else:
                stem = "daily-%s" % start.isoformat() if kind == "daily" else "weekly-%s-W%s" % (start.isocalendar()[0], str(start.isocalendar()[1]).zfill(2))
                path = str(service.export_dir / (stem + "." + format))
            if not path or not os.path.exists(path):
                raise HTTPException(404, "report file not found")
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if format == "xlsx" else ("text/markdown" if format == "md" else "text/html")
            return FileResponse(path, media_type=media_type, filename=os.path.basename(path))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/ai/preview")
    def ai_preview(body: Dict[str, Any]) -> Dict[str, Any]:
        kind = body.get("kind", "daily")
        if kind == "daily":
            start = date.fromisoformat(body["date"])
            end = start
        else:
            start, end = week_bounds(body["week"])
        context = service.context(kind, start, end, body.get("message_ids"), bool(body.get("include_raw", False)))
        instructions = ReportInstructions(redaction_terms=body.get("redaction_terms", []))
        return {"provider": body.get("provider", "openai"), "context": build_prompt(context, instructions), "message_count": len(context.selected_messages)}

    @app.post("/api/ai/generate")
    def ai_generate(body: Dict[str, Any]) -> Dict[str, Any]:
        provider_name = body.get("provider", "openai")
        kind = body.get("kind", "daily")
        try:
            if kind == "daily":
                start = date.fromisoformat(body["date"])
                end = start
            else:
                start, end = week_bounds(body["week"])
            report = service.generate_ai_draft(kind, start, end, ai.provider(provider_name, body.get("model"), body.get("protocol"), body.get("base_url")), body.get("message_ids"), bool(body.get("include_raw", False)))
            return report.to_dict()
        except (ProviderError, KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/settings/key")
    def set_key(body: Dict[str, Any]) -> Dict[str, str]:
        provider = body.get("provider")
        value = body.get("api_key")
        if provider not in ("openai", "anthropic", "ccswitch") or not value:
            raise HTTPException(400, "provider and api_key are required")
        ai.key_store.set(provider, value)
        return {"status": "saved", "provider": provider}

    @app.get("/api/settings/providers")
    def provider_settings() -> Any:
        return [config.to_dict() for config in ai.configs()]

    @app.post("/api/settings/provider")
    def set_provider_settings(body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            config = ai.set_config(body.get("provider", "ccswitch"), body.get("protocol", "openai"), body.get("base_url"), body.get("model"))
            return config.to_dict()
        except ProviderError as exc:
            raise HTTPException(400, str(exc))

    # 前端 build 產物。存在就掛成同源靜態站，讓「一個行程」就能完整使用。
    # npm run build 之後才有 dist；沒建置過時維持純 API 行為。
    from pathlib import Path

    WEB_DIST = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"

    if (WEB_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(str(WEB_DIST / "index.html"))

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> Any:
            # SPA 路由：非 /api 的路徑一律回到 index.html。
            if full_path.startswith("api/"):
                raise HTTPException(404)
            candidate = WEB_DIST / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(WEB_DIST / "index.html"))

    if os.getenv("WORKLOG_NO_BROWSER") != "1":
        @app.on_event("startup")
        def _open_browser() -> None:
            import threading
            import webbrowser

            host = os.getenv("WORKLOG_HOST", "127.0.0.1")
            port = os.getenv("WORKLOG_PORT", "8000")
            url = "http://%s:%s/" % (host, port)
            # 等 uvicorn 真正開始監聽再開，避免瀏覽器看到連線失敗。
            def _delayed() -> None:
                import time

                time.sleep(1.0)
                webbrowser.open(url)

            threading.Thread(target=_delayed, daemon=True).start()

except ImportError:
    app = None
