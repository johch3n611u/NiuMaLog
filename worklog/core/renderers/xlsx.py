from __future__ import annotations

import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from xml.etree.ElementTree import Element, SubElement, tostring

from ..domain import ReportDocument, WorkEvent


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _tag(name: str) -> str:
    return "{%s}%s" % (MAIN_NS, name)


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _excel_serial(value: date) -> int:
    return (value - date(1899, 12, 30)).days


class ExcelRenderer:
    """Dependency-free XLSX writer for local report exports."""

    def render(self, document: ReportDocument, output_path: str) -> Path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        sheets = [
            ("报告", self._summary_rows(document), [18, 18, 18, 72]),
            ("工作事件", self._event_rows(document), [14, 18, 16, 34, 90, 30]),
            ("对话证据", self._evidence_rows(document), [22, 12, 100, 66]),
        ]
        with zipfile.ZipFile(str(destination), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._content_types(len(sheets)))
            archive.writestr("_rels/.rels", self._root_relationships())
            archive.writestr("xl/workbook.xml", self._workbook(sheets))
            archive.writestr("xl/_rels/workbook.xml.rels", self._workbook_relationships(len(sheets)))
            archive.writestr("xl/styles.xml", self._styles())
            for index, (_, rows, widths) in enumerate(sheets, 1):
                archive.writestr("xl/worksheets/sheet%d.xml" % index, self._worksheet(rows, widths))
        return destination

    def _summary_rows(self, document: ReportDocument) -> List[List[Tuple[str, object, str]]]:
        rows: List[List[Tuple[str, object, str]]] = [
            [("s", document.title, "title")],
            [("s", "周期", "header"), ("s", document.period_start.isoformat(), "date"), ("s", "至", "normal"), ("s", document.period_end.isoformat(), "date")],
            [("s", "概览", "header"), ("s", document.overview, "normal")],
            [],
        ]
        labels = {"completed": "今日完成", "in_progress": "进行中", "blocked": "遇到的问题 / 阻塞", "decision": "关键决策", "next": "下一步"}
        for key in ("completed", "in_progress", "blocked", "decision", "next"):
            rows.append([("s", labels[key], "header")])
            events = document.sections.get(key, [])
            if events:
                rows.extend([[("s", event.title, "normal"), ("s", event.summary, "normal"), ("s", event.project, "normal")] for event in events])
            else:
                rows.append([("s", "暂无记录", "normal")])
            rows.append([])
        rows.append([("s", "按项目", "header")])
        for project in sorted(document.project_summaries):
            rows.append([("s", project, "header")])
            rows.extend([[("s", event.title, "normal"), ("s", event.summary, "normal"), ("s", event.type, "normal")] for event in document.project_summaries[project]])
        return rows

    def _event_rows(self, document: ReportDocument) -> List[List[Tuple[str, object, str]]]:
        rows = [[("s", value, "header") for value in ("日期", "项目", "类型", "标题", "摘要", "证据消息 ID")]]
        events = [event for events in document.sections.values() for event in events]
        for event in events:
            rows.append([
                ("n", _excel_serial(event.date), "date"),
                ("s", event.project, "normal"),
                ("s", event.type, "normal"),
                ("s", event.title, "normal"),
                ("s", event.summary, "normal"),
                ("s", ", ".join(event.evidence_message_ids), "normal"),
            ])
        return rows

    def _evidence_rows(self, document: ReportDocument) -> List[List[Tuple[str, object, str]]]:
        rows = [[("s", value, "header") for value in ("时间", "角色", "内容", "消息 ID")]]
        for message in document.evidence:
            rows.append([
                ("s", message.timestamp.isoformat(sep=" ", timespec="minutes") if message.timestamp else "", "normal"),
                ("s", message.role, "normal"),
                ("s", message.text, "normal"),
                ("s", message.id, "normal"),
            ])
        return rows

    def _worksheet(self, rows: Sequence[Sequence[Tuple[str, object, str]]], widths: Sequence[int]) -> bytes:
        root = Element(_tag("worksheet"), {"xmlns:r": REL_NS})
        sheet_views = SubElement(root, _tag("sheetViews"))
        SubElement(sheet_views, _tag("sheetView"), {"workbookViewId": "0"})
        cols = SubElement(root, _tag("cols"))
        for index, width in enumerate(widths, 1):
            SubElement(cols, _tag("col"), {"min": str(index), "max": str(index), "width": str(width), "customWidth": "1"})
        sheet_data = SubElement(root, _tag("sheetData"))
        for row_index, row in enumerate(rows, 1):
            row_element = SubElement(sheet_data, _tag("row"), {"r": str(row_index)})
            for col_index, (kind, value, style) in enumerate(row, 1):
                cell = SubElement(row_element, _tag("c"), {"r": "%s%d" % (_column_name(col_index), row_index), "s": str({"normal": 0, "title": 1, "header": 2, "date": 3}.get(style, 0))})
                if kind == "n":
                    SubElement(cell, _tag("v")).text = str(value)
                else:
                    cell.set("t", "inlineStr")
                    inline = SubElement(cell, _tag("is"))
                    SubElement(inline, _tag("t")).text = str(value)
        pane = SubElement(sheet_views.find(_tag("sheetView")), _tag("pane"), {"ySplit": "1", "topLeftCell": "A2", "activePane": "bottomLeft", "state": "frozen"})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _content_types(self, count: int) -> bytes:
        root = Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
        SubElement(root, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
        SubElement(root, "Default", {"Extension": "xml", "ContentType": "application/xml"})
        SubElement(root, "Override", {"PartName": "/xl/workbook.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"})
        SubElement(root, "Override", {"PartName": "/xl/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"})
        for index in range(1, count + 1):
            SubElement(root, "Override", {"PartName": "/xl/worksheets/sheet%d.xml" % index, "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _root_relationships(self) -> bytes:
        root = Element("Relationships", {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"})
        SubElement(root, "Relationship", {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "Target": "xl/workbook.xml"})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _workbook(self, sheets: Sequence[Tuple[str, object, object]]) -> bytes:
        root = Element(_tag("workbook"))
        book_views = SubElement(root, _tag("bookViews"))
        SubElement(book_views, _tag("workbookView"))
        sheets_element = SubElement(root, _tag("sheets"))
        for index, (name, _, _) in enumerate(sheets, 1):
            SubElement(sheets_element, _tag("sheet"), {"name": name, "sheetId": str(index), "{%s}id" % REL_NS: "rId%d" % index})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _workbook_relationships(self, count: int) -> bytes:
        root = Element("Relationships", {"xmlns": "http://schemas.openxmlformats.org/package/2006/relationships"})
        for index in range(1, count + 1):
            SubElement(root, "Relationship", {"Id": "rId%d" % index, "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", "Target": "worksheets/sheet%d.xml" % index})
        SubElement(root, "Relationship", {"Id": "rId%d" % (count + 1), "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "Target": "styles.xml"})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _styles(self) -> bytes:
        root = Element(_tag("styleSheet"), {"xmlns": MAIN_NS})
        fonts = SubElement(root, _tag("fonts"), {"count": "2"})
        SubElement(fonts, _tag("font"))
        bold = SubElement(fonts, _tag("font"))
        SubElement(bold, _tag("b"))
        fills = SubElement(root, _tag("fills"), {"count": "2"})
        SubElement(SubElement(fills, _tag("fill")), _tag("patternFill"), {"patternType": "none"})
        SubElement(SubElement(fills, _tag("fill")), _tag("patternFill"), {"patternType": "gray125"})
        borders = SubElement(root, _tag("borders"), {"count": "1"})
        SubElement(borders, _tag("border"))
        cell_style = SubElement(root, _tag("cellStyleXfs"), {"count": "1"})
        SubElement(cell_style, _tag("xf"))
        cell_xfs = SubElement(root, _tag("cellXfs"), {"count": "4"})
        SubElement(cell_xfs, _tag("xf"), {"xfId": "0"})
        SubElement(cell_xfs, _tag("xf"), {"xfId": "0", "fontId": "1"})
        SubElement(cell_xfs, _tag("xf"), {"xfId": "0", "fontId": "1", "fillId": "1"})
        SubElement(cell_xfs, _tag("xf"), {"xfId": "0", "numFmtId": "14"})
        cell_styles = SubElement(root, _tag("cellStyles"), {"count": "1"})
        SubElement(cell_styles, _tag("cellStyle"), {"name": "Normal", "xfId": "0", "builtinId": "0"})
        return tostring(root, encoding="utf-8", xml_declaration=True)
