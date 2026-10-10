from __future__ import annotations

import zipfile
from pathlib import Path
from typing import List, Sequence, Tuple
from xml.etree.ElementTree import Element, SubElement, tostring, register_namespace

from ..domain import ReportDocument, WorkEvent


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
register_namespace("p", P_NS)
register_namespace("a", A_NS)
register_namespace("r", R_NS)


def p(name: str) -> str:
    return "{%s}%s" % (P_NS, name)


def a(name: str) -> str:
    return "{%s}%s" % (A_NS, name)


class PptxRenderer:
    """Dependency-free editable PPTX renderer for concise work reports."""

    WIDTH = 12192000
    HEIGHT = 6858000

    def render(self, document: ReportDocument, output_path: str) -> Path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        slides = self._slides(document)
        with zipfile.ZipFile(str(destination), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._content_types(len(slides)))
            archive.writestr("_rels/.rels", self._root_rels())
            archive.writestr("ppt/presentation.xml", self._presentation(len(slides)))
            archive.writestr("ppt/_rels/presentation.xml.rels", self._presentation_rels(len(slides)))
            archive.writestr("ppt/slideMasters/slideMaster1.xml", self._slide_master())
            archive.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", self._slide_master_rels())
            archive.writestr("ppt/slideLayouts/slideLayout1.xml", self._slide_layout())
            archive.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", self._slide_layout_rels())
            archive.writestr("ppt/theme/theme1.xml", self._theme())
            for index, slide in enumerate(slides, 1):
                archive.writestr("ppt/slides/slide%d.xml" % index, self._slide(slide))
                archive.writestr("ppt/slides/_rels/slide%d.xml.rels" % index, self._slide_rels())
        return destination

    def _slides(self, document: ReportDocument) -> List[Tuple[str, str, List[str]]]:
        slides: List[Tuple[str, str, List[str]]] = [(document.title, "%s 至 %s" % (document.period_start.isoformat(), document.period_end.isoformat()), [document.overview])]
        completed = document.sections.get("completed", []) + document.sections.get("in_progress", [])
        slides.append(("工作内容", "完成事项与进行中", self._event_lines(completed) or ["暂无记录"]))
        issues = document.sections.get("blocked", []) + document.sections.get("decision", [])
        slides.append(("问题与决策", "需要关注的事项", self._event_lines(issues) or ["暂无记录"]))
        slides.append(("下一步", "后续行动", self._event_lines(document.sections.get("next", [])) or ["暂无记录"]))
        if document.project_summaries:
            project_lines = ["%s：%d 条工作事件" % (project, len(document.project_summaries[project])) for project in sorted(document.project_summaries)]
            slides.append(("项目概览", "按项目汇总", project_lines))
        return slides

    @staticmethod
    def _event_lines(events: Sequence[WorkEvent]) -> List[str]:
        return ["%s：%s" % (event.title, event.summary[:150]) for event in events[:8]]

    def _slide(self, slide: Tuple[str, str, List[str]]) -> bytes:
        title, subtitle, lines = slide
        root = Element(p("sld"), {"xmlns:a": A_NS, "xmlns:r": R_NS})
        bg = SubElement(root, p("bg"))
        bg_pr = SubElement(bg, p("bgPr"))
        solid = SubElement(bg_pr, a("solidFill"))
        SubElement(solid, a("srgbClr"), {"val": "F7F7F4"})
        SubElement(bg_pr, a("effectLst"))
        c_sld = SubElement(root, p("cSld"))
        tree = SubElement(c_sld, p("spTree"))
        self._group_props(tree)
        self._text_box(tree, 2, "Title", 650000, 470000, 10800000, 800000, title, 2800, True, "292925")
        self._text_box(tree, 3, "Subtitle", 680000, 1200000, 10600000, 380000, subtitle, 1500, False, "77776E")
        body = "\n".join("• " + line for line in lines)
        self._text_box(tree, 4, "Body", 900000, 1900000, 10100000, 3900000, body, 1900, False, "3F3F38")
        clr = SubElement(root, p("clrMapOvr"))
        SubElement(clr, a("masterClrMapping"))
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _group_props(self, tree: Element) -> None:
        group = SubElement(tree, p("nvGrpSpPr"))
        SubElement(group, p("cNvPr"), {"id": "1", "name": ""})
        SubElement(group, p("cNvGrpSpPr"))
        SubElement(group, p("nvPr"))
        SubElement(tree, p("grpSpPr"))

    def _text_box(self, tree: Element, shape_id: int, name: str, x: int, y: int, cx: int, cy: int, text: str, size: int, bold: bool, color: str) -> None:
        shape = SubElement(tree, p("sp"))
        nv = SubElement(shape, p("nvSpPr"))
        SubElement(nv, p("cNvPr"), {"id": str(shape_id), "name": name})
        SubElement(nv, p("cNvSpPr"), {"txBox": "1"})
        SubElement(nv, p("nvPr"))
        sp_pr = SubElement(shape, p("spPr"))
        xfrm = SubElement(sp_pr, a("xfrm"))
        SubElement(xfrm, a("off"), {"x": str(x), "y": str(y)})
        SubElement(xfrm, a("ext"), {"cx": str(cx), "cy": str(cy)})
        SubElement(sp_pr, a("prstGeom"), {"prst": "rect"})
        tx_body = SubElement(shape, p("txBody"))
        SubElement(tx_body, a("bodyPr"), {"wrap": "square"})
        SubElement(tx_body, a("lstStyle"))
        for line in text.split("\n") or [""]:
            para = SubElement(tx_body, a("p"))
            run = SubElement(para, a("r"))
            rpr = SubElement(run, a("rPr"), {"lang": "zh-CN", "sz": str(size), "b": "1" if bold else "0"})
            fill = SubElement(rpr, a("solidFill"))
            SubElement(fill, a("srgbClr"), {"val": color})
            SubElement(run, a("t")).text = line
            SubElement(para, a("endParaRPr"), {"lang": "zh-CN", "sz": str(size)})

    def _presentation(self, count: int) -> bytes:
        root = Element(p("presentation"), {"xmlns:a": A_NS, "xmlns:r": R_NS})
        masters = SubElement(root, p("sldMasterIdLst"))
        SubElement(masters, p("sldMasterId"), {"id": "2147483648", "{%s}id" % R_NS: "rId1"})
        slides = SubElement(root, p("sldIdLst"))
        for index in range(1, count + 1):
            SubElement(slides, p("sldId"), {"id": str(255 + index), "{%s}id" % R_NS: "rId%d" % (index + 2)})
        SubElement(root, p("sldSz"), {"cx": str(self.WIDTH), "cy": str(self.HEIGHT), "type": "screen16x9"})
        SubElement(root, p("notesSz"), {"cx": "6858000", "cy": "9144000"})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _slide_master(self) -> bytes:
        root = Element(p("sldMaster"), {"xmlns:a": A_NS, "xmlns:r": R_NS})
        tree = SubElement(SubElement(root, p("cSld")), p("spTree"))
        self._group_props(tree)
        SubElement(root, p("clrMap"), {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2", "accent1": "accent1", "accent2": "accent2", "accent3": "accent3", "accent4": "accent4", "accent5": "accent5", "accent6": "accent6", "hlink": "hlink", "folHlink": "folHlink"})
        SubElement(root, p("sldLayoutIdLst"))
        SubElement(root, p("txStyles"))
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _slide_layout(self) -> bytes:
        root = Element(p("sldLayout"), {"type": "blank", "preserve": "1", "xmlns:a": A_NS, "xmlns:r": R_NS})
        tree = SubElement(SubElement(root, p("cSld"), {"name": "Blank"}), p("spTree"))
        self._group_props(tree)
        clr = SubElement(root, p("clrMapOvr"))
        SubElement(clr, a("masterClrMapping"))
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _slide_rels(self) -> bytes:
        return self._rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml")])

    def _slide_master_rels(self) -> bytes:
        return self._rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout", "../slideLayouts/slideLayout1.xml"), ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme", "../theme/theme1.xml")])

    def _slide_layout_rels(self) -> bytes:
        return self._rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "../slideMasters/slideMaster1.xml")])

    def _presentation_rels(self, count: int) -> bytes:
        relationships = [("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster", "slideMasters/slideMaster1.xml"), ("rId2", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme", "theme/theme1.xml")]
        relationships.extend(("rId%d" % (index + 2), "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide", "slides/slide%d.xml" % index) for index in range(1, count + 1))
        return self._rels_xml(relationships)

    def _rels_xml(self, relationships: Sequence[Tuple[str, str, str]]) -> bytes:
        root = Element("Relationships", {"xmlns": PKG_REL_NS})
        for rel_id, rel_type, target in relationships:
            SubElement(root, "Relationship", {"Id": rel_id, "Type": rel_type, "Target": target})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _root_rels(self) -> bytes:
        return self._rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "ppt/presentation.xml")])

    def _content_types(self, count: int) -> bytes:
        root = Element("Types", {"xmlns": CT_NS})
        SubElement(root, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
        SubElement(root, "Default", {"Extension": "xml", "ContentType": "application/xml"})
        overrides = [("/ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"), ("/ppt/slideMasters/slideMaster1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"), ("/ppt/slideLayouts/slideLayout1.xml", "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"), ("/ppt/theme/theme1.xml", "application/vnd.openxmlformats-officedocument.theme+xml")]
        overrides.extend(("/ppt/slides/slide%d.xml" % index, "application/vnd.openxmlformats-officedocument.presentationml.slide+xml") for index in range(1, count + 1))
        for part, content_type in overrides:
            SubElement(root, "Override", {"PartName": part, "ContentType": content_type})
        return tostring(root, encoding="utf-8", xml_declaration=True)

    def _theme(self) -> bytes:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Worklog"><a:themeElements><a:clrScheme name="Worklog"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="292925"/></a:dk2><a:lt2><a:srgbClr val="F7F7F4"/></a:lt2><a:accent1><a:srgbClr val="6E8F70"/></a:accent1><a:accent2><a:srgbClr val="A26A52"/></a:accent2><a:accent3><a:srgbClr val="806F93"/></a:accent3><a:accent4><a:srgbClr val="6F7F9E"/></a:accent4><a:accent5><a:srgbClr val="C7C7BD"/></a:accent5><a:accent6><a:srgbClr val="77776E"/></a:accent6><a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink></a:clrScheme><a:fontScheme name="Worklog"><a:majorFont><a:latin typeface="Aptos Display"/><a:ea typeface="等线"/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/><a:ea typeface="等线"/></a:minorFont></a:fontScheme><a:fmtScheme name="Worklog"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme></a:themeElements></a:theme>'''.encode('utf-8')
