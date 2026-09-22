"""Portable PDF project reports with embedded Unicode fonts."""

from __future__ import annotations

import html
import json
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle


def _fonts() -> tuple[str, str]:
    regular = files("reportlab").joinpath("fonts/Vera.ttf")
    bold = files("reportlab").joinpath("fonts/VeraBd.ttf")
    if "TVScanVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("TVScanVera", str(regular)))
        pdfmetrics.registerFont(TTFont("TVScanVeraBold", str(bold)))
    return "TVScanVera", "TVScanVeraBold"


def export_project_pdf(project: dict[str, Any], rows: Iterable[dict[str, Any]],
                       destination: str | Path) -> int:
    materialized = list(rows)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    regular, bold = _fonts()
    document = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"TV Scan Studio - {project['name']}", author="TV Scan Studio",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName=bold,
                              fontSize=22, leading=26, textColor=colors.HexColor("#0b5394")))
    styles.add(ParagraphStyle(name="ReportHeading", parent=styles["Heading2"], fontName=bold,
                              fontSize=13, leading=17, textColor=colors.HexColor("#0b5394"),
                              spaceBefore=12, spaceAfter=7))
    styles.add(ParagraphStyle(name="ReportBody", parent=styles["BodyText"], fontName=regular,
                              fontSize=8.5, leading=12, textColor=colors.HexColor("#14213d")))
    styles.add(ParagraphStyle(name="Metric", parent=styles["BodyText"], fontName=bold,
                              fontSize=9, leading=13, alignment=TA_CENTER,
                              textColor=colors.HexColor("#0b5394")))
    story = [
        Paragraph("TV Scan Studio", styles["ReportTitle"]),
        Paragraph(
            f"<b>{html.escape(str(project['name']))}</b> - {datetime.now().strftime('%Y-%m-%d %H:%M')}<br/>"
            f"Pine SHA-256: {html.escape(str(project.get('pine_hash') or '-'))}", styles["ReportBody"]
        ), Spacer(1, 6 * mm), Paragraph("Özet", styles["ReportHeading"]),
    ]
    classes: dict[str, int] = {}
    for row in materialized:
        classes[row["classification"]] = classes.get(row["classification"], 0) + 1
    metric_cells = [Paragraph(f"{html.escape(name.title())}<br/><font size='16'>{count}</font>", styles["Metric"])
                    for name, count in sorted(classes.items())]
    if not metric_cells:
        metric_cells = [Paragraph("Sonuç<br/><font size='16'>0</font>", styles["Metric"])]
    metric_table = Table([metric_cells], colWidths=[45 * mm] * len(metric_cells))
    metric_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eaf3fb")),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#9fc5e8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([metric_table, Paragraph("Doğrulanmış sonuçlar", styles["ReportHeading"])])
    headers = ["Görev", "Sembol", "TF", "Sınıf", "İşlem", "PF", "Win %", "DD %", "Net"]
    header_style = ParagraphStyle(name="Header", parent=styles["ReportBody"], fontName=bold,
                                  textColor=colors.white, fontSize=7)
    data = [[Paragraph(value, header_style) for value in headers]]
    for row in materialized:
        metrics = row["metrics"]
        payload = row["payload"]
        values = (row["task_key"][:10], payload.get("symbol", "-"), payload.get("timeframe", "-"),
                  row["classification"], metrics.get("trades", "-"), metrics.get("profit_factor", "-"),
                  metrics.get("win_rate_pct", "-"), metrics.get("max_drawdown_pct", "-"),
                  metrics.get("net_profit", "-"))
        data.append([Paragraph(html.escape(str(value)), styles["ReportBody"]) for value in values])
    if len(data) == 1:
        data.append([Paragraph("Henüz sonuç yok.", styles["ReportBody"])] + [""] * 8)
    result_table = Table(data, repeatRows=1,
                         colWidths=[20*mm, 30*mm, 10*mm, 20*mm, 14*mm, 13*mm, 14*mm, 14*mm, 17*mm])
    result_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b5394")),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#c8d4e3")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([
        result_table, Paragraph("Yöntem ve doğrulama", styles["ReportHeading"]),
        Paragraph("Bu rapor yalnızca sembol, timeframe, tarih aralığı ve input değerleri görevle eşleşen; "
                  "Strategy Tester sonucu kararlı okunan kayıtları içerir.", styles["ReportBody"]),
        Paragraph("Proje ayarları", styles["ReportHeading"]),
        Preformatted(json.dumps(project.get("settings", {}), ensure_ascii=False, indent=2),
                     ParagraphStyle(name="Code", parent=styles["Code"], fontName=regular,
                                    fontSize=7.5, leading=10, backColor=colors.HexColor("#f4f7fb"))),
    ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#5b6577"))
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return len(materialized)
