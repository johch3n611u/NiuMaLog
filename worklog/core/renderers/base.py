from __future__ import annotations

from typing import Protocol

from ..domain import ReportDocument


class ReportRenderer(Protocol):
    def render(self, document: ReportDocument) -> str:
        ...
