from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..domain import Message
from ..utils import parse_datetime, stable_hash, text_from_content


@dataclass
class ParsedConversation:
    provider: str
    title: str
    source_path: str
    messages: List[Message]
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return stable_hash(self.provider, self.source_path, self.title)


class SourceAdapter:
    provider = "unknown"

    def can_handle(self, path: Path, payload: Any = None) -> bool:
        raise NotImplementedError

    def parse(self, path: Path) -> ParsedConversation:
        raise NotImplementedError

    @staticmethod
    def read_payload(path: Path) -> Any:
        raw = path.read_text(encoding="utf-8-sig")
        if path.suffix.lower() in (".jsonl", ".ndjson"):
            records = []
            for line in raw.splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
            return records
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    @staticmethod
    def candidate_messages(payload: Any) -> Sequence[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("messages", "chat_messages", "conversation_messages", "turns"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        conversation = payload.get("conversation")
        if isinstance(conversation, dict):
            return SourceAdapter.candidate_messages(conversation)
        data = payload.get("data")
        if isinstance(data, dict):
            return SourceAdapter.candidate_messages(data)
        return []

    @staticmethod
    def message_fields(item: Any) -> tuple:
        if not isinstance(item, dict):
            return "user", text_from_content(item), None, {}
        role = item.get("role") or item.get("sender") or item.get("author") or item.get("type") or "user"
        if isinstance(role, dict):
            role = role.get("role") or role.get("name") or "user"
        role = str(role).lower()
        if role in ("human", "user_message", "prompt"):
            role = "user"
        elif role in ("assistant_message", "model", "bot"):
            role = "assistant"
        elif role in ("tool_result", "tool_use", "function"):
            role = "tool"
        text = text_from_content(item.get("content") or item.get("text") or item.get("parts") or item.get("message"))
        timestamp = parse_datetime(item.get("timestamp") or item.get("created_at") or item.get("createdAt") or item.get("date"))
        metadata = {k: v for k, v in item.items() if k not in {"role", "sender", "author", "type", "content", "text", "parts", "message"}}
        return role, text, timestamp, metadata

    @classmethod
    def messages_from_payload(cls, conversation_id: str, payload: Any) -> List[Message]:
        messages = []
        for index, item in enumerate(cls.candidate_messages(payload)):
            role, text, timestamp, metadata = cls.message_fields(item)
            if not text:
                continue
            message_id = stable_hash(conversation_id, index, role, text, timestamp)
            messages.append(Message(message_id, conversation_id, role, text, timestamp, metadata))
        return messages

    @staticmethod
    def parse_markdown(path: Path, provider: str) -> ParsedConversation:
        raw = path.read_text(encoding="utf-8-sig")
        title = path.stem
        heading = re.search(r"^#\s+(.+)$", raw, flags=re.MULTILINE)
        if heading:
            title = heading.group(1).strip()
        blocks = re.split(r"\n(?=##\s+)", raw)
        messages: List[Message] = []
        conversation_id = stable_hash(provider, str(path), title)
        for index, block in enumerate(blocks):
            match = re.match(r"##\s+(user|assistant|tool|human|claude|codex)\s*\n?(.*)", block, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            role = match.group(1).lower()
            role = "user" if role in ("human",) else "assistant" if role in ("claude", "codex") else role
            text = match.group(2).strip()
            if text:
                messages.append(Message(stable_hash(conversation_id, index, role, text), conversation_id, role, text))
        return ParsedConversation(provider, title, str(path), messages)
