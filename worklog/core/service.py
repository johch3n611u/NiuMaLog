from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .analyzers import DeterministicAnalyzer
from .domain import Message, Report, ReportContext, ReportDocument, ReportDraft, WorkEvent
from .renderers import ExcelRenderer, HtmlRenderer, MarkdownRenderer
from .storage import Storage
from .utils import stable_hash


def week_bounds(value: str) -> Tuple[date, date]:
    if "-W" in value:
        year_text, week_text = value.split("-W", 1)
        start = date.fromisocalendar(int(year_text), int(week_text), 1)
        return start, start + timedelta(days=6)
    parsed = date.fromisoformat(value)
    start = parsed - timedelta(days=parsed.weekday())
    return start, start + timedelta(days=6)


class WorklogService:
    def __init__(self, storage: Storage, export_dir: str = ".worklog/exports"):
        self.storage = storage
        self.export_dir = Path(export_dir)
        self.analyzer = DeterministicAnalyzer()
        self.markdown = MarkdownRenderer()
        self.html = HtmlRenderer()
        self.excel = ExcelRenderer()

    def refresh_events(self) -> List[WorkEvent]:
        conversations = self.storage.list_conversations()
        messages = self.storage.list_all_messages()
        events = self.analyzer.analyze(messages, conversations)
        self.storage.save_events(events)
        return events

    def build_document(self, kind: str, start: date, end: date, project: Optional[str] = None) -> ReportDocument:
        events = [event for event in self.refresh_events() if start <= event.date <= end and (project is None or event.project == project)]
        sections: Dict[str, List[WorkEvent]] = defaultdict(list)
        projects: Dict[str, List[WorkEvent]] = defaultdict(list)
        for event in events:
            sections[event.type].append(event)
            projects[event.project].append(event)
        if kind == "daily":
            title = "工作日志 · %s" % start.isoformat()
            overview = "共记录 %d 条工作事件，涉及 %d 个项目。" % (len(events), len(projects))
        else:
            title = "工作周报 · %s 至 %s" % (start.isoformat(), end.isoformat())
            overview = "本周共记录 %d 条工作事件，涉及 %d 个项目。" % (len(events), len(projects))
        evidence_ids = []
        for event in events:
            evidence_ids.extend(event.evidence_message_ids)
        message_map = {message.id: message for message in self.storage.list_all_messages()}
        evidence = [message_map[mid] for mid in evidence_ids if mid in message_map]
        return ReportDocument(kind, start, end, title, overview, dict(sections), dict(projects), evidence)

    def generate(self, kind: str, start: date, end: date, mode: str = "deterministic", project: Optional[str] = None) -> Report:
        document = self.build_document(kind, start, end, project)
        markdown = self.markdown.render(document)
        html = self.html.render(document)
        now = datetime.utcnow()
        report_id = stable_hash(kind, start, end, project or "", mode)
        report = Report(report_id, kind, start, end, project, mode, markdown, html, now, {"event_count": sum(len(v) for v in document.sections.values()), "evidence_count": len(document.evidence)})
        self.storage.save_report(report)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        stem = "%s-%s" % (kind, start.isoformat() if kind == "daily" else "%s-W%s" % (start.isocalendar()[0], str(start.isocalendar()[1]).zfill(2)))
        if project:
            stem += "-%s" % project.replace("/", "-").replace(" ", "-")
        (self.export_dir / (stem + ".md")).write_text(markdown, encoding="utf-8")
        (self.export_dir / (stem + ".html")).write_text(html, encoding="utf-8")
        xlsx_path = self.excel.render(document, str(self.export_dir / (stem + ".xlsx")))
        report.metadata["xlsx_path"] = str(xlsx_path)
        self.storage.save_report(report)
        return report

    def context(self, kind: str, start: date, end: date, selected_message_ids: Optional[Sequence[str]] = None, include_raw: bool = False) -> ReportContext:
        document = self.build_document(kind, start, end)
        messages = self.storage.list_all_messages()
        if selected_message_ids:
            selected = [message for message in messages if message.id in set(selected_message_ids)]
        else:
            evidence = {message.id for message in document.evidence}
            selected = [message for message in messages if message.id in evidence]
        return ReportContext(document, selected, include_raw)

    def generate_ai_draft(self, kind: str, start: date, end: date, provider, selected_message_ids: Optional[Sequence[str]] = None, include_raw: bool = False, project: Optional[str] = None):
        """Generate an AI report while preserving a deterministic fallback and its error metadata."""
        from .ai import ProviderError
        from .domain import ReportInstructions
        context = self.context(kind, start, end, selected_message_ids, include_raw)
        try:
            draft = provider.generate_report(context, ReportInstructions())
            document = context.document
            sections = defaultdict(list)
            for key, items in draft.sections.items():
                normalized = key if key in ("completed", "in_progress", "blocked", "decision", "next") else "in_progress"
                for index, item in enumerate(items):
                    sections[normalized].append(WorkEvent(stable_hash("ai", draft.provider, key, index, item.get("title")), start, project or "AI 精炼", normalized, item["title"], item["summary"], [], 0.7))
            document = ReportDocument(kind, start, end, document.title, draft.overview, dict(sections), document.project_summaries, document.evidence)
            return self._save_document(document, "ai", {"provider": draft.provider, "event_count": sum(len(v) for v in sections.values()), "evidence_count": len(document.evidence), "fallback": False})
        except ProviderError as exc:
            fallback = self.generate(kind, start, end, "ai", project)
            fallback.metadata.update({"fallback": True, "fallback_error": str(exc)})
            self.storage.save_report(fallback)
            return fallback

    def _save_document(self, document: ReportDocument, mode: str, metadata: Dict[str, object], project: Optional[str] = None) -> Report:
        markdown = self.markdown.render(document)
        html = self.html.render(document)
        now = datetime.utcnow()
        report = Report(stable_hash(document.kind, document.period_start, document.period_end, project or "", mode), document.kind, document.period_start, document.period_end, project, mode, markdown, html, now, metadata)
        self.storage.save_report(report)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        stem = "%s-%s" % (document.kind, document.period_start.isoformat() if document.kind == "daily" else "%s-W%s" % (document.period_start.isocalendar()[0], str(document.period_start.isocalendar()[1]).zfill(2)))
        (self.export_dir / (stem + ".md")).write_text(markdown, encoding="utf-8")
        (self.export_dir / (stem + ".html")).write_text(html, encoding="utf-8")
        xlsx_path = self.excel.render(document, str(self.export_dir / (stem + ".xlsx")))
        report.metadata["xlsx_path"] = str(xlsx_path)
        self.storage.save_report(report)
        return report
