"""Portable PDF project reports with embedded Unicode fonts."""

from __future__ import annotations

import html
import json
import math
import textwrap
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

from .result_filters import SUCCESS_CLASSES


def _metric_text(value: Any, decimals: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "—"
    return f"{value:.{decimals}f}"


def _fonts() -> tuple[str, str]:
    regular = files("reportlab").joinpath("fonts/Vera.ttf")
    bold = files("reportlab").joinpath("fonts/VeraBd.ttf")
    if "TVScanVera" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("TVScanVera", str(regular)))
        pdfmetrics.registerFont(TTFont("TVScanVeraBold", str(bold)))
    return "TVScanVera", "TVScanVeraBold"


def export_project_pdf(project: dict[str, Any], rows: Iterable[dict[str, Any]],
                       destination: str | Path) -> int:
    materialized = [row for row in rows
                    if row.get("classification") in SUCCESS_CLASSES and row.get("verified") is True]
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
                              fontSize=22, leading=26, textColor=colors.HexColor("#3a322a")))
    styles.add(ParagraphStyle(name="ReportHeading", parent=styles["Heading2"], fontName=bold,
                              fontSize=13, leading=17, textColor=colors.HexColor("#b9863f"),
                              spaceBefore=12, spaceAfter=7))
    styles.add(ParagraphStyle(name="ReportBody", parent=styles["BodyText"], fontName=regular,
                              fontSize=8.5, leading=12, textColor=colors.HexColor("#3a322a")))
    styles.add(ParagraphStyle(name="Metric", parent=styles["BodyText"], fontName=bold,
                              fontSize=9, leading=13, alignment=TA_CENTER,
                              textColor=colors.HexColor("#3a322a")))
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
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5ecdd")),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#ece0c8")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([metric_table, Paragraph("Sonuçlar ve doğrulama durumu", styles["ReportHeading"])])
    headers = ["Görev", "Sembol", "TF", "Sınıf", "İşlem", "PF", "Win %", "DD %", "Net", "Kanıt"]
    header_style = ParagraphStyle(name="Header", parent=styles["ReportBody"], fontName=bold,
                                  textColor=colors.white, fontSize=7)
    data = [[Paragraph(value, header_style) for value in headers]]
    for row in materialized:
        metrics = row["metrics"]
        payload = row["payload"]
        values = (row["task_key"][:10], payload.get("symbol", "-"), payload.get("timeframe", "-"),
                  row["classification"], _metric_text(metrics.get("trades"), 0),
                  _metric_text(metrics.get("profit_factor"), 3),
                  _metric_text(metrics.get("win_rate_pct"), 1),
                  _metric_text(metrics.get("max_drawdown_pct"), 2),
                  _metric_text(metrics.get("net_profit"), 2),
                  "Doğrulandı" if row.get("verified") else "Geçersiz")
        data.append([Paragraph(html.escape(str(value)), styles["ReportBody"]) for value in values])
    if len(data) == 1:
        data.append([Paragraph("Henüz sonuç yok.", styles["ReportBody"])] + [""] * 9)
    result_table = Table(data, repeatRows=1,
                         colWidths=[18*mm, 37*mm, 10*mm, 20*mm, 13*mm, 12*mm, 13*mm, 13*mm, 17*mm, 23*mm])
    result_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8b6330")),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#ece0c8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fbf7f0")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.extend([
        result_table, Paragraph("Yöntem ve doğrulama", styles["ReportHeading"]),
        Paragraph("Doğrulandı satırları sembol, timeframe, tarih aralığı ve input değerleri görevle eşleşen; "
                  "Strategy Tester sonucu kararlı okunan kayıtlardır. Bu PDF yalnız başarılı presetleri içerir. "
                  "Farklı sağlayıcı ve forward doğrulaması yalnız ilgili kanıt ayrıca kaydedildiyse geçerlidir.",
                  styles["ReportBody"]),
        Paragraph("Günlük/total kayıp ölçümleri kapanmış işlem ve mevcut equity satırlarından türetilen "
                  "tarama göstergeleridir; FTMO gün içi açık pozisyon equity sınırını doğrudan kanıtlamaz.",
                  styles["ReportBody"]),
        Paragraph("Proje ayarları", styles["ReportHeading"]),
        Preformatted("\n".join(
            line for raw in json.dumps(project.get("settings", {}), ensure_ascii=False, indent=2).splitlines()
            for line in (textwrap.wrap(raw, width=94, break_long_words=True, break_on_hyphens=False) or [""])
        ),
                     ParagraphStyle(name="Code", parent=styles["Code"], fontName=regular,
                                    fontSize=7.5, leading=10, backColor=colors.HexColor("#f5ecdd"))),
    ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#5b6577"))
        canvas.drawRightString(A4[0] - 14 * mm, 8 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return len(materialized)


def _research_funnel(catalog: dict[str, Any], regular: str, bold: str) -> Drawing:
    values = [catalog["session_tests"]["planned"], catalog["session_tests"]["valid"],
              catalog["session_tests"]["moderate_passes"], catalog["heavy_tests"]["passes"]]
    labels = ["Planlanan", "Geçerli", "Orta maliyet", "Ağır maliyet"]
    chart = Drawing(720, 132)
    maximum = math.log10(max(values) + 1)
    for index, (label, value) in enumerate(zip(labels, values)):
        top = 105 - index * 31
        chart.add(String(0, top, label, fontName=regular, fontSize=9,
                         fillColor=colors.HexColor("#14213d")))
        width = max(4, 455 * math.log10(value + 1) / maximum)
        chart.add(Rect(112, top - 3, width, 14, rx=3, ry=3,
                       fillColor=colors.HexColor("#287d8e" if index < 3 else "#3d8b62"),
                       strokeColor=None))
        chart.add(String(586, top, f"{value:,}".replace(",", "."),
                         fontName=bold, fontSize=10, fillColor=colors.HexColor("#14213d")))
    return chart


def export_research_pdf(catalog: dict[str, Any], destination: str | Path) -> int:
    """Present historical presets with explicit evidence boundaries and next gates."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    regular, bold = _fonts()
    document = SimpleDocTemplate(
        str(path), pagesize=landscape(A4), leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=catalog["title"], author="TV Scan Studio",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("ResearchTitle", parent=styles["Title"], fontName=bold,
                           fontSize=21, leading=26, textColor=colors.HexColor("#20324a"))
    heading = ParagraphStyle("ResearchHeading", parent=styles["Heading2"], fontName=bold,
                             fontSize=12, leading=16, spaceBefore=10, spaceAfter=5,
                             textColor=colors.HexColor("#20324a"))
    body = ParagraphStyle("ResearchBody", parent=styles["BodyText"], fontName=regular,
                          fontSize=8.5, leading=12, textColor=colors.HexColor("#20324a"))
    small = ParagraphStyle("ResearchSmall", parent=body, fontSize=7.5, leading=10)
    header = ParagraphStyle("ResearchTableHeader", parent=small, fontName=bold,
                            textColor=colors.white)
    story = [
        Paragraph(html.escape(catalog["title"]), title),
        Paragraph("Araştırma amaçlı Strategy Tester sonuçları | OANDA verisi | 23.09.2026", body),
        Spacer(1, 4 * mm), _research_funnel(catalog, regular, bold),
        Paragraph("Çubuklar logaritmik ölçektedir; sağdaki sayılar kesindir.", small),
        Paragraph("Karar", heading),
        Paragraph("33.075 görevden 32.923 geçerli sonuç elde edildi. 501 orta maliyet adayının tamamı "
                  "%0,04 komisyon + 10 tick toplam spread/kayma cezasıyla yeniden sınandı; yedi ayar "
                  "sert eşiği korudu. Bu yedi session kombinasyonu başka veri sağlayıcısında henüz "
                  "doğrulanmadı ve forward işlem kanıtı yoktur.", body),
        Paragraph("Geçiş: en az 60 işlem, PF en az 1,40, win rate en az %40 ve Max DD %5'in altında. "
                  "Maliyet ayrımı: orta %0,02 + 5 tick; ağır %0,04 + 10 tick. "
                  "19.584 normal tarama ayrı bir deney evrenidir.", small),
        Paragraph("Örneklem süreleri farklıdır: DE30 yaklaşık 387 gün, NAS100 yaklaşık 107 gün. "
                  "PF ve net yüzdeleri doğrudan eşit gözlem süresi gibi karşılaştırmayın.", small),
        Paragraph("Ağır maliyeti geçen ayarlar", heading),
    ]
    labels = ["Preset / session", "Sembol", "TF/FVG", "Dönem", "İşlem", "PF", "Win %", "DD %", "Net %", "Sağlayıcı"]
    table_data = [[Paragraph(html.escape(label), header) for label in labels]]
    for index, record in enumerate(catalog["records"], 1):
        metric = record["heavy_metrics"]
        anchor = f"preset_{index}"
        title_link = f'<link href="#{anchor}" color="#0b5394">{html.escape(record["preset_id"])} / {html.escape(record["variant"])}</link>'
        start, end = record["period_label"].split(" - ", 1)
        compact_period = f"{start[5:7]}/{start[2:4]}-{end[5:7]}/{end[2:4]}"
        values = [title_link, record["symbol"], f'{record["chart_tf"]}/{record["fvg_tf"]}',
                  compact_period,
                  str(metric["trades"]), f'{metric["pf"]:.3f}', f'{metric["win"]:.1f}',
                  f'{metric["dd"]:.2f}', f'{metric["net_pct"]:.2f}',
                  {"passed": "Geçti", "queued": "Kuyrukta", "running": "Çalışıyor",
                   "failed": "Geçmedi"}.get(record["evidence"]["alternative_provider"], "Bekliyor")]
        table_data.append([Paragraph(value if column == 0 else html.escape(value), small)
                           for column, value in enumerate(values)])
    table = Table(table_data, repeatRows=1,
                  colWidths=[75*mm, 30*mm, 18*mm, 33*mm, 15*mm, 17*mm, 17*mm, 17*mm, 17*mm, 21*mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#20324a")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf3f5")]),
        ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#cbd6df")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([table, PageBreak()])
    for index, record in enumerate(catalog["records"], 1):
        metric, moderate = record["heavy_metrics"], record["moderate_metrics"]
        anchor = f"preset_{index}"
        changed = record["changed_inputs"]
        block = [
            Paragraph(f'<a name="{anchor}"/>{index}. {html.escape(record["preset_id"])} - '
                      f'{html.escape(record["variant"])}', heading),
            Paragraph(f'{html.escape(record["symbol"])} | Grafik/FVG {record["chart_tf"]}/{record["fvg_tf"]} | '
                      f'{metric["trades"]} işlem | PF {metric["pf"]:.3f} | Win %{metric["win"]:.1f} | '
                      f'Max DD %{metric["dd"]:.2f} | Net %{metric["net_pct"]:.2f}', body),
            Paragraph(f'Test dönemi: {html.escape(record["period_label"])} '
                      f'({record["coverage_days"]} gün).', small),
            Paragraph(f'Orta maliyet PF {moderate["pf"]:.3f}, DD %{moderate["dd"]:.2f}; '
                      f'ağır maliyet komisyon %{record["cost"]["commission_pct"]:.2f} + '
                      f'{record["cost"]["combined_spread_slippage_ticks"]} tick. '
                      f'Alternatif sağlayıcı: {html.escape({"pending": "bekliyor", "queued": "kuyrukta", "running": "çalışıyor", "passed": "geçti", "failed": "geçmedi"}.get(record["evidence"]["alternative_provider"], record["evidence"]["alternative_provider"]))}; '
                      'demo forward: başlamadı.', small),
            Paragraph("Varsayılandan farklı Pine girdileri (İngilizce arayüz adları)", small),
        ]
        halves = [changed[:math.ceil(len(changed)/2)], changed[math.ceil(len(changed)/2):]]
        columns = []
        for half in halves:
            text = "<br/>".join(
                f'{html.escape(item["title"])}: <b>{"ON" if item["value"] is True else "OFF" if item["value"] is False else html.escape(str(item["value"]))}</b>'
                for item in half
            )
            columns.append(Paragraph(text or "-", small))
        settings_table = Table([columns], colWidths=[120 * mm, 120 * mm])
        settings_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf3f5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        block.extend([settings_table,
                      Paragraph("Saatler Pine içinde America/New_York saat dilimindedir. "
                                "Listelenmeyen girdiler eşleme kaynağının varsayılanındadır; "
                                "tarihsel testin Pine SHA-256 özeti bulunmuyor.", small)])
        story.extend([KeepTogether(block), Spacer(1, 5 * mm)])
        if index in (2, 4, 6):
            story.append(PageBreak())
    story.extend([PageBreak(), Paragraph("Önerilen sonraki taramalar", heading)])
    for scan in catalog["next_scans"]:
        story.append(Paragraph(f'<b>{scan["priority"]}. {html.escape(scan["name"])}</b> - '
                               f'{html.escape(scan["scope"])}', body))
        story.append(Spacer(1, 3 * mm))
    story.extend([
        Paragraph("Kanıt ve kaynak", heading),
        Paragraph(f'Yedi ham sonuç: {html.escape(catalog["source_file"])}; '
                  f'SHA-256 {catalog["source_sha256"]}. '
                  'Input adları güncel Pine eşleme kaynağından alınmıştır; tarihsel Pine sürüm hash’i '
                  'mevcut değildir. Sağlayıcı doğrulaması yalnız ilgili yeni görevlerde başarıyla '
                  'kaydedilen ayarlar için geçerlidir; forward kanıtı ayrıca gerekir.', small),
        Paragraph("Kapanmış işlem analizi varsa dahi FTMO intraday equity sınırının doğrudan kanıtı "
                  "değildir. Backtest, maliyet stresi, farklı sağlayıcı ve forward sonuçları ayrı kapılardır.", small),
    ])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#657180"))
        canvas.drawString(16 * mm, 8 * mm, "TV Scan Studio | Araştırma / backtest")
        canvas.drawRightString(landscape(A4)[0] - 16 * mm, 8 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return len(catalog["records"])
