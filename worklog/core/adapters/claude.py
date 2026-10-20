from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .base import ParsedConversation, SourceAdapter
from ..domain import Message
from ..utils import parse_datetime, stable_hash, text_from_content


class ClaudeAdapter(SourceAdapter):
    """解析 Claude 來源。支援兩種格式：

    1. **原生 Claude Code session**（`~/.claude/projects/<目錄>/<uuid>.jsonl`）
       - 檔名是 UUID，不含 "claude"，所以必須靠路徑與內容辨識
       - 每行一個 record，真正的訊息在巢狀的 ``message`` 欄位
       - 除 user/assistant 外還有 mode、attachment、ai-title 等非訊息 record
    2. **通用匯出格式**（原本就支援，保持不變）
       - dict 帶 ``chat_messages`` / ``messages`` 等欄位
    """

    provider = "claude"
    # 這些 record 不是對話訊息，導入時略過。
    SKIP_TYPES = {"mode", "permission-mode", "atis-latch", "last-prompt", "attachment",
                  "file-history-snapshot", "system", "ai-title", "summary", "progress"}

    @staticmethod
    def _is_native_session(payload: Any) -> bool:
        if not isinstance(payload, list) or not payload:
            return False
        for item in payload[:20]:
            if not isinstance(item, dict):
                continue
            message = item.get("message")
            if isinstance(item.get("type"), str) and isinstance(message, dict) and "role" in message:
                return True
        return False

    @staticmethod
    def _mentions_claude(path: Path) -> bool:
        # 路徑任一層出現 .claude / claude / anthropic 都算（檔名本身常是 UUID）。
        return any("claude" in part.lower() or "anthropic" in part.lower()
                   for part in (*path.parts, path.name))

    def can_handle(self, path: Path, payload: Any = None) -> bool:
        if self._mentions_claude(path):
            return True
        if isinstance(payload, dict):
            marker = " ".join(str(payload.get(k, "")) for k in ("provider", "source", "app", "client")).lower()
            if "claude" in marker or "anthropic" in marker:
                return True
        return self._is_native_session(payload)

    @staticmethod
    def _title_from_records(payload: List[Any]) -> str:
        for item in payload:
            if isinstance(item, dict) and item.get("type") == "ai-title":
                title = item.get("aiTitle") or item.get("title")
                if title:
                    return str(title).strip()
        return ""

    def _parse_native(self, path: Path, records: List[Any]) -> ParsedConversation:
        title = self._title_from_records(records) or path.stem
        conversation_id = stable_hash(self.provider, str(path), title)
        messages: List[Message] = []
        project_dir = ""
        git_branch = ""

        for index, item in enumerate(records):
            if not isinstance(item, dict):
                continue
            record_type = item.get("type")
            if not isinstance(record_type, str) or record_type in self.SKIP_TYPES:
                continue

            message = item.get("message")
            if not isinstance(message, dict):
                continue

            role = str(message.get("role") or record_type).lower()
            if role in ("human", "user_message", "prompt"):
                role = "user"
            elif role in ("assistant_message", "model", "bot"):
                role = "assistant"
            if role not in ("user", "assistant"):
                continue

            text = text_from_content(message.get("content"))
            if not text:
                continue

            if not project_dir:
                project_dir = str(item.get("cwd") or "")
            if not git_branch:
                git_branch = str(item.get("gitBranch") or "")

            timestamp = parse_datetime(item.get("timestamp"))
            message_id = stable_hash(conversation_id, index, role, text, timestamp)
            messages.append(Message(message_id, conversation_id, role, text, timestamp, {}))

        metadata: Dict[str, Any] = {"format": path.suffix.lower(), "native": True}
        if project_dir:
            metadata["cwd"] = project_dir
        if git_branch:
            metadata["git_branch"] = git_branch
        return ParsedConversation(self.provider, title, str(path), messages, metadata)

    def parse(self, path: Path) -> ParsedConversation:
        payload = self.read_payload(path)
        if isinstance(payload, str):
            return self.parse_markdown(path, self.provider)
        if self._is_native_session(payload):
            return self._parse_native(path, payload)

        # 通用匯出格式：維持原本行為。
        title = path.stem
        if isinstance(payload, dict):
            title = str(payload.get("title") or payload.get("name") or payload.get("conversation_title") or title)
        conversation_id = stable_hash(self.provider, str(path), title)
        messages = self.messages_from_payload(conversation_id, payload)
        return ParsedConversation(self.provider, title, str(path), messages, {"format": path.suffix.lower()})
