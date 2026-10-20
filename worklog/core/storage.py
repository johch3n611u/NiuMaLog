from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .domain import Conversation, Message, Report, WorkEvent


def _dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


class Storage:
    def __init__(self, path: str = ".worklog/worklog.db"):
        self.path = str(Path(path).expanduser())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    source_hash TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
                CREATE TABLE IF NOT EXISTS work_events (
                    id TEXT PRIMARY KEY,
                    event_date TEXT NOT NULL,
                    project TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL,
                    conversation_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_date ON work_events(event_date);
                CREATE TABLE IF NOT EXISTS event_overrides (
                    event_id TEXT PRIMARY KEY,
                    project_override TEXT,
                    suppressed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    project TEXT,
                    mode TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    html TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def get_meta(self, key: str, default: str = "") -> str:
        with self.connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def upsert_conversation(self, conversation: Conversation, messages: Sequence[Message]) -> bool:
        source_hash = conversation.metadata.get("source_hash")
        with self.connection() as conn:
            current = conn.execute("SELECT source_hash FROM conversations WHERE id = ?", (conversation.id,)).fetchone()
            if current and current["source_hash"] == source_hash:
                return False
            conn.execute(
                """INSERT INTO conversations (id, provider, title, source_path, imported_at, source_hash, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, title=excluded.title,
                     source_path=excluded.source_path, imported_at=excluded.imported_at,
                     source_hash=excluded.source_hash, metadata_json=excluded.metadata_json""",
                (conversation.id, conversation.provider, conversation.title, conversation.source_path,
                 conversation.imported_at.isoformat(), source_hash, json.dumps(conversation.metadata, ensure_ascii=False)),
            )
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation.id,))
            conn.executemany(
                "INSERT INTO messages (id, conversation_id, role, text, timestamp, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                [(m.id, m.conversation_id, m.role, m.text, m.timestamp.isoformat() if m.timestamp else None,
                  json.dumps(m.metadata, ensure_ascii=False)) for m in messages],
            )
            return True

    def list_conversations(self) -> List[Conversation]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM conversations ORDER BY imported_at DESC").fetchall()
        return [Conversation(row["id"], row["provider"], row["title"], row["source_path"],
                             _dt(row["imported_at"]) or datetime.utcnow(), json.loads(row["metadata_json"])) for row in rows]

    def list_messages(self, start: Optional[date] = None, end: Optional[date] = None) -> List[Message]:
        clauses: List[str] = []
        values: List[Any] = []
        if start:
            clauses.append("date(timestamp) >= date(?)")
            values.append(start.isoformat())
        if end:
            clauses.append("date(timestamp) <= date(?)")
            values.append(end.isoformat())
        query = "SELECT * FROM messages"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp, id"
        with self.connection() as conn:
            rows = conn.execute(query, values).fetchall()
        return [Message(row["id"], row["conversation_id"], row["role"], row["text"], _dt(row["timestamp"]), json.loads(row["metadata_json"])) for row in rows]

    def list_all_messages(self) -> List[Message]:
        return self.list_messages()

    def save_events(self, events: Sequence[WorkEvent]) -> None:
        with self.connection() as conn:
            suppressed = {row["event_id"] for row in conn.execute("SELECT event_id FROM event_overrides WHERE suppressed = 1").fetchall()}
            conn.executemany(
                """INSERT INTO work_events (id, event_date, project, event_type, title, summary, evidence_json, confidence, conversation_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET event_date=excluded.event_date, project=excluded.project,
                     event_type=excluded.event_type, title=excluded.title, summary=excluded.summary,
                     evidence_json=excluded.evidence_json, confidence=excluded.confidence,
                     conversation_id=excluded.conversation_id""",
                [(e.id, e.date.isoformat(), e.project, e.type, e.title, e.summary, json.dumps(e.evidence_message_ids), e.confidence, e.conversation_id) for e in events if e.id not in suppressed],
            )

    def replace_events(self, events: Sequence[WorkEvent]) -> None:
        """全量重分析時整批取代事件。

        只 upsert 不刪除的話，事件 id 一變（例如 project 推導結果修正）舊列就會永久殘留。
        event_overrides 是使用者的手動編輯，不會動它。
        """
        with self.connection() as conn:
            conn.execute("DELETE FROM work_events")
        self.save_events(events)

    def list_events(self, start: Optional[date] = None, end: Optional[date] = None, project: Optional[str] = None) -> List[WorkEvent]:
        clauses: List[str] = []
        values: List[Any] = []
        if start:
            clauses.append("event_date >= ?")
            values.append(start.isoformat())
        if end:
            clauses.append("event_date <= ?")
            values.append(end.isoformat())
        if project:
            clauses.append("project = ?")
            values.append(project)
        query = "SELECT e.*, CASE WHEN o.suppressed = 0 THEN COALESCE(o.project_override, e.project) ELSE e.project END AS effective_project FROM work_events e LEFT JOIN event_overrides o ON o.event_id = e.id"
        if clauses:
            clauses = [clause.replace("event_date", "e.event_date").replace("project = ?", "COALESCE(o.project_override, e.project) = ?") for clause in clauses]
            query += " WHERE " + " AND ".join(clauses)
        query += " AND (o.suppressed IS NULL OR o.suppressed = 0)" if clauses else " WHERE (o.suppressed IS NULL OR o.suppressed = 0)"
        query += " ORDER BY e.event_date, effective_project, e.id"
        with self.connection() as conn:
            rows = conn.execute(query, values).fetchall()
        return [WorkEvent(row["id"], date.fromisoformat(row["event_date"]), row["effective_project"], row["event_type"], row["title"], row["summary"], json.loads(row["evidence_json"]), row["confidence"], row["conversation_id"]) for row in rows]

    def update_event_project(self, event_id: str, project: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("UPDATE work_events SET project = ? WHERE id = ?", (project.strip() or "未分类", event_id))
            conn.execute("INSERT INTO event_overrides (event_id, project_override, suppressed) VALUES (?, ?, 0) ON CONFLICT(event_id) DO UPDATE SET project_override=excluded.project_override, suppressed=0", (event_id, project.strip() or "未分类"))
            return cursor.rowcount > 0

    def delete_event(self, event_id: str) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT id FROM work_events WHERE id = ?", (event_id,)).fetchone()
            if not row:
                return False
            conn.execute("INSERT INTO event_overrides (event_id, suppressed) VALUES (?, 1) ON CONFLICT(event_id) DO UPDATE SET suppressed=1", (event_id,))
            conn.execute("DELETE FROM work_events WHERE id = ?", (event_id,))
            return True

    def merge_events(self, target_id: str, source_ids: Sequence[str]) -> bool:
        events = {event.id: event for event in self.list_events()}
        target = events.get(target_id)
        if not target:
            return False
        source_ids = [event_id for event_id in source_ids if event_id != target_id and event_id in events]
        if not source_ids:
            return True
        evidence = list(target.evidence_message_ids)
        summaries = [target.summary]
        for event_id in source_ids:
            evidence.extend(events[event_id].evidence_message_ids)
            summaries.append(events[event_id].summary)
        merged = WorkEvent(target.id, target.date, target.project, target.type, target.title, "；".join(dict.fromkeys(summaries))[:1000], list(dict.fromkeys(evidence)), max([target.confidence] + [events[event_id].confidence for event_id in source_ids]), target.conversation_id)
        self.save_events([merged])
        with self.connection() as conn:
            conn.executemany("INSERT INTO event_overrides (event_id, suppressed) VALUES (?, 1) ON CONFLICT(event_id) DO UPDATE SET suppressed=1", [(event_id,) for event_id in source_ids])
            conn.executemany("DELETE FROM work_events WHERE id = ?", [(event_id,) for event_id in source_ids])
        return True

    def save_report(self, report: Report) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO reports (id, kind, period_start, period_end, project, mode, markdown, html, generated_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET mode=excluded.mode, markdown=excluded.markdown, html=excluded.html,
                     generated_at=excluded.generated_at, metadata_json=excluded.metadata_json""",
                (report.id, report.kind, report.period_start.isoformat(), report.period_end.isoformat(), report.project,
                 report.mode, report.markdown, report.html, report.generated_at.isoformat(), json.dumps(report.metadata, ensure_ascii=False)),
            )

    def latest_report(self, kind: str, start: date, end: date, project: Optional[str] = None) -> Optional[Report]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM reports WHERE kind=? AND period_start=? AND period_end=? AND (project IS ? OR project = ?) ORDER BY generated_at DESC LIMIT 1", (kind, start.isoformat(), end.isoformat(), project, project)).fetchone()
        if not row:
            return None
        return Report(row["id"], row["kind"], date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"]), row["project"], row["mode"], row["markdown"], row["html"], _dt(row["generated_at"]) or datetime.utcnow(), json.loads(row["metadata_json"]))
