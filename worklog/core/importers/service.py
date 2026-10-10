from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from datetime import datetime as _datetime
import os
import hashlib
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ..adapters import ClaudeAdapter, CodexAdapter, ParsedConversation, SourceAdapter
from ..domain import Conversation, Message
from ..storage import Storage


SUPPORTED_SUFFIXES = {".json", ".jsonl", ".ndjson", ".md", ".markdown"}


@dataclass
class ImportResult:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    conversations: List[Conversation] = field(default_factory=list)


class ImportService:
    def __init__(self, storage: Storage, adapters: Optional[Sequence[SourceAdapter]] = None):
        self.storage = storage
        self.adapters = list(adapters or (CodexAdapter(), ClaudeAdapter()))

    def scan(self, root: str) -> List[str]:
        path = Path(root).expanduser()
        if path.is_file():
            return [str(path)] if path.suffix.lower() in SUPPORTED_SUFFIXES else []
        if not path.exists():
            return []
        return sorted(str(item) for item in path.rglob("*") if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES)

    def _adapter_for(self, path: Path) -> Optional[SourceAdapter]:
        payload = None
        try:
            if path.suffix.lower() in (".json", ".jsonl", ".ndjson"):
                payload = SourceAdapter.read_payload(path)
        except Exception:
            payload = None
        for adapter in self.adapters:
            try:
                if adapter.can_handle(path, payload):
                    return adapter
            except Exception:
                continue
        # A provider marker in the file name is the safe, deterministic fallback.
        lower = path.name.lower()
        if "codex" in lower or "openai" in lower:
            return CodexAdapter()
        if "claude" in lower or "anthropic" in lower:
            return ClaudeAdapter()
        return None

    def import_path(self, root: str) -> ImportResult:
        result = ImportResult()
        root_path = Path(root).expanduser()
        if root_path.is_file() and root_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            result.scanned = 1
            result.skipped = 1
            result.errors.append("Unsupported source format: %s" % root_path)
            return result
        for raw_path in self.scan(root):
            result.scanned += 1
            path = Path(raw_path)
            adapter = self._adapter_for(path)
            if adapter is None:
                result.skipped += 1
                result.errors.append("Unsupported source format: %s" % path)
                continue
            try:
                parsed = adapter.parse(path)
                fallback_time = _datetime.fromtimestamp(path.stat().st_mtime)
                for message in parsed.messages:
                    if message.timestamp is None:
                        message.timestamp = fallback_time
                conversation = Conversation(
                    id=parsed.id,
                    provider=parsed.provider,
                    title=parsed.title,
                    source_path=parsed.source_path,
                    imported_at=datetime.utcnow(),
                    metadata=dict(parsed.metadata, source_hash=hashlib.sha256(path.read_bytes()).hexdigest()),
                )
                inserted = self.storage.upsert_conversation(conversation, parsed.messages)
                if inserted:
                    result.imported += 1
                    result.conversations.append(conversation)
                else:
                    result.skipped += 1
            except Exception as exc:
                result.errors.append("%s: %s" % (path, exc))
        return result
