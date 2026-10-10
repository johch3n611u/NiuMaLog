from __future__ import annotations

from typing import Dict, Iterable, List

from ..domain import ReportDocument, WorkEvent


SECTION_LABELS = {
    "completed": "今日完成",
    "in_progress": "进行中",
    "blocked": "遇到的问题 / 阻塞",
    "decision": "关键决策",
    "next": "下一步",
}


class MarkdownRenderer:
    def render(self, document: ReportDocument) -> str:
        lines = ["# %s" % document.title, "", "**周期：** %s 至 %s" % (document.period_start.isoformat(), document.period_end.isoformat()), ""]
        if document.overview:
            lines.extend(["## 概览", "", document.overview, ""])
        for key in ("completed", "in_progress", "blocked", "decision", "next"):
            lines.extend(self._section(SECTION_LABELS[key], document.sections.get(key, [])))
        if document.project_summaries:
            lines.extend(["## 按项目", ""])
            for project in sorted(document.project_summaries):
                lines.extend(["### %s" % project, ""])
                for event in document.project_summaries[project]:
                    lines.append("- **%s**：%s" % (event.title, event.summary))
                lines.append("")
        lines.extend(["## 关联对话证据", ""])
        if document.evidence:
            for message in document.evidence:
                timestamp = message.timestamp.isoformat(sep=" ", timespec="minutes") if message.timestamp else "未知时间"
                lines.append("- `%s` · %s · %s" % (timestamp, message.role, message.text[:240].replace("\n", " ")))
        else:
            lines.append("- 暂无可关联的对话证据")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _section(self, title: str, events: List[WorkEvent]) -> List[str]:
        lines = ["## %s" % title, ""]
        if not events:
            lines.append("- 暂无记录")
        else:
            for event in events:
                lines.append("- **%s**：%s" % (event.title, event.summary))
        lines.append("")
        return lines
