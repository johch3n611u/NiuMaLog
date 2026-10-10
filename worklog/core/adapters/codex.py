from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import ParsedConversation, SourceAdapter
from ..utils import stable_hash


class CodexAdapter(SourceAdapter):
    provider = "codex"

    def can_handle(self, path: Path, payload: Any = None) -> bool:
        name = path.name.lower()
        if "codex" in name or "openai" in name:
            return True
        if isinstance(payload, dict):
            marker = " ".join(str(payload.get(k, "")) for k in ("provider", "source", "app", "client")).lower()
            return "codex" in marker or "openai" in marker
        return False

    def parse(self, path: Path) -> ParsedConversation:
        payload = self.read_payload(path)
        if isinstance(payload, str):
            return self.parse_markdown(path, self.provider)
        title = path.stem
        if isinstance(payload, dict):
            title = str(payload.get("title") or payload.get("name") or payload.get("conversation_title") or title)
        conversation_id = stable_hash(self.provider, str(path), title)
        messages = self.messages_from_payload(conversation_id, payload)
        return ParsedConversation(self.provider, title, str(path), messages, {"format": path.suffix.lower()})
