from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..domain import Conversation, Message, WorkEvent
from ..utils import clean_text, stable_hash


DONE_TERMS = ("完成", "已完成", "搞定", "修复", "实现了", "已解决", "shipped", "done", "fixed", "implemented", "完成了")
BLOCKED_TERMS = ("阻塞", "卡住", "失败", "报错", "问题", "无法", "blocked", "error", "failed", "issue")
DECISION_TERMS = ("决定", "采用", "选择", "方案", "decision", "choose", "selected")
NEXT_TERMS = ("下一步", "接下来", "计划", "todo", "next", "will ", "需要继续")


class DeterministicAnalyzer:
    """Turn normalized messages into auditable work events using stable rules."""

    def __init__(self, project_overrides: Optional[Dict[str, str]] = None):
        self.project_overrides = project_overrides or {}

    def project_for(self, message: Message, conversation: Optional[Conversation], conversation_projects: Optional[Dict[str, str]] = None) -> str:
        if message.conversation_id in self.project_overrides:
            return self.project_overrides[message.conversation_id]
        text = message.text
        marker = re.search(r"(?:项目|project)\s*[:：]\s*([\w\-./一-龥 ]{1,40})", text, re.IGNORECASE)
        if marker:
            return marker.group(1).strip().rstrip("。,.，")
        tag = re.search(r"#([\w\-]+)", text)
        if tag:
            return tag.group(1)
        if conversation_projects and message.conversation_id in conversation_projects:
            return conversation_projects[message.conversation_id]
        if conversation and conversation.title:
            title = re.sub(r"\s+", " ", conversation.title).strip()
            return title[:48] or "未分类"
        return "未分类"

    def event_type(self, text: str, role: str) -> str:
        lowered = text.lower()
        if any(term.lower() in lowered for term in BLOCKED_TERMS):
            return "blocked"
        if any(term.lower() in lowered for term in DECISION_TERMS):
            return "decision"
        if any(term.lower() in lowered for term in DONE_TERMS):
            return "completed"
        if any(term.lower() in lowered for term in NEXT_TERMS):
            return "next"
        return "in_progress"

    def title_for(self, text: str, event_type: str) -> str:
        first = re.split(r"[\n。.!！?？]", clean_text(text))[0]
        first = first.strip(" -*•#")
        if not first:
            first = {"completed": "完成事项", "blocked": "待解决问题", "decision": "关键决策", "next": "下一步", "in_progress": "工作进展"}[event_type]
        return first[:80]

    def analyze(self, messages: Sequence[Message], conversations: Sequence[Conversation] = ()) -> List[WorkEvent]:
        conversation_map = {conversation.id: conversation for conversation in conversations}
        conversation_projects: Dict[str, str] = {}
        marker_pattern = re.compile(r"(?:项目|project)\s*[:：]\s*([\w\-./一-龥 ]{1,40})", re.IGNORECASE)
        for message in messages:
            marker = marker_pattern.search(message.text)
            if marker:
                conversation_projects[message.conversation_id] = marker.group(1).strip().rstrip("。,.，")
        events: List[WorkEvent] = []
        for message in messages:
            if not message.text.strip() or not message.timestamp:
                continue
            # Assistant messages contain the useful result in most exports. Keep user messages that
            # explicitly state a task so the report is still useful for an unfinished conversation.
            if message.role not in ("assistant", "user"):
                continue
            event_type = self.event_type(message.text, message.role)
            has_project_marker = bool(re.search(r"(?:项目|project)\s*[:：]", message.text, re.IGNORECASE))
            if message.role == "user" and event_type == "in_progress" and len(message.text) < 20 and not has_project_marker:
                continue
            conversation = conversation_map.get(message.conversation_id)
            project = self.project_for(message, conversation, conversation_projects)
            summary = clean_text(message.text)
            event_id = stable_hash(message.id, project, event_type)
            events.append(WorkEvent(event_id, message.timestamp.date(), project, event_type,
                                    self.title_for(message.text, event_type), summary[:500], [message.id],
                                    0.8 if event_type != "in_progress" else 0.55, message.conversation_id))
        return events

    def group(self, events: Sequence[WorkEvent]) -> Dict[str, List[WorkEvent]]:
        grouped: Dict[str, List[WorkEvent]] = defaultdict(list)
        for event in events:
            grouped[event.type].append(event)
        return dict(grouped)
