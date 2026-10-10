from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .core.importers import ImportService
from .core.service import WorklogService, week_bounds
from .core.storage import Storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worklog", description="Create local work logs from Codex and Claude conversations")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="List supported files")
    scan.add_argument("path")
    imp = sub.add_parser("import", help="Import conversations into SQLite")
    imp.add_argument("path")
    imp.add_argument("--db", default=".worklog/worklog.db")
    daily = sub.add_parser("daily", help="Generate a daily report")
    daily.add_argument("--date", dest="report_date", required=True)
    daily.add_argument("--db", default=".worklog/worklog.db")
    daily.add_argument("--output", default=".worklog/exports")
    weekly = sub.add_parser("weekly", help="Generate a weekly report")
    weekly.add_argument("--week", required=True, help="ISO week such as 2026-W41")
    weekly.add_argument("--db", default=".worklog/worklog.db")
    weekly.add_argument("--output", default=".worklog/exports")
    export = sub.add_parser("export", help="Generate a report and print its exported path")
    export.add_argument("--format", choices=("markdown", "html", "excel"), required=True)
    export.add_argument("--date", dest="report_date")
    export.add_argument("--week")
    export.add_argument("--db", default=".worklog/worklog.db")
    export.add_argument("--output", default=".worklog/exports")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        files = ImportService(Storage(":memory:")).scan(args.path)
        print("\n".join(files))
        return 0
    if args.command == "import":
        result = ImportService(Storage(args.db)).import_path(args.path)
        print(json.dumps({"scanned": result.scanned, "imported": result.imported, "skipped": result.skipped, "errors": result.errors}, ensure_ascii=False, indent=2))
        return 1 if result.errors and result.imported == 0 else 0
    storage = Storage(args.db)
    service = WorklogService(storage, args.output)
    if args.command == "daily":
        start = date.fromisoformat(args.report_date)
        report = service.generate("daily", start, start)
    elif args.command == "weekly":
        start, end = week_bounds(args.week)
        report = service.generate("weekly", start, end)
    else:
        if args.week:
            start, end = week_bounds(args.week)
            kind = "weekly"
        elif args.report_date:
            start = date.fromisoformat(args.report_date)
            end = start
            kind = "daily"
        else:
            raise SystemExit("export requires --date or --week")
        report = service.generate(kind, start, end)
        path = Path(args.output) / (("weekly-%s-W%s" % (start.isocalendar()[0], str(start.isocalendar()[1]).zfill(2))) if kind == "weekly" else "daily-%s" % start.isoformat())
        path = path.with_suffix({"markdown": ".md", "html": ".html", "excel": ".xlsx"}[args.format])
        print(path)
        return 0
    print(report.markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
