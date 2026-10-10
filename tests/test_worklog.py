from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from worklog.core.adapters import ClaudeAdapter, CodexAdapter
from worklog.core.ai import AnthropicProvider, OpenAIProvider, ProviderError, validate_draft
from worklog.core.domain import ReportInstructions
from worklog.core.importers import ImportService
from worklog.core.service import WorklogService
from worklog.core.storage import Storage


ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"


class WorklogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(str(Path(self.tmp.name) / "worklog.db"))
        self.service = WorklogService(self.storage, str(Path(self.tmp.name) / "exports"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_adapters_parse_fixture_messages(self):
        codex = CodexAdapter().parse(FIXTURES / "codex-session.json")
        claude = ClaudeAdapter().parse(FIXTURES / "claude-session.json")
        self.assertEqual(codex.provider, "codex")
        self.assertEqual(len(codex.messages), 3)
        self.assertEqual(claude.messages[0].role, "user")
        self.assertIn("Markdown", claude.messages[1].text)

    def test_import_is_incremental_and_skips_unknown_files(self):
        importer = ImportService(self.storage)
        first = importer.import_path(str(FIXTURES))
        second = importer.import_path(str(FIXTURES))
        self.assertEqual(first.imported, 2)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.skipped, 2)
        unsupported = importer.import_path(str(FIXTURES / "unsupported.txt"))
        self.assertTrue(any("Unsupported" in error for error in unsupported.errors))
        self.assertEqual(len(self.storage.list_all_messages()), 5)

    def test_deterministic_reports_have_sections_and_evidence(self):
        ImportService(self.storage).import_path(str(FIXTURES))
        report = self.service.generate("daily", date(2026, 10, 10), date(2026, 10, 10))
        self.assertIn("今日完成", report.markdown)
        self.assertIn("遇到的问题", report.markdown)
        self.assertIn("Codex", report.markdown)  # source evidence includes conversation text
        self.assertIn("<html", report.html)
        self.assertTrue((Path(self.tmp.name) / "exports").joinpath("daily-2026-10-10.md").exists())

    def test_week_bounds_and_project_grouping(self):
        ImportService(self.storage).import_path(str(FIXTURES))
        report = self.service.generate("weekly", date(2026, 10, 5), date(2026, 10, 11))
        self.assertIn("按项目", report.markdown)
        self.assertIn("worklog", report.markdown)
        self.assertIn("docs", report.markdown)

    def test_event_project_override_and_suppression_survive_refresh(self):
        ImportService(self.storage).import_path(str(FIXTURES))
        events = self.service.refresh_events()
        self.assertTrue(events)
        self.assertTrue(self.storage.update_event_project(events[0].id, "重新归类"))
        self.assertTrue(self.storage.delete_event(events[1].id))
        self.service.refresh_events()
        current = {event.id: event for event in self.storage.list_events()}
        self.assertEqual(current[events[0].id].project, "重新归类")
        self.assertNotIn(events[1].id, current)

    def test_invalid_ai_output_is_rejected(self):
        with self.assertRaises(ProviderError):
            validate_draft({"overview": "ok", "sections": {"done": "not-an-array"}}, "test")

    def test_ai_generation_falls_back_to_local_report(self):
        ImportService(self.storage).import_path(str(FIXTURES))

        class BrokenProvider:
            def generate_report(self, context, instructions):
                raise ProviderError("invalid response")

        report = self.service.generate_ai_draft("daily", date(2026, 10, 10), date(2026, 10, 10), BrokenProvider())
        self.assertEqual(report.mode, "ai")
        self.assertTrue(report.metadata["fallback"])
        self.assertIn("今日完成", report.markdown)

    @patch("worklog.core.ai.urlopen")
    def test_openai_and_anthropic_payloads_are_provider_specific(self, mocked_urlopen):
        class Response:
            def __init__(self, body): self.body = json.dumps(body).encode()
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body

        context = self.service.context("daily", date(2026, 10, 10), date(2026, 10, 10))
        mocked_urlopen.return_value = Response({"choices": [{"message": {"content": '{"overview":"ok","sections":{}}'}}]})
        draft = OpenAIProvider("secret").generate_report(context, ReportInstructions())
        self.assertEqual(draft.provider, "openai")
        mocked_urlopen.return_value = Response({"content": [{"text": '{"overview":"ok","sections":{}}'}]})
        draft = AnthropicProvider("secret").generate_report(context, ReportInstructions())
        self.assertEqual(draft.provider, "anthropic")


if __name__ == "__main__":
    unittest.main()
