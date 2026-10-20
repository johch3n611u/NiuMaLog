from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .base import ParsedConversation, SourceAdapter
from ..domain import Message
from ..utils import parse_datetime, stable_hash, text_from_content


class CodexAdapter(SourceAdapter):
    """解析 Codex 來源。支援兩種格式：

    1. **原生 Codex rollout**（`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`）
       - 檔名是 ``rollout-<時間戳>-<uuid>.jsonl``，不含 "codex"，必須靠路徑與內容辨識
       - 每行一個 record，真正的訊息在巢狀的 ``payload`` 欄位
       - 只有 ``type == "response_item"`` 且 ``payload.type == "message"`` 才是對話
       - ``role`` 為 developer / system 的是注入指令，不是工作內容，略過
    2. **通用匯出格式**（原本就支援，保持不變）
       - dict 帶 ``messages`` 等欄位
    """

    provider = "codex"

    @staticmethod
    def _is_native_rollout(payload: Any) -> bool:
        if not isinstance(payload, list) or not payload:
            return False
        for item in payload[:20]:
            if not isinstance(item, dict):
                continue
            inner = item.get("payload")
            if isinstance(item.get("type"), str) and isinstance(inner, dict):
                return True
        return False

    @staticmethod
    def _mentions_codex(path: Path) -> bool:
        # 路徑任一層出現 .codex / codex 都算（檔名是 rollout- 開頭）。
        return any("codex" in part.lower() or "openai" in part.lower()
                   for part in (*path.parts, path.name))

    def can_handle(self, path: Path, payload: Any = None) -> bool:
        if self._mentions_codex(path):
            return True
        if isinstance(payload, dict):
            marker = " ".join(str(payload.get(k, "")) for k in ("provider", "source", "app", "client")).lower()
            if "codex" in marker or "openai" in marker:
                return True
        return self._is_native_rollout(payload)

    def _parse_native(self, path: Path, records: List[Any]) -> ParsedConversation:
        # 檔名穩定（rollout-<時間戳>-<uuid>），拿來當標題與 id 的一部分最安全。
        title = path.stem
        conversation_id = stable_hash(self.provider, str(path), title)
        messages: List[Message] = []
        project_dir = ""

        for index, item in enumerate(records):
            if not isinstance(item, dict):
                continue
            record_type = item.get("type")

            if record_type == "session_meta" and not project_dir:
                inner = item.get("payload")
                if isinstance(inner, dict):
                    project_dir = str(inner.get("cwd") or "")
                continue

            if record_type != "response_item":
                continue

            inner = item.get("payload")
            if not isinstance(inner, dict) or inner.get("type") != "message":
                continue

            role = str(inner.get("role") or "user").lower()
            # developer / system 是注入的系統指令，不是使用者工作內容。
            if role in ("developer", "system", "tool"):
                continue
            if role in ("human", "user_message", "prompt"):
                role = "user"
            elif role in ("model", "bot"):
                role = "assistant"
            if role not in ("user", "assistant"):
                continue

            text = text_from_content(inner.get("content"))
            if not text:
                continue

            timestamp = parse_datetime(item.get("timestamp"))
            message_id = stable_hash(conversation_id, index, role, text, timestamp)
            messages.append(Message(message_id, conversation_id, role, text, timestamp, {}))

        metadata: Dict[str, Any] = {"format": path.suffix.lower(), "native": True}
        if project_dir:
            metadata["cwd"] = project_dir
        return ParsedConversation(self.provider, title, str(path), messages, metadata)

    def parse(self, path: Path) -> ParsedConversation:
        payload = self.read_payload(path)
        if isinstance(payload, str):
            return self.parse_markdown(path, self.provider)
        if self._is_native_rollout(payload):
            return self._parse_native(path, payload)

        # 通用匯出格式：維持原本行為。
        title = path.stem
        if isinstance(payload, dict):
            title = str(payload.get("title") or payload.get("name") or payload.get("conversation_title") or title)
        conversation_id = stable_hash(self.provider, str(path), title)
        messages = self.messages_from_payload(conversation_id, payload)
        return ParsedConversation(self.provider, title, str(path), messages, {"format": path.suffix.lower()})
