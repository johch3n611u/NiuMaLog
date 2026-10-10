from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@dataclass
class Conversation:
    id: str
    provider: str
    title: str
    source_path: str
    imported_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: _iso(v) for k, v in asdict(self).items()}


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str
    text: str
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: _iso(v) for k, v in asdict(self).items()}


@dataclass
class WorkEvent:
    id: str
    date: date
    project: str
    type: str
    title: str
    summary: str
    evidence_message_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5
    conversation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: _iso(v) for k, v in asdict(self).items()}


@dataclass
class ReportDocument:
    kind: str
    period_start: date
    period_end: date
    title: str
    overview: str
    sections: Dict[str, List[WorkEvent]]
    project_summaries: Dict[str, List[WorkEvent]] = field(default_factory=dict)
    evidence: List[Message] = field(default_factory=list)


@dataclass
class Report:
    id: str
    kind: str
    period_start: date
    period_end: date
    project: Optional[str]
    mode: str
    markdown: str
    html: str
    generated_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: _iso(v) for k, v in asdict(self).items()}


@dataclass
class ReportContext:
    document: ReportDocument
    selected_messages: List[Message] = field(default_factory=list)
    include_raw: bool = False

    def as_payload(self) -> Dict[str, Any]:
        return {
            "kind": self.document.kind,
            "period_start": self.document.period_start.isoformat(),
            "period_end": self.document.period_end.isoformat(),
            "title": self.document.title,
            "overview": self.document.overview,
            "sections": {
                key: [event.to_dict() for event in events]
                for key, events in self.document.sections.items()
            },
            "project_summaries": {
                key: [event.to_dict() for event in events]
                for key, events in self.document.project_summaries.items()
            },
            "selected_messages": [
                message.to_dict() if self.include_raw else {
                    "id": message.id,
                    "role": message.role,
                    "timestamp": _iso(message.timestamp),
                    "text": message.text[:1200],
                }
                for message in self.selected_messages
            ],
        }


@dataclass
class ReportInstructions:
    language: str = "zh-CN"
    tone: str = "clear, factual, and concise"
    redaction_terms: List[str] = field(default_factory=list)


@dataclass
class ReportDraft:
    overview: str
    sections: Dict[str, List[Dict[str, Any]]]
    provider: str
    raw_response: Optional[Dict[str, Any]] = None

