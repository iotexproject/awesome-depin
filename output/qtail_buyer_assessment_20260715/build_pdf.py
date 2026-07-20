from __future__ import annotations

import html
import json
import re
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "output/pdf"
PDF_DIR.mkdir(parents=True, exist_ok=True)
PDF_PATH = PDF_DIR / "Q-Tail_具身机器人厂商买方评估.pdf"

artifact = json.loads((OUT / "artifact.json").read_text(encoding="utf-8"))
manifest = artifact["manifest"]
datasets = artifact["snapshot"]["datasets"]


def register_fonts() -> tuple[str, str]:
    candidates = [
        (
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
        ),
        (
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ),
        (
            "/Library/Fonts/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        ),
    ]
    for regular, bold in candidates:
        if not Path(regular).exists() or not Path(bold).exists():
            continue
        try:
            pdfmetrics.registerFont(TTFont("QTailCJK", regular))
            pdfmetrics.registerFont(TTFont("QTailCJKBold", bold))
            pdfmetrics.registerFontFamily(
                "QTailCJK",
                normal="QTailCJK",
                bold="QTailCJKBold",
                italic="QTailCJK",
                boldItalic="QTailCJKBold",
            )
            return "QTailCJK", "QTailCJKBold"
        except Exception:
            continue
    raise RuntimeError("No compatible CJK font was found")


FONT, FONT_BOLD = register_fonts()

INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#5E6B7E")
BLUE = colors.HexColor("#315FA8")
BLUE_LIGHT = colors.HexColor("#DCE8F7")
GOLD = colors.HexColor("#B98724")
PAPER = colors.HexColor("#F8FAFC")
GRID = colors.HexColor("#D7DEE8")
SOFT_RED = colors.HexColor("#FCE8E6")
SOFT_AMBER = colors.HexColor("#FFF3D6")
SOFT_GREEN = colors.HexColor("#E5F3EA")


styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="ReportTitle",
        fontName=FONT_BOLD,
        fontSize=24,
        leading=31,
        textColor=INK,
        spaceAfter=12,
        alignment=TA_LEFT,
    )
)
styles.add(
    ParagraphStyle(
        name="H2CJK",
        fontName=FONT_BOLD,
        fontSize=15,
        leading=21,
        textColor=INK,
        spaceBefore=13,
        spaceAfter=7,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        name="H3CJK",
        fontName=FONT_BOLD,
        fontSize=11.5,
        leading=17,
        textColor=BLUE,
        spaceBefore=9,
        spaceAfter=5,
        keepWithNext=True,
    )
)
styles.add(
    ParagraphStyle(
        name="BodyCJK",
        fontName=FONT,
        fontSize=9.4,
        leading=15.5,
        textColor=INK,
        spaceAfter=6,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="BulletCJK",
        parent=styles["BodyCJK"],
        leftIndent=14,
        firstLineIndent=-9,
        bulletIndent=4,
        spaceAfter=4,
    )
)
styles.add(
    ParagraphStyle(
        name="TableHeaderCJK",
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="TableCellCJK",
        fontName=FONT,
        fontSize=8.2,
        leading=11.8,
        textColor=INK,
        alignment=TA_LEFT,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="CaptionCJK",
        fontName=FONT,
        fontSize=8,
        leading=11,
        textColor=MUTED,
        spaceAfter=6,
    )
)


def inline_markup(text: str) -> str:
    value = html.escape(text, quote=False)
    value = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<link href="\2" color="#315FA8"><u>\1</u></link>',
        value,
    )
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r"<font name=\"Courier\">\1</font>", value)
    return value


def markdown_flowables(body: str):
    lines = body.splitlines()
    result = []
    buffer: list[str] = []

    def flush():
        if buffer:
            result.append(Paragraph(inline_markup(" ".join(buffer)), styles["BodyCJK"]))
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.startswith("# "):
            flush()
            result.append(Paragraph(inline_markup(stripped[2:]), styles["ReportTitle"]))
        elif stripped.startswith("## "):
            flush()
            result.append(Paragraph(inline_markup(stripped[3:]), styles["H2CJK"]))
        elif stripped.startswith("### "):
            flush()
            result.append(Paragraph(inline_markup(stripped[4:]), styles["H3CJK"]))
        elif stripped.startswith("- "):
            flush()
            result.append(Paragraph(inline_markup(stripped[2:]), styles["BulletCJK"], bulletText="•"))
        elif re.match(r"^\d+\.\s+", stripped):
            flush()
            number, item = stripped.split(".", 1)
            result.append(Paragraph(inline_markup(item.strip()), styles["BulletCJK"], bulletText=f"{number}."))
        else:
            buffer.append(stripped)
    flush()
    return result


TABLE_WIDTHS = {
    "offer_scores": [42 * mm, 20 * mm, 53 * mm, 132 * mm],
    "current_evidence": [43 * mm, 77 * mm, 127 * mm],
    "buyer_gates": [41 * mm, 22 * mm, 135 * mm, 49 * mm],
    "segments": [48 * mm, 30 * mm, 32 * mm, 137 * mm],
    "roadmap": [45 * mm, 102 * mm, 100 * mm],
}


def format_value(value, column: dict) -> str:
    if value is None:
        return ""
    if column.get("format") == "number" and isinstance(value, (int, float)):
        return f"{value:.1f}"
    return str(value)


