from __future__ import annotations

import html

from ..domain import ReportDocument
from .markdown import SECTION_LABELS


class HtmlRenderer:
    def render(self, document: ReportDocument) -> str:
        sections = []
        if document.overview:
            sections.append("<section><h2>概览</h2><p>%s</p></section>" % html.escape(document.overview))
        for key in ("completed", "in_progress", "blocked", "decision", "next"):
            events = document.sections.get(key, [])
            items = "".join("<li><strong>%s</strong>：%s</li>" % (html.escape(event.title), html.escape(event.summary)) for event in events)
            if not items:
                items = "<li>暂无记录</li>"
            sections.append("<section><h2>%s</h2><ul>%s</ul></section>" % (SECTION_LABELS[key], items))
        if document.project_summaries:
            project_html = []
            for project in sorted(document.project_summaries):
                items = "".join("<li><strong>%s</strong>：%s</li>" % (html.escape(event.title), html.escape(event.summary)) for event in document.project_summaries[project])
                project_html.append("<h3>%s</h3><ul>%s</ul>" % (html.escape(project), items))
            sections.append("<section><h2>按项目</h2>%s</section>" % "".join(project_html))
        evidence = "".join("<li><code>%s</code> · %s · %s</li>" % (html.escape(message.timestamp.isoformat(sep=" ", timespec="minutes") if message.timestamp else "未知时间"), html.escape(message.role), html.escape(message.text[:240])) for message in document.evidence)
        sections.append("<section><h2>关联对话证据</h2><ul>%s</ul></section>" % (evidence or "<li>暂无可关联的对话证据</li>"))
        return "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>%s</title><style>%s</style></head><body><main><h1>%s</h1><p class=\"period\">周期：%s 至 %s</p>%s</main></body></html>" % (
            html.escape(document.title),
            "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f7f7f4;color:#242424;line-height:1.6;margin:0}main{max-width:860px;margin:48px auto;padding:0 24px;background:#fff}h1{font-size:32px;margin-bottom:4px}.period{color:#6b6b64}section{border-top:1px solid #e8e8e2;padding:18px 0}li{margin:7px 0}",
            html.escape(document.title), html.escape(document.period_start.isoformat()), html.escape(document.period_end.isoformat()), "".join(sections))