def table_flowable(table_id: str):
    spec = next(item for item in manifest["tables"] if item["id"] == table_id)
    rows = datasets[spec["dataset"]]
    headers = [Paragraph(inline_markup(column["label"]), styles["TableHeaderCJK"]) for column in spec["columns"]]
    data = [headers]
    for row in rows:
        data.append(
            [
                Paragraph(inline_markup(format_value(row.get(column["field"]), column)), styles["TableCellCJK"])
                for column in spec["columns"]
            ]
        )
    table = Table(
        data,
        colWidths=TABLE_WIDTHS[table_id],
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=True,
    )
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if table_id == "buyer_gates":
        for index, row in enumerate(rows, start=1):
            status = row.get("qtail", "")
            fill = SOFT_RED if status == "未达到" else SOFT_AMBER if status == "部分达到" else SOFT_GREEN
            commands.append(("BACKGROUND", (3, index), (3, index), fill))
    table.setStyle(TableStyle(commands))
    return KeepTogether(
        [
            Paragraph(inline_markup(spec["title"]), styles["H3CJK"]),
            Paragraph(inline_markup(spec.get("subtitle", "")), styles["CaptionCJK"]),
            table,
            Spacer(1, 6),
        ]
    )


def procurement_chart() -> Drawing:
    rows = datasets["procurement_gap"]
    actual = {row["criterion"]: row["points"] for row in rows if row["series"] == "当前得分"}
    maximum = {row["criterion"]: row["points"] for row in rows if row["series"] == "满分"}
    labels = [
        "直接可训练性",
        "策略与真机增益",
        "机型与物理有效性",
        "长尾覆盖",
        "质量与审计",
        "集成成熟度",
        "合规与安全",
        "规模/成本/SLA",
        "独立泛化",
    ]
    width = 247 * mm
    height = 88 * mm
    drawing = Drawing(width, height)
    label_x = 4 * mm
    bar_x = 60 * mm
    bar_width = 155 * mm
    row_height = 8.4 * mm
    top = height - 11 * mm
    scale = bar_width / 20.0
    drawing.add(String(label_x, height - 5 * mm, "当前加权得分 / 该项满分", fontName=FONT_BOLD, fontSize=9.2, fillColor=INK))
    drawing.add(Rect(193 * mm, height - 6.5 * mm, 6 * mm, 2.6 * mm, fillColor=BLUE, strokeColor=None))
    drawing.add(String(201 * mm, height - 6.6 * mm, "当前", fontName=FONT, fontSize=7.4, fillColor=MUTED))
    drawing.add(Rect(218 * mm, height - 6.5 * mm, 6 * mm, 2.6 * mm, fillColor=BLUE_LIGHT, strokeColor=None))
    drawing.add(String(226 * mm, height - 6.6 * mm, "满分", fontName=FONT, fontSize=7.4, fillColor=MUTED))
    for index, label in enumerate(labels):
        y = top - index * row_height
        max_value = maximum.get(label, 0.0)
        actual_value = actual.get(label, 0.0)
        drawing.add(String(label_x, y + 1.1 * mm, label, fontName=FONT, fontSize=7.6, fillColor=INK))
        drawing.add(Rect(bar_x, y, max_value * scale, 3.6 * mm, fillColor=BLUE_LIGHT, strokeColor=None))
        drawing.add(Rect(bar_x, y, actual_value * scale, 3.6 * mm, fillColor=BLUE, strokeColor=None))
        drawing.add(
            String(
                bar_x + max_value * scale + 3 * mm,
                y + 0.6 * mm,
                f"{actual_value:.1f}/{max_value:.0f}",
                fontName=FONT,
                fontSize=7.2,
                fillColor=MUTED,
            )
        )
    return drawing


def header_footer(canvas, doc):
    canvas.saveState()
    page_width, page_height = landscape(A4)
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, page_height - 13 * mm, page_width - 18 * mm, page_height - 13 * mm)
    canvas.setFont(FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, page_height - 10 * mm, "Q-Tail 具身机器人厂商买方评估")
    canvas.drawRightString(page_width - 18 * mm, page_height - 10 * mm, "评估日期：2026-07-15")
    canvas.line(18 * mm, 12 * mm, page_width - 18 * mm, 12 * mm)
    canvas.drawString(18 * mm, 8 * mm, "Coherent (Beijing) Technology Co., Ltd. - 专业买方评估")
    canvas.drawRightString(page_width - 18 * mm, 8 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


story = []
for block in manifest["blocks"]:
    if block["type"] == "markdown":
        story.extend(markdown_flowables(block["body"]))
    elif block["type"] == "chart":
        story.append(Paragraph("数据采购准备度分项", styles["H3CJK"]))
        story.append(Paragraph("当前加权得分与每项满分对比；九项合计满分为 100。", styles["CaptionCJK"]))
        story.append(procurement_chart())
        story.append(Spacer(1, 7))
    elif block["type"] == "table":
        story.append(table_flowable(block["tableId"]))


doc = SimpleDocTemplate(
    str(PDF_PATH),
    pagesize=landscape(A4),
    rightMargin=18 * mm,
    leftMargin=18 * mm,
    topMargin=18 * mm,
    bottomMargin=17 * mm,
    title=manifest["title"],
    author="OpenAI Codex for Coherent (Beijing) Technology Co., Ltd.",
    subject="Q-Tail embodied robotics vendor buyer assessment",
)
doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print(PDF_PATH)
