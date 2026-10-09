"""TV Scan Studio desktop application."""

from __future__ import annotations

import os
import sys
import json
import itertools
import math
import unicodedata
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6 import QtCore, QtGui, QtWidgets, QtNetwork

from .pine import parse_strategy_inputs, strategy_title, validate_input_value
from .planner import ScanPlan, enqueue_plan, iter_tasks
from .export import (CSV_FILTERS, export_results_csv, export_task_csv, export_task_xlsx,
                     export_project_task_scope)
from .backup import create_backup, verify_backup, restore_backup
from .resources import recommend_workers, system_snapshot
from .supervisor import WorkerAssignment, WorkerSupervisor
from .tradingview import (GncZihinDriver, confirmed_strategy_identity_matches,
                          TradingViewError, SourceReadUnavailable, pine_source_hash, strategy_structure_matches)
from .windows import (TabCreationError, cdp_healthy, chart_targets, find_tradingview_executables,
                      launch_with_cdp, open_chart_tabs, worker_layout_candidates)
from .storage import Store
from .scan_values import parse_scan_values
from .recommendations import historical_values_by_input, input_dependencies, suggest_input
from .profiles import COST_SCENARIOS, FTMO_SYMBOL_PROFILES, apply_cost_multiplier
from .report import export_project_pdf, export_research_pdf
from .research import (describe_session_choice, iter_successful_research_records,
                       load_catalog, provider_check_tasks, with_provider_status)
from .result_filters import SUCCESS_CLASSES, filter_results
from .historical import iter_historical_records
from .instance import desktop_instance
from .sensitivity import build_sensitivity, verified_no_effect_inputs
from .session_variants import SESSION_IDS, observed_session_variants
from .validation import enqueue_followups
from .ui_controls import DecisionChoice, DisclosureButton, SwitchToggle, SafeWheelFilter
from .preparation import (PreparationResult, PreparationState,
                          find_prepared_chart, prepare_empty_layout)
from .symbol_search import search_url, catalogue_results


def event_evidence_tooltip(store, reference, *, verify=True):
    """Present relocated evidence without modifying the original event reference."""
    if not reference:
        return "Bu olay için ekran görüntüsü kaydedilmedi."
    if not verify:
        return "Özgün kayıt (değiştirilmedi):\n" + str(reference) + "\n\nYeni kanıt konumunu ve dosya bütünlüğünü kontrol etmek için bu hücreye çift tıkla. Henüz doğrulanmadı."
    from .restored_assets import resolve_restored_asset
    original = "Özgün kayıt (değiştirilmedi):\n" + str(reference)
    try:
        restored = resolve_restored_asset(store, reference)
    except (ValueError, OSError) as error:
        return "Geri yüklenen kanıt açılamıyor: " + str(error) + "\n\n" + original
    if restored is not None:
        return "Geri yüklenen kanıtın dosya bütünlüğü doğrulandı:\n" + str(restored) + "\n\n" + original
    return "Yerel kanıt dosyası:\n" + str(reference) + "\nDosyanın mevcut olduğu veya yeniden doğrulandığı varsayılmaz."


STYLE = """
QWidget { background:#f3f4f5; color:#292d32; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#f3f4f5; }
QLabel { background:transparent; }
#rail { background:#ffffff; border-right:1px solid #d9dde1; }
#brand { color:#292d32; font-family:'Segoe UI'; font-size:19px; font-weight:600; padding:18px 14px; }
#tagline { color:#68756d; padding:0 14px 20px 14px; }
QPushButton { background:#fffdf9; color:#28332e; border:1px solid #d8d0c2; border-radius:7px; padding:8px 12px; }
QPushButton:hover { background:#f2ecdf; border-color:#b9863f; }
QPushButton:disabled { color:#9ba69e; background:#efe9dc; }
QPushButton[nav='true'] { text-align:left; padding:11px 15px; border:0; border-left:3px solid transparent; border-radius:0; background:#ebe7dc; color:#53635a; }
QPushButton[nav='true']:checked { background:#f8f5ef; border-left-color:#b9863f; color:#28332e; font-weight:600; }
QPushButton[nav='true']:hover { background:#e3ddcf; }
QPushButton#primary { background:#b9863f; color:#fffdf9; border:1px solid #a06b2a; border-radius:7px; padding:9px 17px; font-weight:600; }
QPushButton#primary:hover { background:#a06b2a; }
QPushButton#primary:disabled { background:#ddd1ba; color:#6a665d; border-color:#ddd1ba; }
QLineEdit,QPlainTextEdit,QTableWidget,QComboBox,QSpinBox,QDoubleSpinBox,QListWidget {
  background:#fffdf9; color:#28332e; border:1px solid #d8d0c2; border-radius:6px; padding:6px;
  selection-background-color:#e9d8b9; selection-color:#28332e;
}
QLineEdit:focus,QPlainTextEdit:focus,QComboBox:focus,QTableWidget:focus,
QSpinBox:focus,QDoubleSpinBox:focus,QListWidget:focus,QPushButton:focus { border-color:#b9863f; }
QSpinBox::up-button,QSpinBox::down-button,QDoubleSpinBox::up-button,QDoubleSpinBox::down-button {
  width:0px; border:0; background:transparent;
}
QComboBox QAbstractItemView { background:#fffdf9; color:#28332e; border:1px solid #b9863f; selection-background-color:#efe9dc; }
QHeaderView::section { background:#ebe7dc; color:#53635a; border:0; border-bottom:1px solid #d8d0c2; padding:8px; font-weight:600; }
QTableWidget { gridline-color:#e7e3d9; alternate-background-color:#f8f5ef; }
#title { font-family:'Segoe UI'; font-size:23px; font-weight:600; color:#292d32; }
#subtitle { color:#68756d; font-size:14px; }
#sectionTitle { color:#292d32; font-family:'Segoe UI'; font-size:16px; font-weight:600; padding:6px 0; }
#metric { background:#fffdf9; border:1px solid #e7e3d9; border-radius:8px; padding:16px; }
#metricLabel { color:#68756d; font-size:12px; }
#metricValue { border:0; background:transparent; color:#28332e; font-size:24px; font-weight:700; text-align:left; padding:0; }
#metricValue:hover { color:#8b6330; }
#status { color:#6b4c22; padding:8px 0; }
#filterChip { background:#ece0c8; color:#3a322a; border:1px solid #ddc9a3; border-radius:6px; padding:5px 9px; }
QProgressBar { background:#ebe7dc; border:1px solid #d8d0c2; border-radius:5px; color:#28332e; text-align:center; min-height:21px; }
QProgressBar::chunk { background:#b9863f; border-radius:4px; }
QPushButton[nav='true'] { background:#ffffff; color:#59636c; }
QPushButton[nav='true']:checked { background:#f3f4f5; color:#292d32; }
QPushButton,QLineEdit,QPlainTextEdit,QTableWidget,QComboBox,QSpinBox,QDoubleSpinBox,QListWidget { background:#ffffff; border-color:#d9dde1; color:#292d32; }
QHeaderView::section { background:#eef0f2; color:#59636c; border-bottom-color:#d9dde1; }
QTableWidget { gridline-color:#e3e6e9; alternate-background-color:#f3f4f5; }
QSpinBox::up-button,QSpinBox::down-button,QDoubleSpinBox::up-button,QDoubleSpinBox::down-button { width:18px; }
"""

STATUS_SUCCESS = "#477a62"
STATUS_ERROR = "#b54c42"
STATUS_INFO = "#6b4c22"
STATUS_WARNING = "#a06b2a"


def funnel_icon():
    """Small palette-matched filter glyph without an external icon dependency."""
    pixmap = QtGui.QPixmap(18, 18)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor("#3a322a"))
    painter.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(2, 3), QtCore.QPointF(16, 3),
        QtCore.QPointF(11, 9), QtCore.QPointF(11, 15),
        QtCore.QPointF(7, 17), QtCore.QPointF(7, 9),
    ]))
    painter.end()
    return QtGui.QIcon(pixmap)


PROJECT_STATUS_LABELS = {
    "draft": "Taslak", "queued": "Kuyrukta", "running": "Çalışıyor",
    "paused": "Duraklatıldı", "complete": "Tamamlandı", "cancelled": "İptal edildi",
}

WORKER_READY_LABEL = "Kaynak kullanıcı onaylı · yapı eşleşiyor"


def _finite_plot_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


class ProjectProgressBar(QtWidgets.QProgressBar):
    clicked = QtCore.Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class CurveChart(QtWidgets.QWidget):
    def __init__(self, points, parent=None, *, closed_trade_only=False):
        super().__init__(parent)
        self.closed_trade_only = closed_trade_only
        original = list(points or [])
        self._invalid_points = any(
            not isinstance(point, dict) or
            not all(_finite_plot_number(point.get(key)) for key in ("time", "equity", "drawdown"))
            for point in original
        )
        self.points = [] if self._invalid_points else original
        self.setMinimumHeight(190)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAccessibleName("Kapanmış işlem bazlı tahmini equity ve drawdown grafiği"
                               if closed_trade_only else "Equity ve drawdown grafiği")
        self.setAccessibleDescription("Artı ve eksi tuşları yakınlaştırır; Home tüm dönemi gösterir.")
        self._view_start = 0
        self._view_end = len(self.points)
        self._hover_index = None
        self._drag_start = None

    def _area(self):
        return self.rect().adjusted(106 if self.closed_trade_only else 42, 18, -18, -28)

    def _index_at(self, x):
        area = self._area()
        count = self._view_end - self._view_start
        if count < 1 or area.width() < 1:
            return None
        fraction = max(0.0, min(1.0, (x - area.left()) / area.width()))
        return self._view_start + round(fraction * (count - 1))

    def mouseMoveEvent(self, event):
        area = self._area()
        self._hover_index = self._index_at(event.position().x()) if area.contains(event.position().toPoint()) else None
        if self._hover_index is not None:
            point = self.points[self._hover_index]
            moment = QtCore.QDateTime.fromMSecsSinceEpoch(int(point.get("time") or 0), QtCore.Qt.UTC)
            prefix = "Kapanış " if self.closed_trade_only else ""
            self.setToolTip(f"{moment.toString('yyyy-MM-dd HH:mm')} UTC\n{prefix}Equity: {point.get('equity')}\n{prefix}DD: {point.get('drawdown')}")
        else:
            self.setToolTip("")
        self.update()

    def leaveEvent(self, event):
        self._hover_index = None
        self.setToolTip("")
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_start = self._index_at(event.position().x())

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self._drag_start is not None:
            end = self._index_at(event.position().x())
            start = min(self._drag_start, end)
            stop = max(self._drag_start, end) + 1
            if stop - start >= 2:
                self._view_start, self._view_end = start, stop
                self.update()
            self._drag_start = None

    def mouseDoubleClickEvent(self, _event):
        self._view_start, self._view_end = 0, len(self.points)
        self.update()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Home:
            self._view_start, self._view_end = 0, len(self.points)
            self.update()
            event.accept()
            return
        if event.key() in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal,
                           QtCore.Qt.Key_Minus, QtCore.Qt.Key_Underscore):
            count = self._view_end - self._view_start
            if count >= 2:
                zoom_in = event.key() in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal)
                span = max(2, min(len(self.points), round(count * (0.75 if zoom_in else 1.33))))
                center = (self._view_start + self._view_end - 1) / 2
                start = max(0, min(len(self.points) - span, round(center - (span - 1) / 2)))
                self._view_start, self._view_end = start, start + span
                self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        count = self._view_end - self._view_start
        if count < 3:
            return
        factor = 0.75 if event.angleDelta().y() > 0 else 1.33
        span = max(2, min(len(self.points), round(count * factor)))
        anchor = self._index_at(event.position().x())
        fraction = max(0, min(1, (event.position().x() - self._area().left()) / max(1, self._area().width())))
        start = max(0, min(len(self.points) - span, round(anchor - fraction * (span - 1))))
        self._view_start, self._view_end = start, start + span
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        area = self._area()
        painter.fillRect(self.rect(), QtGui.QColor("#fffdf8"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#ddc9a3"), 1))
        painter.drawRect(area)
        points = self.points[self._view_start:self._view_end]
        if len(points) < 2:
            message = ("Equity/DD noktaları eksik veya geçersiz; eğri çizilmedi"
                       if self._invalid_points else "Grafik için yeterli işlem yok")
            painter.setPen(QtGui.QColor("#746454")); painter.drawText(area, QtCore.Qt.AlignCenter, message)
            return
        equities = [float(point["equity"]) for point in points]
        drawdowns = [float(point["drawdown"]) for point in points]
        low, high = min(equities), max(equities)
        span = high - low or 1
        dd_low, dd_high = min(drawdowns), max(drawdowns)

        def path(values, minimum, value_span):
            result = QtGui.QPainterPath()
            for index, value in enumerate(values):
                x = area.left() + index * area.width() / (len(values) - 1)
                y = area.bottom() - (value - minimum) / value_span * area.height()
                (result.moveTo if index == 0 else result.lineTo)(x, y)
            return result

        painter.setPen(QtGui.QPen(QtGui.QColor("#a06b2a"), 2)); painter.drawPath(path(equities, low, span))
        painter.setPen(QtGui.QPen(QtGui.QColor("#b54c42"), 1.5)); painter.drawPath(path(drawdowns, dd_low, dd_high - dd_low or 1))
        if self._hover_index is not None and self._view_start <= self._hover_index < self._view_end:
            x = area.left() + (self._hover_index - self._view_start) * area.width() / (len(points) - 1)
            painter.setPen(QtGui.QPen(QtGui.QColor("#746454"), 1, QtCore.Qt.DashLine))
            painter.drawLine(QtCore.QPointF(x, area.top()), QtCore.QPointF(x, area.bottom()))
        painter.setPen(QtGui.QColor("#6b4c22")); painter.drawText(8, 18, "Kapanış equity" if self.closed_trade_only else "Equity")
        painter.setPen(QtGui.QColor("#b54c42")); painter.drawText(8, 35, "Kapanış DD" if self.closed_trade_only else "DD")
        painter.setPen(QtGui.QColor("#746454")); painter.drawText(area.left(), self.height() - 5, "Kaydır: yakınlaştır · Sürükle: dönem seç · +/−: yakınlaştır · Home: sıfırla")
        if self.hasFocus():
            painter.setPen(QtGui.QPen(QtGui.QColor("#a06b2a"), 2))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))


class ResultScatterChart(QtWidgets.QWidget):
    """PF–DD view; plots only measured rows and preserves task identity."""

    selected = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._points = []
        self._keyboard_index = 0
        self.setMinimumHeight(185)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAccessibleName("Sonuçların PF ve DD grafiği")
        self.setAccessibleDescription("Sol ve sağ oklarla sonuç seçin; Enter ayrıntıyı açar.")

    def set_rows(self, rows):
        self.rows = list(rows)
        self._keyboard_index = 0
        self.update()

    def _plot_area(self):
        return self.rect().adjusted(54, 22, -28, -38)

    def _hit(self, position):
        for x, y, radius, row in reversed(self._points):
            if (position.x() - x) ** 2 + (position.y() - y) ** 2 <= (radius + 5) ** 2:
                return row
        return None

    def mouseMoveEvent(self, event):
        row = self._hit(event.position())
        self.setCursor(QtCore.Qt.PointingHandCursor if row else QtCore.Qt.ArrowCursor)
        if row:
            metrics = row["metrics"]
            self.setToolTip(
                f"{row['task_key'][:12]} · {row['payload'].get('symbol', '—')}\n"
                f"PF {metrics['profit_factor']:.3f} · DD %{metrics['max_drawdown_pct']:.2f} · "
                f"{metrics.get('trades', 0)} işlem\n"
                f"Kanıt: {'doğrulanmış' if row.get('verified') else 'doğrulanmamış'}"
            )
        else:
            self.setToolTip("")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            row = self._hit(event.position())
            if row:
                self.setFocus()
                self._keyboard_index = next(
                    (index for index, point in enumerate(self._points) if point[3] is row), 0
                )
                self.update()
                self.selected.emit(row["task_id"])

    def keyPressEvent(self, event):
        if not self._points:
            return super().keyPressEvent(event)
        if event.key() in (QtCore.Qt.Key_Left, QtCore.Qt.Key_Right,
                           QtCore.Qt.Key_Home, QtCore.Qt.Key_End):
            if event.key() == QtCore.Qt.Key_Left:
                self._keyboard_index = max(0, self._keyboard_index - 1)
            elif event.key() == QtCore.Qt.Key_Right:
                self._keyboard_index = min(len(self._points) - 1, self._keyboard_index + 1)
            elif event.key() == QtCore.Qt.Key_Home:
                self._keyboard_index = 0
            else:
                self._keyboard_index = len(self._points) - 1
            row = self._points[self._keyboard_index][3]
            self.setAccessibleDescription(
                f"{row['task_key']}: PF {row['metrics']['profit_factor']:.3f}, "
                f"DD %{row['metrics']['max_drawdown_pct']:.2f}. Enter ayrıntıyı açar."
            )
            self.update()
            event.accept()
            return
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.selected.emit(self._points[self._keyboard_index][3]["task_id"])
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#fffdf8"))
        area = self._plot_area()
        painter.setPen(QtGui.QPen(QtGui.QColor("#ddc9a3"), 1))
        painter.drawRect(area)
        valid = []
        for row in self.rows:
            metrics = row.get("metrics") or {}
            pf, dd = metrics.get("profit_factor"), metrics.get("max_drawdown_pct")
            if _finite_plot_number(pf) and _finite_plot_number(dd):
                if 0 <= pf < float("inf") and 0 <= dd < float("inf"):
                    valid.append(row)
        self._points = []
        if not valid:
            painter.setPen(QtGui.QColor("#746454"))
            painter.drawText(area, QtCore.Qt.AlignCenter, "PF ve DD verisi olan sonuç yok")
            return
        max_pf = max(1.0, max(row["metrics"]["profit_factor"] for row in valid) * 1.08)
        max_dd = max(1.0, max(row["metrics"]["max_drawdown_pct"] for row in valid) * 1.08)
        for index, row in enumerate(valid):
            metrics = row["metrics"]
            x = area.left() + metrics["profit_factor"] / max_pf * area.width()
            y = area.bottom() - metrics["max_drawdown_pct"] / max_dd * area.height()
            radius = 4 + min(9, max(0, float(metrics.get("trades") or 0)) ** .5 / 2)
            color = QtGui.QColor("#477a62" if row.get("verified") else "#b9863f")
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(QtGui.QColor("#fffdf8"), 1))
            painter.drawEllipse(QtCore.QPointF(x, y), radius, radius)
            if self.hasFocus() and index == self._keyboard_index:
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor("#a06b2a"), 2))
                painter.drawEllipse(QtCore.QPointF(x, y), radius + 3, radius + 3)
            self._points.append((x, y, radius, row))
        painter.setPen(QtGui.QColor("#746454"))
        painter.drawText(area.left(), self.height() - 9, f"PF → 0–{max_pf:.2f} · Nokta boyutu: işlem sayısı")
        painter.drawText(area.right() - 225, self.height() - 9, "Yeşil: doğrulandı · Taba: doğrulanmadı")
        painter.drawText(8, 18, "DD %")


class MetricBarsChart(QtWidgets.QWidget):
    """Interactive signed bars for saved P/L aggregates; never fills absent buckets."""

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.values = [(str(label), float(value)) for label, value in (values or {}).items()
                       if _finite_plot_number(value)]
        self._bars = []
        self.setMinimumHeight(230)
        self.setMouseTracking(True)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#fffdf8"))
        self._bars = []
        if not self.values:
            painter.setPen(QtGui.QColor("#746454"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "Bu kırılım için kaydedilmiş işlem verisi yok")
            return
        area = self.rect().adjusted(44, 18, -18, -48)
        minimum = min(0, *(value for _, value in self.values))
        maximum = max(0, *(value for _, value in self.values))
        span = maximum - minimum or 1
        zero_y = area.bottom() - (0 - minimum) / span * area.height()
        painter.setPen(QtGui.QPen(QtGui.QColor("#ddc9a3"), 1))
        painter.drawLine(QtCore.QPointF(area.left(), zero_y), QtCore.QPointF(area.right(), zero_y))
        width = area.width() / max(1, len(self.values))
        for index, (label, value) in enumerate(self.values):
            x = area.left() + index * width + width * .16
            y = area.bottom() - (value - minimum) / span * area.height()
            rect = QtCore.QRectF(x, min(y, zero_y), max(2, width * .68), max(2, abs(y - zero_y)))
            painter.fillRect(rect, QtGui.QColor("#477a62" if value >= 0 else "#b54c42"))
            self._bars.append((rect, label, value))
            painter.setPen(QtGui.QColor("#746454"))
            displayed = label if len(label) <= 10 else label[:9] + "…"
            painter.drawText(QtCore.QRectF(x - width * .12, area.bottom() + 6, width, 34),
                             QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, displayed)

    def mouseMoveEvent(self, event):
        for rect, label, value in self._bars:
            if rect.adjusted(-3, -3, 3, 3).contains(event.position()):
                self.setToolTip(f"{label}: {value:,.2f}")
                return
        self.setToolTip("")


class DailyPnlCalendar(QtWidgets.QWidget):
    """Month-by-month closed-trade P/L calendar; missing days stay empty."""

    def __init__(self, daily, parent=None):
        super().__init__(parent)
        self.daily = {str(day): float(value) for day, value in (daily or {}).items()
                      if _finite_plot_number(value)}
        layout = QtWidgets.QVBoxLayout(self)
        self.month = QtWidgets.QComboBox()
        months = sorted({day[:7] for day in self.daily if QtCore.QDate.fromString(day, "yyyy-MM-dd").isValid()})
        self.month.addItems(months)
        self.month.currentTextChanged.connect(self.refresh_month)
        self.table = QtWidgets.QTableWidget(6, 7)
        self.table.setHorizontalHeaderLabels(["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(53)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.cellClicked.connect(self.show_day)
        self.detail = QtWidgets.QLabel("Bir günü seçin; boş hücreler için kayıt yok.")
        layout.addWidget(self.month)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.detail)
        self.refresh_month()

    def refresh_month(self, *_args):
        self.table.clearContents()
        first = QtCore.QDate.fromString(self.month.currentText() + "-01", "yyyy-MM-dd")
        if not first.isValid():
            self.detail.setText("Günlük kapanmış işlem P/L verisi yok.")
            return
        for day in range(1, first.daysInMonth() + 1):
            date = QtCore.QDate(first.year(), first.month(), day)
            slot = first.dayOfWeek() - 1 + day - 1
            row, column = divmod(slot, 7)
            key = date.toString("yyyy-MM-dd")
            value = self.daily.get(key)
            text = f"{day}\n{value:+,.2f}" if value is not None else str(day)
            item = QtWidgets.QTableWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, key)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            if value is not None:
                item.setBackground(QtGui.QColor("#dceddf" if value >= 0 else "#f4dcd8"))
                item.setToolTip(f"{key}: {value:+,.2f} · kapanmış işlemler")
            else:
                item.setForeground(QtGui.QColor("#aa9e8d"))
            self.table.setItem(row, column, item)
        observed = [(day, pnl) for day, pnl in self.daily.items() if day.startswith(self.month.currentText())]
        if observed:
            best = max(observed, key=lambda item: item[1])
            worst = min(observed, key=lambda item: item[1])
            self.detail.setText(f"En iyi gün: {best[0]} {best[1]:+,.2f} · En kötü gün: {worst[0]} {worst[1]:+,.2f}")

    def show_day(self, row, column):
        item = self.table.item(row, column)
        if item is None:
            return
        day = item.data(QtCore.Qt.UserRole)
        value = self.daily.get(day)
        self.detail.setText(f"{day}: {value:+,.2f} (kapanmış işlemler)" if value is not None
                            else f"{day}: kayıtlı işlem yok; sıfır varsayılmadı.")


class ResearchFunnelChart(QtWidgets.QWidget):
    """Compact logarithmic overview; exact counts remain visible at the right."""

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.setMinimumHeight(160)

    def paintEvent(self, _event):
        import math

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#fffdf8"))
        values = [self.catalog["session_tests"]["planned"], self.catalog["session_tests"]["valid"],
                  self.catalog["session_tests"]["moderate_passes"], self.catalog["heavy_tests"]["passes"]]
        labels = ["Planlanan", "Geçerli", "Orta maliyet", "Ağır maliyet"]
        maximum = math.log10(max(values) + 1)
        label_width = 118
        count_width = 95
        available = max(20, self.width() - label_width - count_width - 30)
        for index, (label, value) in enumerate(zip(labels, values)):
            y = 18 + index * 34
            painter.setPen(QtGui.QColor("#3a322a"))
            painter.drawText(12, y + 15, label)
            width = max(3, available * math.log10(value + 1) / maximum)
            painter.fillRect(QtCore.QRectF(label_width, y, width, 18),
                             QtGui.QColor("#477a62" if index == 3 else "#b9863f"))
            painter.drawText(self.width() - count_width + 6, y + 15, f"{value:,}".replace(",", "."))
        painter.setPen(QtGui.QColor("#746454"))
        painter.drawText(12, self.height() - 5, "Çubuklar logaritmik; sayılar kesindir")


def data_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TVScanStudio"
    return base / "studio.db"


class ChartPreparationJob(QtCore.QThread):
    progress = QtCore.Signal(str)
    completed = QtCore.Signal(object)

    def __init__(self, driver, store, project, slot=0):
        super().__init__()
        self.driver, self.store, self.project = driver, store, dict(project)
        self.slot = slot
        self.cancelled = threading.Event()
        self.journal_key = "automatic_preparation" if slot == 0 else f"automatic_preparation_parallel_{slot}"

    def run(self):
        project_id = self.project["id"]
        try:
            settings = self.store.settings(project_id) or {}
            journal = dict(settings.get(self.journal_key) or {})
            self.progress.emit("Bağlanıyor: bağımsız tarama grafiği hazırlanıyor…")
            result = prepare_empty_layout(self.driver, chart_targets(), journal=journal,
                persist=lambda value: self.store.save_settings(project_id, {self.journal_key: value}),
                read_targets=chart_targets, cancelled=self.cancelled.is_set)
            if not result.target_id:
                raise TradingViewError(result.message + " " + result.technical_detail)
            def guard(target):
                if self.cancelled.is_set():
                    raise TradingViewError("Hazırlık durduruldu; kayıtlı tarama grafiği korunuyor.")
                current = chart_targets()
                names = {item["id"]: self.driver.layout_name(item["id"]) for item in current}
                if worker_layout_candidates(current, names).get(target) != result.chart_id:
                    raise TradingViewError("Tarama grafiğinin bağımsız kimliği değişti; hazırlık durduruldu.")
            self.progress.emit("Bağlanıyor: ayrı özel strateji yükleniyor ve kaynak doğrulanıyor…")
            source_journal = dict((self.store.settings(project_id) or {}).get("private_source_preparation") or {})
            self.driver.load_private_source(result.target_id, self.project["pine_source"],
                journal=source_journal,
                persist=lambda value: self.store.save_settings(project_id, {"private_source_preparation": value}),
                guard=guard)
            guard(result.target_id)
            if self.slot == 0:
                self.store.save_settings(project_id, {"prepared_chart_id": result.chart_id})
            self.completed.emit({"project_id": project_id, "success": True})
        except Exception as exc:
            self.completed.emit({"project_id": project_id, "success": False, "error": str(exc)})


class StudioMainWindow(QtWidgets.QMainWindow):
    """Closing the UI must end its timers, not leave invisible preparation alive."""

    def closeEvent(self, event):
        gate = getattr(self, "before_close", None)
        if gate is not None and not gate():
            event.ignore()
            return
        callback = getattr(self, "shutdown", None)
        if callback is not None:
            callback()
        super().closeEvent(event)


class StudioWindow:
    def __init__(self, store: Store):
        self.QtWidgets = QtWidgets
        self.store = store
        self.store.recover_interrupted()
        self.supervisor = None
        self.driver = None
        self.window = StudioMainWindow()
        from .plan_jobs import PlanCountController
        self.plan_counter = PlanCountController(self.window)
        self._count_key = None
        self._count_result = None
        self._plan_parsed_inputs = []
        self._count_closing = False
        self._admission_job = None
        self._admission_result = None
        self._admission_callback = None
        self.plan_counter.result.connect(self._receive_plan_count)
        self.plan_counter.progress.connect(self._plan_count_progress)
        self.plan_counter.drained.connect(self._plan_count_drained)
        self.window.before_close = self._before_count_close
        self.window.shutdown = self.shutdown
        self.window.setWindowTitle("TV Scan Studio")
        self.window.setWindowIcon(QtGui.QIcon(str(Path(__file__).parent / "assets" / "app-icon.ico")))
        self.window.resize(1240, 780)
        self._last_dashboard_counts = None
        self._notified_worker_errors = set()
        self._notified_worker_restarts = set()
        self._safe_worker_targets = set()  # Only explicitly claimed independent layouts in this session.
        self._safe_worker_layouts = {}  # Explicitly claimed, unique saved layouts: target -> chart ID.
        self._preparing = False
        self._saved_project_id = None
        self._wheel_filter = SafeWheelFilter(self.window)
        QtWidgets.QApplication.instance().installEventFilter(self._wheel_filter)
        self.tray = QtWidgets.QSystemTrayIcon(
            self.window.windowIcon(), self.window
        )
        self.tray.setToolTip("TV Scan Studio")
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        root = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._rail(), 0)
        self.pages = QtWidgets.QStackedWidget()
        self.pages.setMinimumSize(0, 0)
        self.pages.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.dashboard = self._dashboard_page()
        self.new_project = self._new_project_page()
        self.scan_setup = self._scan_setup_page()
        self.workers_page = self._workers_page()
        self.results_page = self._results_page()
        self.research_page = self._research_page()
        self.settings_page = self._settings_page()
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.new_project)
        self.pages.addWidget(self.scan_setup)
        self.pages.addWidget(self.workers_page)
        self.pages.addWidget(self.results_page)
        self.pages.addWidget(self.research_page)
        self.pages.addWidget(self.settings_page)
        self._simplify_navigation()
        layout.addWidget(self.pages, 1)
        self.window.setCentralWidget(root)
        self.result_detail_dock = QtWidgets.QDockWidget("Preset ayrıntısı", self.window)
        self.result_detail_dock.setObjectName("resultDetailDock")
        self.result_detail_dock.setAllowedAreas(QtCore.Qt.RightDockWidgetArea)
        self.result_detail_dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable | QtWidgets.QDockWidget.DockWidgetFloatable
        )
        self.result_detail_dock.setMinimumWidth(360)
        self.window.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.result_detail_dock)
        self.result_detail_dock.hide()
        self._open_result_task_id = None
        self.result_detail_dock.visibilityChanged.connect(
            lambda visible: None if visible else setattr(self, "_open_result_task_id", None)
        )
        self.worker_timer = QtCore.QTimer(self.window)
        self.worker_timer.timeout.connect(self.refresh_worker_states)
        self.worker_timer.start(1000)
        self.refresh_dashboard()
        self.refresh_project_selectors()
        self._register_context_help()
        self._show_page(1)

    def _register_context_help(self):
        from .help_system import HelpRegistry, HelpSpec, TourSpec
        self.help_registry = HelpRegistry(self.window, self.store.app_settings, self.store.save_app_settings)
        entries = [
            ("strategy.select", self.strategy_list, "Kayıtlı stratejiler", "Kayıtlı stratejiyi açar; yeni tarama başlatmaz.", "Yeni strateji ekle seçeneğiyle kod yapıştırabilir veya kayıtlı bir stratejiyi inceleyebilirsin."),
            ("strategy.source", self.pine_source, "Strateji kodu", "Pine strategy kodunu okur ve ayarlarını analiz eder.", "TradingView'deki stratejinin tam kaynak kodunu yapıştır. Kodun analiz edilmesi grafiğe yüklendiği veya test edildiği anlamına gelmez."),
            ("strategy.name", self.project_name, "Strateji adı", "Stratejiyi listede tanıyacağın adı belirler.", "Bu ad yerel kayda aittir; TradingView scriptinin adını değiştirmez."),
            ("strategy.save", self.strategy_save_button, "Stratejiyi kaydet", "Kodu yerel kayda alır; aynı kaynak için yeni kopya oluşturmaz.", "Kaydetmek TradingView'de script yayımlamaz veya tarama başlatmaz. Ayrı bir kayıt istiyorsan Kopya oluştur seçeneğini kullan."),
            ("scan.symbols", self.symbols, "Semboller", "Test edilecek piyasaları belirler.", "Seç düğmesiyle sembol ara. Birden fazla sembol seçmek toplam test sayısını artırır; grafikteki mevcut sembol seçim yerine geçmez."),
            ("scan.timeframes", self.timeframes, "Zaman dilimleri", "Her sembolün hangi mum sürelerinde test edileceğini belirler.", "Seç düğmesinden örneğin 15 dakika ekle. Her seçili zaman dilimi ayrı testler üretir."),
            ("scan.parallel", self.parallel_count, "Paralel tarama", "Aynı anda çalışan bağımsız tarama grafiklerinin sayısıdır (1–16).", "Daha fazla grafik bellek tüketimini artırır ve her zaman daha hızlı değildir. Kaynakları ölç bir öneri verir; gerçek hızı tamamlanan test/saat göstergesiyle karşılaştır."),
            ("scan.start", self.enqueue_plan_button, "Hazırla ve başlat", "Planı doğrular, ayrı grafikleri hazırlar ve onayından sonra taramayı başlatır.", "Kişisel grafikler tarama için kullanılmaz. Hazırlık başarılı olmadan veya gerekli onaylar alınmadan görevler başlamaz."),
            ("results.progress", self.run_progress, "Tarama ilerlemesi", "Tamamlanan testleri ve devam eden işlemi gösterir.", "Durduruluyor durumunda mevcut işlem güvenli noktaya ulaşana kadar beklenir; yeni görev alınmaz."),
            ("results.speed", self.run_performance, "Tarama hızı", "Aynı taramanın doğrulanmış test hızını ve aktif grafik sayısını gösterir.", "Son 5 dakika ve çalışma ortalaması yalnız bu taramanın kaynak kanıtlı sonuçlarından hesaplanır. En az 5 sonuç ve 60 saniye aktif test süresi gerekir. Paralel test süreleri iki kez sayılmaz; testler arasındaki duraklamalar çıkarılır. Kesinti süresi kanıtlanamıyorsa ölçüm gösterilmez. ETA yalnız karşılaştırılabilir sembol, zaman dilimi, dönem ve maliyetlerde verilir; garanti değildir."),
        ]
        for feature, target, title, short, detail in entries:
            availability = None
            if target is self.enqueue_plan_button:
                availability = lambda: (None if self.enqueue_plan_button.isEnabled() else
                                       "Plan veya grafik hazırlığı tamamlanmadı. Görünür hata açıklamasını kontrol et; Eksik alana git düğmesini kullan.")
            self.help_registry.register(HelpSpec(feature, 1, title, short, detail, target, availability))
        parallel_help = self.help_registry.specs["scan.parallel"]
        self.help_registry.register_tour(TourSpec("parallel", 1, (
            (self.parallel_count, parallel_help.title, parallel_help.detail +
             "\n\nTarama çalışırken hızı Sonuçlar ekranından izleyebilirsin. Bu rehber tarama başlatmaz.", None),
        )))
        # Only show this feature guide when the user actually enters its control,
        # not merely because the advanced option exists on a screen.
        self.help_registry.bind_first_use(self.parallel_count, "parallel")
        for key, target, title, short, detail in (
            ("method", self.scan_method, "Tarama yöntemi", "Tam, örneklemeli veya kaba→ince taramayı seçer.", "Tam ve kaba aşamada zorunlu test sınırı yoktur. Kaba aşamanın değerlerini sen seçersin; tamamlanınca Sonuçlar ekranında adayları seçip ayrıntılı değerleri ayrıca onaylarsın. Örnekleme yalnız seçilen alt kümeyi dener; denenmeyen değerler sonuç değildir."),
            ("budget", self.sample_budget, "Örnekleme bütçesi", "Örneklemede en fazla kaç test seçileceğini belirler.", "Pozitif tam sayı gir. Bütçe tüm olası testlerden büyükse bütün testler seçilir; bu alan tam taramayı sınırlamaz."),
            ("seed", self.sample_seed, "Örnekleme tohumu", "Aynı plan için aynı test alt kümesini yeniden seçmeyi sağlar.", "Tam sayı gir. Kaynak, semboller veya değer listesi değişirse aynı tohum farklı testler seçebilir; aynı sonuç garantisi değildir."),
            ("guide", self.sampling_guide, "Yöntem rehberi", "Tarama yöntemi rehberini yeniden açar.", "Rehber görev oluşturmaz veya tarama başlatmaz."),
            ("detach", self.refinement_detach, "Aday bağlantısını kaldır", "Düzenlenen planı bağımsız tarama olarak kullanmayı seçer.", "Kaba adaylara bağlı onaylı ayrıntılı kapsamı değiştiriyorsan önce bu bağlantıyı kaldır. Geçmiş koşular silinmez; yeni tarama artık bu adayların onaylı ayrıntılı aşaması sayılmaz."),
        ):
            availability = (lambda: None if self.scan_method.currentData() == "sample" else
                            "Bu alan yalnız Tohumlu örnekleme seçildiğinde kullanılır.") if key in {"budget", "seed"} else None
            self.help_registry.register(HelpSpec("sampling." + key, 1, title, short, detail, target, availability))
        self.help_registry.register_tour(TourSpec("sampling", 1, (
            (self.scan_method, "Yöntemi seç", "Varsayılan tam tarama bütün değerleri dener. Örnekleme yalnız bütçeye uygun alt kümeyi dener.", None),
            (self.sample_budget, "Test bütçesini belirle", "Örnekleme için pozitif tam sayı gir. Tam taramada bu alan kullanılmaz; zorunlu 500 sınırı yoktur.", None),
            (self.sample_seed, "Seçimi yeniden üret", "Aynı plan ve tohum aynı testleri seçer. Denenmeyen ayarlar sonuç gibi gösterilmez. Rehber tarama başlatmaz.", None),
        )))
        sampling_active = lambda: self.scan_method.currentData() == "sample"
        for target in (self.scan_method, self.sample_budget, self.sample_seed):
            self.help_registry.bind_first_use(target, "sampling", when=sampling_active)
        self.scan_method.currentIndexChanged.connect(lambda *_:
            self.help_registry.start_tour("sampling", automatic=True) if sampling_active() else None)
        self.sampling_guide.clicked.connect(lambda: self.help_registry.start_tour("sampling"))
        self.help_registry.register_tour(TourSpec("coarse", 1, (
            (self.scan_method, "Kaba aşamayı seç", "Değer aralıklarını kendin belirle. Kaba aşama bütün seçili kombinasyonları dener; otomatik kazanan veya 500 sınırı yoktur.", None),
            (self.scan_method, "Sonuçlardan adayları seç", "Kaba koşu tamamlanınca aynı koşullarda doğrulanmış adayları Sonuçlar ekranında seç ve Adaylardan ayrıntılı tara kullan. Ayrıntılı değerler ayrıca onaylanır; rehber test başlatmaz.", None),
        )))
        self.scan_method.currentIndexChanged.connect(lambda *_: self.help_registry.start_tour("coarse", automatic=True)
            if self.scan_method.currentData() == "coarse" else None)
        self.constraint_editor.register_help(self.help_registry)
        self.run_choice.register_help(self.help_registry)
        self.run_choice.changed.connect(self.preview_plan)
        self.help_registry.register(HelpSpec("scan.cancel_count", 1, "Sayımı iptal et",
            "Arka plandaki kombinasyon sayımını iptal eder; kayıtlı görevleri değiştirmez.",
            "İptal tamamlanmadan yeni sayım sonucu gösterilmez. Yeniden saymak için Sayımı yeniden dene düğmesini kullan.",
            self.cancel_count_button))
        self.help_registry.register(HelpSpec("scan.cancel_queue", 1, "Kuyruk hazırlığını iptal et",
            "Görev kuyruğu oluşturulmasını iptal eder; bu işlemdeki görevler ve ayarlar geri alınır.",
            "İlerleme henüz kaydedilmemiş görevleri gösterir. Tamamlandı mesajından sonra kuyruk kalıcıdır; taramayı durdurmak için Durdur kullanılır.",
            self.cancel_queue_button))
        from .help_catalog import register_scan_results_help, register_settings_help, register_research_help
        register_scan_results_help(self)
        register_settings_help(self)
        register_research_help(self)
        from .help_catalog import register_preparation_help
        register_preparation_help(self)
        from .help_catalog import register_main_actions_help
        register_main_actions_help(self)

    def _rail(self):
        Q = self.QtWidgets
        rail = Q.QFrame(objectName="rail")
        rail.setFixedWidth(180)
        box = Q.QVBoxLayout(rail)
        box.setContentsMargins(0, 0, 0, 16)
        box.addWidget(Q.QLabel("TV Scan Studio", objectName="brand"))
        box.addWidget(Q.QLabel("Yerel strateji laboratuvarı", objectName="tagline"))
        group = Q.QButtonGroup(rail)
        group.setExclusive(True)
        self.nav_group = group
        for index, label in ((1, "Stratejiler"), (2, "Tarama"), (4, "Sonuçlar")):
            button = Q.QPushButton(label)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked=False, i=index: self._show_page(i))
            group.addButton(button, index)
            box.addWidget(button)
        box.addStretch()
        settings = Q.QPushButton("Ayarlar")
        self.settings_navigation_button = settings
        settings.clicked.connect(lambda: self._show_auxiliary(6, "Genel ayarlar"))
        box.addWidget(settings)
        privacy = Q.QLabel("Veriler yalnızca bu bilgisayarda tutulur", objectName="tagline")
        privacy.setWordWrap(True)
        box.addWidget(privacy)
        return rail

    def _show_auxiliary(self, index, title):
        """Keep legacy tools available without adding main navigation screens."""
        page = self.pages.widget(index)
        self.pages.removeWidget(page)
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle(title)
        dialog.resize(1100, 740)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(page)
        # Stacked pages retain their explicit hidden state when reparented.
        page.show()
        close = QtWidgets.QPushButton("Kapat")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        scope = None
        if index in (0, 3, 5, 6):
            from .help_catalog import register_settings_help, register_research_help, register_preparation_help, register_dashboard_help
            from .help_system import HelpSpec, TourSpec
            scope = self.help_registry.child_scope(dialog)
            dialog.help_registry = scope
            if index == 0:
                register_dashboard_help(self, scope)
                key = "management"
                targets = (self.dashboard_backup_button, self.restore_backup_button)
            elif index == 3:
                register_preparation_help(self, scope)
                key = "preparation"
                targets = (self.tv_executable, self.worker_status)
            elif index == 6:
                register_settings_help(self, scope)
                key = "settings"
                targets = (self.settings_save_button, self.archive_import_button)
            else:
                register_research_help(self, scope)
                key = "research"
                targets = (self.research_table, self.research_status)
            scope.register_tour(TourSpec(key, 1, tuple(
                (target, scope.resolve(target).title, scope.resolve(target).detail, None)
                for target in targets)))
            guide = QtWidgets.QPushButton("Bu pencerenin rehberi (?)")
            guide.clicked.connect(lambda: scope.start_tour(key))
            layout.addWidget(guide)
            scope.register(HelpSpec(key + ".guide", 1, "Pencere rehberi",
                                    "Bu pencerenin adım adım rehberini yeniden açar.",
                                    "Rehber ayar kaydetmez, arşiv içe aktarmaz veya test başlatmaz.", guide))
            scope.register(HelpSpec(key + ".close", 1, "Pencereyi kapat",
                                    "Bu pencereyi kapatır.", "Kapatmak taramayı durdurmaz veya kayıtları silmez.", close))
            QtCore.QTimer.singleShot(0, scope, lambda: scope.start_tour(key, automatic=True))
        try:
            dialog.exec()
        finally:
            if scope is not None:
                scope.finish_scope()
                # The page is about to return to the main window; restore its
                # primary contextual-help filters rather than retaining a
                # hidden dialog's F1 handlers.
                for target in tuple(scope._targets):
                    target.removeEventFilter(scope)
            layout.removeWidget(page)
            page.setParent(self.pages)
            self.pages.insertWidget(index, page)
            page.hide()
            dialog.deleteLater()

    def _simplify_navigation(self):
        self.tv_executable.setText(str(self.store.app_settings().get("tradingview_executable", "")))
        self.tv_executable.editingFinished.connect(lambda: self.store.save_app_settings(
            {"tradingview_executable": self.tv_executable.text().strip()}))
        self.new_tab_count.setValue(1)
        scan_layout = self.scan_setup.widget().layout() if isinstance(self.scan_setup, QtWidgets.QScrollArea) else self.scan_setup.layout()
        parallel = QtWidgets.QHBoxLayout()
        parallel.addWidget(QtWidgets.QLabel("Paralel tarama grafiği"))
        self.parallel_count = QtWidgets.QSpinBox()
        self.parallel_count.setRange(1, 16)
        self.parallel_count.setValue(int(self.store.app_settings().get("parallel_graphs", 1)))
        self.parallel_count.setToolTip("Her grafik bağımsız hazırlanır ve kaynağı doğrulanır. Daha fazla grafik her zaman daha hızlı değildir.")
        self.parallel_count.valueChanged.connect(lambda value: self.store.save_app_settings({"parallel_graphs": value}))
        parallel.addWidget(self.parallel_count)
        self.parallel_recommendation = QtWidgets.QLabel("Kaynak önerisi henüz ölçülmedi.")
        parallel.addWidget(self.parallel_recommendation, 1)
        measure = QtWidgets.QPushButton("Kaynakları ölç")
        self.parallel_measure_button = measure
        measure.clicked.connect(self.measure_parallel_resources)
        parallel.addWidget(measure)
        scan_layout.insertLayout(1, parallel)
        # Expose existing projects by name on the first screen.
        layout = (self.new_project.widget().layout() if isinstance(self.new_project, QtWidgets.QScrollArea)
                  else self.new_project.layout())
        self.strategy_list = QtWidgets.QComboBox()
        self.strategy_list.setAccessibleName("Kayıtlı stratejiler")
        self.strategy_list.addItem("Yeni strateji ekle", None)
        for project in self.store.projects():
            self.strategy_list.addItem(project["name"], project["id"])
        self.strategy_list.activated.connect(self.open_saved_strategy)
        layout.insertWidget(1, self.strategy_list)
        self.prepare_saved_button = QtWidgets.QPushButton("Taramayı hazırla", objectName="primary")
        self.prepare_saved_button.setEnabled(False)
        self.prepare_saved_button.clicked.connect(self.prepare_saved_strategy)
        layout.addWidget(self.prepare_saved_button)
        result_layout = (self.results_page.widget().layout() if isinstance(self.results_page, QtWidgets.QScrollArea)
                         else self.results_page.layout())
        self.run_progress = QtWidgets.QLabel("Henüz tarama başlatılmadı.")
        self.run_progress.setWordWrap(True)
        result_layout.insertWidget(1, self.run_progress)
        self.run_performance = QtWidgets.QLabel("Hız: ölçüm bekleniyor · aktif grafik: 0")
        self.run_performance.setWordWrap(True)
        result_layout.insertWidget(2, self.run_performance)
        stop = QtWidgets.QPushButton("Taramayı durdur")
        self.results_stop_button = stop
        stop.clicked.connect(self.stop_workers)
        result_layout.insertWidget(2, stop)
        utilities = QtWidgets.QHBoxLayout()
        presets = QtWidgets.QPushButton("Kaydettiğim presetler")
        self.saved_presets_button = presets
        presets.clicked.connect(self.show_saved_presets)
        utilities.addWidget(presets)
        tasks_backup = QtWidgets.QPushButton("Görevler ve yedekleme")
        self.tasks_backup_button = tasks_backup
        tasks_backup.clicked.connect(self.show_tasks_backup)
        utilities.addWidget(tasks_backup)
        historical = QtWidgets.QPushButton("Geçmiş taramalar")
        self.historical_scans_button = historical
        historical.clicked.connect(self.show_historical_scans)
        utilities.addWidget(historical)
        result_layout.addLayout(utilities)
        self.run_history_button = QtWidgets.QPushButton("Koşu ve deneme geçmişi")
        self.run_history_button.clicked.connect(self.show_run_history)
        result_layout.addWidget(self.run_history_button)

    def show_run_history(self):
        from .run_browser import RunBrowser
        dialog = RunBrowser(self.store, parent=self.window, help_registry=self.help_registry)
        try:
            dialog.exec()
        finally:
            dialog.scope.finish_scope()
            dialog.deleteLater()

    def show_support_package(self):
        from .support_dialog import SupportDialog
        if getattr(self, "_support_dialog", None) is not None:
            return
        dialog = SupportDialog(self.store, parent=self.window, help_registry=self.help_registry)
        self._support_dialog = dialog
        try:
            dialog.exec()
        finally:
            dialog.scope.finish_scope()
            self._support_dialog = None
            dialog.deleteLater()
            if self._count_closing:
                QtCore.QTimer.singleShot(0, self.window, self.window.close)

    def show_historical_scans(self):
        from .historical_dialog import HistoricalDialog
        tour = getattr(self, "guided_tour", None)
        if tour is not None:
            tour.finish()
        HistoricalDialog(self.store, self.window, help_coordinator=self.help_registry).exec()

    def show_tasks_backup(self):
        """A direct task browser, independent of hidden dashboard stack pages."""
        active_tour = getattr(self, "guided_tour", None)
        if active_tour is not None:
            active_tour.finish()
        Q = QtWidgets
        dialog = Q.QDialog(self.window)
        dialog.setWindowTitle("Görevler ve yedekleme")
        dialog.resize(900, 620)
        layout = Q.QVBoxLayout(dialog)
        introduction = Q.QLabel("Tarama görevlerini incele veya projelerini, sonuçlarını, ayarlarını ve kaydettiğin presetleri yedekle.")
        introduction.setWordWrap(True); layout.addWidget(introduction)
        controls = Q.QHBoxLayout()
        projects = Q.QComboBox(); projects.setObjectName("backupTaskProject")
        projects.addItem("Tüm stratejiler", None)
        for project in self.store.projects():
            projects.addItem(project["name"], project["id"])
        states = Q.QComboBox(); states.setObjectName("backupTaskState")
        states.addItem("Tüm görevler", None)
        for key, label in (("pending", "Bekleyen"), ("running", "Çalışan"), ("done", "Tamamlanan"),
                           ("failed", "Hata"), ("manual_review", "İnceleme gerekli"), ("cancelled", "İptal edilen")):
            states.addItem(label, key)
        refresh = Q.QPushButton("Yenile")
        for widget in (projects, states, refresh): controls.addWidget(widget)
        layout.addLayout(controls)
        summary = Q.QLabel(); summary.setWordWrap(True); layout.addWidget(summary)
        table = Q.QTableWidget(0, 5); table.setObjectName("backupTaskTable")
        table.setHorizontalHeaderLabels(["Strateji", "Durum", "Sembol", "Zaman dilimi", "Ayar sayısı"])
        table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(Q.QHeaderView.Stretch)
        layout.addWidget(table, 1)
        status = Q.QLabel(); status.setWordWrap(True); status.setObjectName("backupOperationStatus")
        layout.addWidget(status)
        def reload():
            total, rows = self.store.task_summaries(states.currentData(), project_id=projects.currentData())
            labels = {states.itemData(i): states.itemText(i) for i in range(states.count())}
            summary.setText(f"{total:,} görev · son {len(rows):,} kayıt gösteriliyor." if total else
                            "Bu seçimde görev yok. Tarama ekranında Hazırla ve başlat ile görev oluşturabilirsin.")
            table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                payload = row["payload"]
                values = (row["project"], labels.get(row["status"], row["status"]), payload.get("symbol", "—"),
                          self._timeframe_label(payload.get("timeframe", "")), len(payload.get("inputs") or {}))
                for column, value in enumerate(values):
                    item = Q.QTableWidgetItem(str(value))
                    item.setToolTip(f'Test #{row["task_id"]}')
                    table.setItem(index, column, item)
        projects.currentIndexChanged.connect(reload); states.currentIndexChanged.connect(reload)
        refresh.clicked.connect(reload)
        from .backup_selection import BackupSelection
        attachment_toggle = DisclosureButton("Yedeğe ek dosya seç (isteğe bağlı)")
        attachments = BackupSelection(dialog)
        attachments.hide()
        attachment_toggle.toggled.connect(attachments.setVisible)
        layout.addWidget(attachment_toggle)
        layout.addWidget(attachments)
        backup_actions = Q.QHBoxLayout()
        def backup_operation(operation):
            operation()
            status.setText(self.dashboard_status.text())
        backup = Q.QPushButton("Yedek oluştur"); backup.setObjectName("createTaskBackup")
        backup.clicked.connect(lambda: backup_operation(lambda: self.create_portable_backup(attachments=attachments.items())))
        restore = Q.QPushButton("Yedeği yeni dosyaya aç"); restore.setObjectName("restoreTaskBackup")
        restore.clicked.connect(lambda: backup_operation(self.restore_portable_backup))
        restore.setToolTip("Mevcut veritabanına dokunmaz; ayrı bir dosya oluşturur.")
        backup_actions.addWidget(backup); backup_actions.addWidget(restore)
        layout.addLayout(backup_actions)
        advanced = DisclosureButton("Gelişmiş proje yönetimi")
        management = Q.QPushButton("Öncelik, iptal ve yeniden deneme araçlarını aç")
        management.clicked.connect(lambda: self._show_auxiliary(0, "Proje yönetimi"))
        management.hide()
        advanced.toggled.connect(management.setVisible)
        layout.addWidget(advanced); layout.addWidget(management)
        close = Q.QPushButton("Kapat"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        from .help_catalog import register_task_dialog_help
        from .help_system import HelpSpec
        scope = self.help_registry.child_scope(dialog)
        dialog.help_registry = scope
        attachments.register_help(scope)
        scope.register(HelpSpec("backup.files.toggle", 1, "Yedeğe ek dosyalar",
                                "Arşiv, rapor ve kanıt dosyalarını seçebileceğin bölümü açar.",
                                "Bu bölüm isteğe bağlıdır. Ek kaynak dosyalarını sen seçersin; seçilen kayıtlı arşivin doğrulanmış manifesti de birlikte yedeklenir.", attachment_toggle))
        register_task_dialog_help(scope, dict(projects=projects, states=states, refresh=refresh,
                                  summary=summary, table=table, status=status, backup=backup,
                                  restore=restore, advanced=advanced, management=management, close=close))
        guide = Q.QPushButton("Görevler ve yedekleme rehberi (?)")
        guide.clicked.connect(lambda: scope.start_tour("tasks_backup"))
        layout.addWidget(guide)
        scope.register(HelpSpec("tasks.guide", 1, "Görevler ve yedekleme rehberi",
                                "Bu pencerenin adım adım rehberini yeniden açar.",
                                "Rehber filtre, yedek ve geri yükleme araçlarını gösterir; dosya işlemi veya tarama yapmaz.", guide))
        QtCore.QTimer.singleShot(0, scope, lambda: scope.start_tour("tasks_backup", automatic=True))
        reload()
        dialog.exec()

    def save_local_preset(self, task_id):
        project_id = self.result_project.currentData()
        name, accepted = self._ask_text_with_help("preset_name")
        if not accepted:
            return
        try:
            self.store.save_result_preset(project_id, task_id, name)
        except ValueError as error:
            QtWidgets.QMessageBox.warning(self.window, "Preset kaydedilemedi", str(error))
            return
        QtWidgets.QMessageBox.information(self.window, "Preset kaydedildi", "Testin ayarları Kaydettiğim presetler listesine kaydedildi. Aynı test tekrar kaydedilirse kopya oluşmaz.")

    def show_saved_presets(self):
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Kaydettiğim presetler")
        dialog.resize(760, 560)
        layout = QtWidgets.QVBoxLayout(dialog)
        presets = self.store.saved_presets()
        note = QtWidgets.QLabel("Preset, bir testte kullanılan ayarların kaydıdır; gelecekte kâr garantisi değildir." if presets else
            "Henüz preset kaydetmedin. Sonuçlarda bir testi açıp ‘Bu testi preset olarak kaydet’ düğmesine bas.")
        note.setWordWrap(True); layout.addWidget(note)
        listing = QtWidgets.QListWidget()
        for preset in presets:
            snapshot = preset["snapshot"]
            payload = snapshot["result"]["payload"]
            item = QtWidgets.QListWidgetItem(f'{preset["name"]} — {snapshot["project_name"]} — {payload.get("symbol", "")} / {self._timeframe_label(payload.get("timeframe", ""))}')
            listing.addItem(item)
        layout.addWidget(listing)
        details = QtWidgets.QPlainTextEdit(); details.setReadOnly(True)
        layout.addWidget(details)
        reuse = QtWidgets.QPushButton("Seçili presetin ayarlarını taramaya taşı")
        reuse.setEnabled(False)
        def show_details(index):
            if index < 0:
                reuse.setEnabled(False)
                details.clear()
                return
            snapshot = presets[index]["snapshot"]
            row = snapshot["result"]
            definitions = parse_strategy_inputs(snapshot.get("pine_source", ""))
            names = {f"in_{i}": item.title for i, item in enumerate(definitions)}
            lines = [f'Test #{row["task_id"]} · {row["classification"]}',
                     "Ayar adları kayıt anındaki proje kodundandır; testin kaynak doğrulaması teknik kanıtta saklanır.", ""]
            lines.extend(f'{names.get(key, "Tanımı bulunamayan ayar")}: {value}' for key, value in row["payload"].get("inputs", {}).items())
            lines.extend(["", "Tarih, maliyet ve kanıt (değiştirilmemiş kayıt):", json.dumps(
                {"date_range": row["payload"].get("date_range"), "costs": row["payload"].get("costs"),
                 "metrics": row["metrics"], "evidence": row.get("evidence", {})}, ensure_ascii=False, indent=2)])
            details.setPlainText("\n".join(lines)); reuse.setEnabled(True)
        listing.currentRowChanged.connect(show_details)
        def use_selected():
            if listing.currentRow() >= 0 and self.apply_saved_preset(presets[listing.currentRow()]):
                dialog.accept()
        reuse.clicked.connect(use_selected); layout.addWidget(reuse)
        close = QtWidgets.QPushButton("Kapat"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        if presets:
            listing.setCurrentRow(0)
        from .help_catalog import register_preset_help
        from .help_system import HelpSpec
        help_scope = self.help_registry.child_scope(dialog)
        dialog.help_registry = help_scope
        register_preset_help(help_scope, dict(note=note, listing=listing, details=details, reuse=reuse, close=close))
        guide = QtWidgets.QPushButton("Preset rehberi (?)")
        guide.clicked.connect(lambda: help_scope.start_tour("presets"))
        layout.addWidget(guide)
        help_scope.register(HelpSpec("presets.guide", 1, "Preset rehberi",
                                     "Kayıtlı ayarların kullanım rehberini yeniden açar.",
                                     "Rehber ayar taşımaz, görev oluşturmaz veya tarama başlatmaz.", guide))
        QtCore.QTimer.singleShot(0, help_scope, lambda: help_scope.start_tour("presets", automatic=True))
        dialog.exec()

    def apply_saved_preset(self, preset):
        snapshot = preset["snapshot"]
        project = self.store.project(preset["project_id"])
        if not project or project["pine_hash"] != snapshot["pine_hash"]:
            QtWidgets.QMessageBox.warning(self.window, "Preset uygulanamadı", "Strateji kodu değişmiş veya proje bulunamıyor. Eski ayarlar farklı bir kaynağa otomatik uygulanmaz.")
            return False
        answer = QtWidgets.QMessageBox.question(self.window, "Ayarları taramaya taşı",
            "Bu presetin Pine ayarları, sembolü ve zaman dilimi Tarama ekranına taşınacak.\n"
            "Tarih, maliyetler ve başarı ölçütleri değiştirilmez; yeniden test etmeden önce bunları ayrıca kontrol et.\n"
            "Bu işlem görev oluşturmaz ve tarama başlatmaz. Devam edilsin mi?")
        if answer != QtWidgets.QMessageBox.Yes:
            return False
        payload = snapshot["result"]["payload"]
        values = payload.get("inputs") or {}
        self.store.save_settings(project["id"], {"symbols": [payload["symbol"]],
            "timeframes": [str(payload["timeframe"])], "input_values": {key: [value] for key, value in values.items()},
            "input_ui": {key: {"decision": "Tara", "values": [value]} for key, value in values.items()}})
        self._show_page(2)
        self.plan_project.setCurrentIndex(self.plan_project.findData(project["id"]))
        self.load_plan_inputs()
        return True

    def import_research_archive(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.window, "Araştırma arşivi içe aktar", "", "Araştırma kataloğu (*.json)")
        if not path:
            return
        from .research import read_imported_catalog
        try:
            catalog = read_imported_catalog(Path(path))
        except (OSError, ValueError, TypeError, KeyError) as error:
            QtWidgets.QMessageBox.warning(self.window, "Arşiv açılamadı", "Geçerli TV Scan araştırma kataloğu gerekli.\n" + str(error))
            return
        self.store.save_app_settings({"imported_research_catalog": catalog})
        old = self.pages.widget(5)
        self.help_registry.remove_tree(old)
        self.pages.removeWidget(old)
        self.research_page = self._research_page()
        self.pages.insertWidget(5, self.research_page)
        from .help_catalog import register_research_help
        register_research_help(self)
        old.deleteLater()
        self.refresh_project_selectors()
        self.archive_open_button.setEnabled(True)
        self.settings_status.setText("Araştırma arşivi içe aktarıldı. İçe aktarma sonuçları yeniden doğrulamaz; kendi presetlerinle karıştırılmaz.")

    def open_saved_strategy(self):
        project_id = self.strategy_list.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        self._saved_project_id = project_id
        self.project_name.setText(project["name"] if project else "")
        self.pine_source.setPlainText(project["pine_source"] if project else "")
        self.prepare_saved_button.setEnabled(project is not None)

    def prepare_saved_strategy(self):
        self.refresh_project_selectors()
        self.plan_project.setCurrentIndex(self.plan_project.findData(self._saved_project_id))
        self._show_page(2)

    def _ask_text_with_help(self, key, *, title=None, text=""):
        from .text_prompt import ask_text
        return ask_text(self.window, self.help_registry, key, title=title, text=text)

    def _configure_selection_help(self, dialog, layout, key, entries, buttons):
        """Scoped read-only guidance for explicit selection controls."""
        from .help_system import HelpSpec, TourSpec
        scope = self.help_registry.child_scope(dialog)
        dialog.help_registry = scope
        for name, target, title, short, detail in entries:
            scope.register(HelpSpec(f"selection.{key}.{name}", 1, title, short, detail, target))
        for role, name, title, short, detail in (
            (QtWidgets.QDialogButtonBox.Ok, "apply", "Seçimi uygula",
             "Bu penceredeki seçimi tarama planına aktarır.",
             "Yalnız bu pencerenin alanları onaylanır. Planın geçerliliği ayrıca kontrol edilir; görev veya test kendiliğinden başlamaz."),
            (QtWidgets.QDialogButtonBox.Cancel, "cancel", "Değişiklikten vazgeç",
             "Pencereyi mevcut plan değerlerini değiştirmeden kapatır.",
             "Bu pencerede yaptığın düzenlemeler uygulanmaz. Kayıtlı stratejiler, görevler ve sonuçlar korunur."),
        ):
            scope.register(HelpSpec(f"selection.{key}.{name}", 1, title, short, detail, buttons.button(role)))
        feature = "selection." + key
        scope.register_tour(TourSpec(feature, 1, tuple(
            (target, title, detail, None) for _name, target, title, _short, detail in entries)))
        guide = QtWidgets.QPushButton("Bu seçimin rehberi (?)")
        guide.clicked.connect(lambda: scope.start_tour(feature))
        if isinstance(layout, QtWidgets.QFormLayout):
            layout.addRow(guide)
        else:
            layout.addWidget(guide)
        scope.register(HelpSpec(feature + ".guide", 1, "Seçim rehberi",
                               "Bu seçimin adım adım açıklamasını yeniden açar.",
                               "Rehber seçim yapmaz, planı uygulamaz veya tarama başlatmaz.", guide))
        QtCore.QTimer.singleShot(0, scope, lambda: scope.start_tour(feature, automatic=True))
        return scope

    def _configure_readonly_dialog_help(self, dialog, layout, key, entries, close):
        """Register explicit viewer help without introducing data operations."""
        from .help_system import HelpSpec, TourSpec
        scope = self.help_registry.child_scope(dialog)
        dialog.help_registry = scope
        for name, target, title, short, detail in entries:
            scope.register(HelpSpec(f"viewer.{key}.{name}", 1, title, short, detail, target))
        feature = "viewer." + key
        scope.register(HelpSpec(feature + ".close", 1, "Pencereyi kapat",
                               "Yalnız bu inceleme penceresini kapatır.",
                               "Görevler ve sonuçlar korunur; pencereyi kapatmak taramayı durdurmaz.", close))
        scope.register_tour(TourSpec(feature, 1, tuple(
            (target, title, detail, None) for _name, target, title, _short, detail in entries)))
        guide = QtWidgets.QPushButton("Bu pencerenin rehberi (?)")
        guide.clicked.connect(lambda: scope.start_tour(feature))
        layout.addWidget(guide)
        scope.register(HelpSpec(feature + ".guide", 1, "İnceleme rehberi",
                               "Bu pencerenin açıklamalarını yeniden açar.",
                               "Rehber kayıt değiştirmez, görev oluşturmaz veya doğrulama başlatmaz.", guide))
        QtCore.QTimer.singleShot(0, scope, lambda: scope.start_tour(feature, automatic=True))
        return scope

    def choose_timeframes(self):
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Zaman dilimleri")
        box = QtWidgets.QVBoxLayout(dialog)
        selected = set(self._timeframe_codes(self.timeframes.text()))
        choices = []
        for code, label in (("1", "1 dakika"), ("5", "5 dakika"), ("15", "15 dakika"),
                            ("30", "30 dakika"), ("60", "1 saat"), ("240", "4 saat"), ("1D", "1 gün")):
            check = QtWidgets.QCheckBox(label)
            check.setChecked(code in selected or (code == "60" and "1H" in selected))
            box.addWidget(check)
            choices.append((code, check))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Seç")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        self._configure_selection_help(dialog, box, "timeframes", tuple(
            (code, check, check.text(), "Bu mum süresini test kapsamına dahil eder veya çıkarır.",
             "İşaretlenen her zaman dilimi toplam kombinasyon sayısını çarpar. Seç ile onaylayana kadar mevcut plan değişmez; bu seçim grafiğin süresini şimdi değiştirmez.")
            for code, check in choices), buttons)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.timeframes.setText(", ".join(self._timeframe_label(code) for code, check in choices if check.isChecked()))

    def choose_symbols(self):
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Sembol seç")
        dialog.resize(500, 380)
        box = QtWidgets.QVBoxLayout(dialog)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText("Sembol veya şirket adı yazın")
        box.addWidget(search)
        lookup = QtWidgets.QPushButton("TradingView'de ara")
        box.addWidget(lookup)
        note = QtWidgets.QLabel("Arama TradingView sembol kataloğunda yapılır. Veri erişimi ve tarama koşulları ayrı grafikte ayrıca doğrulanır. İnternet yoksa kayıtlı semboller kullanılabilir.")
        note.setWordWrap(True); box.addWidget(note)
        listing = QtWidgets.QListWidget(); box.addWidget(listing)
        symbols = {"BIST:XU030D1!"}
        for values in FTMO_SYMBOL_PROFILES.values():
            symbols.update(values)
        for chart in getattr(self, "_last_inventory", []):
            if chart.get("symbol"):
                symbols.add(chart["symbol"])
        selected = {s.strip() for s in self.symbols.text().split(",") if s.strip()}
        symbols.update(selected)
        for symbol in sorted(symbols):
            item = QtWidgets.QListWidgetItem(symbol)
            item.setData(QtCore.Qt.UserRole, symbol)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if symbol in selected else QtCore.Qt.Unchecked)
            listing.addItem(item)
        search.textChanged.connect(lambda text: [listing.item(i).setHidden(text.casefold() not in listing.item(i).text().casefold()) for i in range(listing.count())])
        manager = QtNetwork.QNetworkAccessManager(dialog)
        def request_catalogue():
            try:
                request = QtNetwork.QNetworkRequest(QtCore.QUrl(search_url(search.text())))
            except ValueError as exc:
                note.setText(str(exc))
                return
            request.setRawHeader(b"Origin", b"https://www.tradingview.com")
            request.setRawHeader(b"Referer", b"https://www.tradingview.com/")
            request.setTransferTimeout(8000)
            lookup.setEnabled(False)
            note.setText("TradingView sembolleri aranıyor…")
            reply = manager.get(request)
            def complete():
                lookup.setEnabled(True)
                try:
                    if reply.error() != QtNetwork.QNetworkReply.NoError:
                        raise ValueError("Sembol servisine ulaşılamadı. Kayıtlı sembolleri kullanabilir veya yeniden deneyebilirsiniz.")
                    rows = catalogue_results(json.loads(bytes(reply.readAll())))
                    known = {listing.item(i).data(QtCore.Qt.UserRole): listing.item(i)
                             for i in range(listing.count())}
                    for row in rows:
                        item = known.get(row["code"])
                        if item is None:
                            item = QtWidgets.QListWidgetItem()
                            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                            item.setCheckState(QtCore.Qt.Unchecked)
                            item.setData(QtCore.Qt.UserRole, row["code"])
                            listing.addItem(item)
                        item.setText(f"{row['name']} · {row['exchange']}")
                        item.setToolTip(row["code"])
                        item.setHidden(False)
                    note.setText(f"{len(rows)} sembol bulundu. İstediklerinizi işaretleyin." if rows else
                                 "Sembol bulunamadı. Daha kısa bir adla yeniden arayın.")
                except (ValueError, TypeError) as exc:
                    note.setText(str(exc))
                finally:
                    reply.deleteLater()
            reply.finished.connect(complete)
        lookup.clicked.connect(request_catalogue)
        search.returnPressed.connect(request_catalogue)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Seç")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        self._configure_selection_help(dialog, box, "symbols", (
            ("search", search, "Sembol adı ara", "Yazdığın metin kayıtlı listeyi süzer; Enter çevrimiçi aramayı başlatır.",
             "TradingView'de ara veya Enter sembol kataloğuna sorgu gönderir. Sembolün bulunması hesabının o veriye erişebildiğini kanıtlamaz; veri ve test koşulları hazırlık sırasında doğrulanır."),
            ("lookup", lookup, "TradingView kataloğunda ara", "Yazdığın ad için çevrimiçi sembol araması yapar.",
             "İnternet bağlantısı gerekir. Arama kişisel grafiği değiştirmez; servis yoksa kayıtlı listedeki semboller kullanılabilir. Sağlayıcıyı ve tam sembol kodunu kontrol et."),
            ("list", listing, "Test sembollerini işaretle", "İşaretlenen sembolleri Seç ile test kapsamına aktarır.",
             "Arama filtresi daha önce işaretlenen gizli satırları kaldırmaz. Onayda tüm işaretli semboller kullanılır; her sembol test sayısını artırır. Tam kod arama sonucunun hücre açıklamasında gösterilir."),
            ("status", note, "Sembol arama durumu", "Aramanın ilerleme, sonuç veya hata açıklamasını gösterir.",
             "Katalog araması veri erişimi veya canlı test doğrulaması değildir. Bağlantı hatasında kayıtlı listeyi kullanabilir veya yeniden deneyebilirsin."),
        ), buttons)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            self.symbols.setText(", ".join(listing.item(i).data(QtCore.Qt.UserRole) for i in range(listing.count())
                                        if listing.item(i).checkState() == QtCore.Qt.Checked))

    def choose_dates(self):
        dialog = QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Tarih aralığı")
        box = QtWidgets.QFormLayout(dialog)
        fields = []
        for title, source in (("Başlangıç", self.date_from), ("Bitiş", self.date_to)):
            field = QtWidgets.QDateEdit()
            field.setCalendarPopup(True); field.setDisplayFormat("yyyy-MM-dd")
            parsed = QtCore.QDate.fromString(source.text(), "yyyy-MM-dd")
            field.setDate(parsed if parsed.isValid() else QtCore.QDate.currentDate())
            box.addRow(title, field); fields.append(field)
        clear = QtWidgets.QPushButton("Grafikteki mevcut geçmişi kullan")
        clear.clicked.connect(lambda: dialog.done(2)); box.addRow(clear)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); box.addRow(buttons)
        self._configure_selection_help(dialog, box, "dates", (
            ("start", fields[0], "Test başlangıcı", "Onaylandığında plana aktarılacak başlangıç tarihidir.",
             "Takvim veya klavye ile düzenle. Alan boş bir plan için bugünü gösterir, fakat onaylamadan plana yazılmaz. Seçim, TradingView raporunun bu dönemde üretildiğinin kanıtı değildir."),
            ("stop", fields[1], "Test bitişi", "Onaylandığında plana aktarılacak bitiş tarihidir.",
             "Başlangıç tarihinden önce olmamalıdır. Tarih desteği ve gerçek rapor dönemi hazırlıkta ayrıca doğrulanır; bu pencere test başlatmaz."),
            ("clear", clear, "Erişilebilen geçmişi kullan", "Pencereyi kapatır ve planın iki tarih alanını boşaltır.",
             "Bu düğme bir onay eylemidir: mevcut özel dönemi kaldırır. Grafikte erişilen dönem kullanılacak; tüm piyasa geçmişinin erişilebilir olduğu varsayılmaz. Vazgeç ise eski tarihleri korur."),
        ), buttons)
        result = dialog.exec()
        if result == 2:
            self.date_from.clear(); self.date_to.clear()
        elif result == QtWidgets.QDialog.Accepted:
            self.date_from.setText(fields[0].date().toString("yyyy-MM-dd"))
            self.date_to.setText(fields[1].date().toString("yyyy-MM-dd"))

    def focus_missing_field(self):
        field = self.symbols if not self.symbols.text().strip() else self.timeframes if not self.timeframes.text().strip() else self.date_from
        self.scan_scroll.ensureWidgetVisible(field)
        field.setFocus()

    def prepare_and_start(self):
        if self._admission_job is not None:
            return
        if self._count_key is not None and (self._count_result is None or self._count_result.get("status") != "ready"):
            self.plan_status.setText("Hazırlığa başlamadan önce kombinasyon sayımını tamamlayın veya yeniden deneyin.")
            return
        if self._preparing or (getattr(self, "_connection_timer", None) and self._connection_timer.isActive()) or (self.supervisor and self.supervisor.running):
            return
        self._preparing = True
        self.enqueue_plan_button.setEnabled(False)
        try:
            project_id = self.plan_project.currentData()
            project = self.store.project(project_id) if project_id is not None else None
            if not project:
                raise ValueError("Önce bir strateji seçin.")
            plan = self._current_plan()
            plan.validate(require_study_id=False)
            run_request = self.run_choice.request(project_id, plan)
            if plan.constraints and plan.cartesian_count > 10000:
                if json.dumps(plan.to_dict(), sort_keys=True, allow_nan=False) != self._count_key:
                    self.preview_plan()
                    return
                count = self._count_result["tasks"]
            else:
                count = plan.task_count
            if plan.date_range and not (GncZihinDriver.date_range_ready and GncZihinDriver.deep_capture_ready):
                raise ValueError("Özel tarih aralığı bu sürümde doğrulanmadı. Tarihleri temizleyerek grafikteki geçmişle devam edebilirsiniz.")
            self.connection_status.setText("Bağlanıyor: TradingView kontrol ediliyor…")
            if not cdp_healthy():
                path = self.tv_executable.text().strip()
                if not Path(path).is_file():
                    self.find_tradingview()
                    path = self.tv_executable.text().strip()
                if not Path(path).is_file():
                    raise ValueError("TradingView bulunamadı. Gelişmiş ayarlardan uygulama yolunu seçin.")
                launch_with_cdp(path)
                self.connection_status.setText("Bağlanıyor: TradingView açılıyor. Hazır olduğunda devam edilecek.")
                self._connection_deadline = __import__('time').monotonic() + 30
                self._preparing = False
                self._connection_timer = QtCore.QTimer(self.window)
                self._connection_timer.setInterval(1500)
                self._connection_timer.timeout.connect(self._wait_for_connection)
                self._connection_timer.start()
                return
            self.driver = GncZihinDriver(self.motor_path.text().strip())
            targets = chart_targets()
            prepared_charts = []
            requested = self.parallel_count.value()
            self.parallel_count.setEnabled(False)
            preparation_settings = self.store.settings(project_id) or {}
            for slot in range(requested):
                journal_key = ("automatic_preparation" if slot == 0
                               else f"automatic_preparation_parallel_{slot}")
                journal = preparation_settings.get(journal_key) or {}
                preferred_chart_id = journal.get("chart_id")
                if preferred_chart_id is None and slot == 0 and not journal:
                    preferred_chart_id = preparation_settings.get("prepared_chart_id")
                if journal and preferred_chart_id is None:
                    # An external create may have succeeded before identity
                    # readback. Resume that intent; don't adopt another layout.
                    prepared = PreparationResult(PreparationState.ACTION_REQUIRED,
                        "Önceki bağımsız grafik hazırlığı tamamlanmalı.",
                        "Kayıtlı grafik hazırlığına devam et")
                    break
                prepared = find_prepared_chart(self.driver, targets, project,
                    preferred_chart_id=preferred_chart_id,
                    excluded_targets={item.target_id for item in prepared_charts})
                if prepared.target_id is None:
                    break
                prepared_charts.append(prepared)
            if len(prepared_charts) < requested:
                self.connection_status.setText("İşlem gerekli: " + prepared.message)
                self.connection_status.setToolTip(prepared.technical_detail)
                answer = QtWidgets.QMessageBox.question(self.window, "Ayrı tarama grafiği oluştur",
                    f"{project['name']} için yeni bağımsız tarama grafiği oluşturulsun mu?\n\n"
                    "Strateji kodu TradingView hesabınıza ayrı bir özel script olarak kaydedilecek; "
                    "yayımlanmayacak ve mevcut scriptler değiştirilmeyecek. Kişisel grafikler korunacak. "
                    "Hazırlık bittiğinde tarama başlamadan önce test özeti için onay alınacak.")
                if answer == QtWidgets.QMessageBox.Yes:
                    self._preparation_job = ChartPreparationJob(self.driver, self.store, project, slot=len(prepared_charts))
                    application = QtWidgets.QApplication.instance()
                    jobs = getattr(application, "_chart_preparation_jobs", [])
                    jobs.append(self._preparation_job)
                    application._chart_preparation_jobs = jobs
                    job = self._preparation_job
                    job.progress.connect(self.connection_status.setText)
                    job.completed.connect(self._automatic_preparation_completed)
                    job.finished.connect(lambda: jobs.remove(job) if job in jobs else None)
                    job.start()
                return
            answer = QtWidgets.QMessageBox.question(self.window, "Tarama grafiği kullanım onayı",
                f"Strateji: {project['name']}\n"
                f"Tarama grafikleri ({requested}): {', '.join(self.driver.layout_name(item.target_id) for item in prepared_charts)}\n"
                f"{count} test: {', '.join(plan.symbols)} / "
                f"{', '.join(self._timeframe_label(tf) for tf in plan.timeframes)}.\n"
                + self._scan_confirmation_conditions(plan) + "\n"
                + "\n".join(f"{item.title}: {', '.join(map(str, plan.input_values.get(f'in_{index}', [])))}"
                    for index, item in enumerate(self._plan_parsed_inputs)
                    if len(plan.input_values.get(f'in_{index}', [])) > 1) + "\n"
                "Yalnız bu tarama grafikleri değiştirilecek; kişisel grafikler korunacak. Devam edilsin mi?")
            if answer != QtWidgets.QMessageBox.Yes:
                self.connection_status.setText("Hazır: tarama başlatılmadı. Ayarları düzenleyip yeniden hazırlayabilirsiniz.")
                return
            prepared = prepared_charts[0]
            for item in prepared_charts:
                self._safe_worker_layouts[item.target_id] = item.chart_id
                self._safe_worker_targets.add(item.target_id)
            self.store.save_settings(project_id, {"prepared_chart_id": prepared.chart_id})
            self.worker_project.setCurrentIndex(self.worker_project.findData(project_id))
            self.discover_targets()
            selected_rows = []
            assignments = []
            for item in prepared_charts:
                row = next((r for r in range(self.worker_table.rowCount())
                    if self.worker_table.item(r, 2).data(QtCore.Qt.UserRole) == item.target_id), None)
                if row is None:
                    raise ValueError("Hazırlanan grafik artık açık değil. Yeniden hazırlayın.")
                self.worker_table.cellWidget(row, 3).setCurrentIndex(
                    self.worker_table.cellWidget(row, 3).findData(project_id))
                self.refresh_worker_match(row)
                self.worker_table.setCurrentCell(row, 4)
                self.bind_selected_strategy()
                if self.worker_table.item(row, 5).text() != WORKER_READY_LABEL:
                    raise ValueError("Kaynak doğrulaması tamamlanmadı. " + self.worker_status.text())
                strategy = self.worker_table.item(row, 4).data(QtCore.Qt.UserRole)
                selected_rows.append(row)
                assignments.append(WorkerAssignment(int(self.worker_table.item(row, 1).text()), item.target_id, (project_id,), strategy["id"]))
            row = selected_rows[0]
            strategy = self.worker_table.item(row, 4).data(QtCore.Qt.UserRole)
            self.strategy_picker.clear()
            self.strategy_picker.addItem(strategy.get("name", project["name"]),
                {"study_id": strategy["id"], "source_confirmed": True})
            self.study_id.setText(strategy["id"])
            for r in range(self.worker_table.rowCount()):
                self.worker_table.item(r, 0).setCheckState(QtCore.Qt.Checked if r in selected_rows else QtCore.Qt.Unchecked)
            self._validate_live_worker_assignments(assignments)
            ready_plan = self._current_plan()
            def launch_admitted(run_id):
                self._validate_live_worker_assignments(assignments)
                from dataclasses import replace
                scoped = [replace(assignment, run_ids=(run_id,)) for assignment in assignments]
                self.start_workers(confirmed=True, prepared_assignments=scoped)
                if self.supervisor and self.supervisor.running:
                    self.connection_status.setText("Hazır: tarama çalışıyor.")
                    self._show_page(4)
                else:
                    raise ValueError(self.worker_status.text())
            # Revalidate the selection after preparation; never admit a silently changed resume plan.
            if run_request != self.run_choice.request(project_id, ready_plan):
                raise ValueError("Koşu seçimi hazırlık sırasında değişti; yeniden hazırlayın.")
            self._start_plan_admission(project_id, ready_plan, launch_admitted,
                                       require_pending_subset=True, **run_request)
        except Exception as exc:
            self.connection_status.setText("İşlem gerekli: " + self._friendly_error(exc))
            self.connection_status.setToolTip(str(exc))
        finally:
            self._preparing = bool(self._admission_job is not None or
                (getattr(self, "_preparation_job", None) and self._preparation_job.isRunning()))
            self.parallel_count.setEnabled(not bool(self._preparing or (self.supervisor and self.supervisor.running)))
            self.preview_plan()

    def _automatic_preparation_completed(self, result):
        self._preparing = False
        if getattr(self, "_closing", False):
            return
        if result.get("success"):
            self.connection_status.setText("Hazır: bağımsız grafik ve strateji kaynağı doğrulandı.")
            if self.plan_project.currentData() == result["project_id"]:
                QtCore.QTimer.singleShot(0, self.window,
                                         lambda: self.prepare_and_start()
                                         if not getattr(self, "_closing", False) else None)
        else:
            self.connection_status.setText("İşlem gerekli: " + self._friendly_error(RuntimeError(result["error"])))
            self.connection_status.setToolTip(result["error"])
        self.preview_plan()

    @staticmethod
    def _scan_confirmation_conditions(plan):
        dates = plan.date_range or {}
        period = (f"{dates.get('from', '—')} – {dates.get('to', '—')}"
                  if dates else "Grafikte erişilebilen geçmiş")
        costs = (plan.costs or {}).get("assumptions") or {}
        labels = (("initial_capital", "Başlangıç sermayesi"),
                  ("position_size", "Pozisyon boyutu"),
                  ("commission_value", "Komisyon (%)"),
                  ("spread", "Spread"), ("slippage", "Kayma (tick)"))
        lines = [f"Tarih aralığı: {period}",
                 f"İşlem analizi saat dilimi: {costs.get('analysis_timezone', 'Belirtilmedi')}"]
        lines.extend(f"{label}: {costs[key]}" for key, label in labels if key in costs)
        lines.append(f"Maliyet senaryosu: {costs.get('scenario', 'Özel')}")
        return "\n".join(lines)

    def _wait_for_connection(self):
        if cdp_healthy():
            self._connection_timer.stop()
            self.prepare_and_start()
        elif __import__('time').monotonic() >= self._connection_deadline:
            self._connection_timer.stop()
            self.connection_status.setText("İşlem gerekli: TradingView bağlantısı 30 saniyede kurulamadı. Uygulamanın açıldığını kontrol edip tekrar deneyin.")
            self.preview_plan()

    def _input_choices_settings(self):
        return {"input_ui": {
            self.plan_inputs.item(row, 0).text(): {
                "decision": self.plan_inputs.cellWidget(row, 3).currentText(),
                "values": self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole) or [],
                "range": self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole + 1) or {},
            } for row in range(self.plan_inputs.rowCount())
        }}

    @staticmethod
    def _timeframe_codes(text):
        import re
        labels = {"1 dakika": "1", "5 dakika": "5", "15 dakika": "15", "30 dakika": "30",
                  "1 saat": "60", "4 saat": "240", "1 gün": "1D", "1 hafta": "1W", "1 ay": "1M"}
        codes = []
        for value in text.split(","):
            value = value.strip()
            if not value:
                continue
            numeric = re.fullmatch(r"(\d+) (dakika|saat)", value)
            codes.append(str(int(numeric[1]) * (60 if numeric[2] == "saat" else 1))
                         if numeric else labels.get(value, value))
        return codes

    @staticmethod
    def _timeframe_label(value):
        from .tradingview import chart_resolution
        code = chart_resolution(str(value))
        if code.isdigit():
            minutes = int(code)
            return f"{minutes // 60} saat" if minutes and minutes % 60 == 0 else f"{minutes} dakika"
        return {"D": "1 gün", "W": "1 hafta", "1M": "1 ay"}.get(code, str(value))

    @staticmethod
    def _friendly_error(exc):
        detail = str(exc)
        if "yardımcı işlemi başlatılamadı" in detail:
            return "TradingView'i bulmak için gereken Windows yardımcı işlemi açılamadı. TradingView.exe yolunu elle seçin; hata kodu teknik ayrıntılarda bulunur."
        if "Sonuç doğrulanamadı" in detail:
            return "TradingView sonucu istenen ayarlarla doğrulanamadı. Teknik ayrıntıları inceleyip testi yeniden deneyin."
        if "CDP eval" in detail:
            return "TradingView hazırlık işlemini tamamlayamadı. Teknik açıklamayı kontrol edin; mevcut grafik ve script kayıtları korunuyor."
        if any(token in detail for token in ("10061", "urlopen", "CDP", "9222")):
            return "TradingView ile bağlantı kurulamadı. TradingView açıksa kaydedilmemiş işlerinizi koruyarak kapatın; ardından yeniden hazırlayın."
        if "geçerli timeframe" in detail:
            return "En az bir zaman dilimi seçin. ‘Zaman dilimi seç’ düğmesini kullanabilirsiniz."
        return detail

    def _page_header(self, title, subtitle):
        Q = self.QtWidgets
        block = Q.QWidget()
        box = Q.QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 18)
        box.addWidget(Q.QLabel(title, objectName="title"))
        box.addWidget(Q.QLabel(subtitle, objectName="subtitle"))
        return block

    def _dashboard_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Tarama masası", "Kuyrukların ve doğrulanmış sonuçların canlı özeti"))
        self.dashboard_metrics = Q.QFrame()
        metrics = Q.QHBoxLayout(self.dashboard_metrics)
        metrics.setContentsMargins(0, 0, 0, 0)
        self.metric_labels = {}
        for key, label in (("projects", "Projeler"), ("pending", "Bekleyen"), ("running", "Çalışan"), ("done", "Tamamlanan"), ("failed", "Geçersiz"), ("manual_review", "İnceleme")):
            frame = Q.QFrame(objectName="metric")
            inner = Q.QVBoxLayout(frame)
            value = Q.QPushButton("0", objectName="metricValue")
            value.setToolTip("İlgili görevleri gör" if key != "projects" else "Projeleri gör")
            value.clicked.connect(lambda _checked=False, status=key: self.open_dashboard_tasks(status))
            inner.addWidget(value)
            inner.addWidget(Q.QLabel(label, objectName="metricLabel"))
            self.metric_labels[key] = value
            metrics.addWidget(frame)
        box.addWidget(self.dashboard_metrics)
        self.dashboard_operational = Q.QFrame()
        operational = Q.QHBoxLayout(self.dashboard_operational)
        operational.setContentsMargins(0, 0, 0, 0)
        self.throughput_label = Q.QLabel("Hız: ölçüm bekleniyor", objectName="status")
        self.eta_label = Q.QLabel("ETA: —", objectName="status")
        self.candidate_label = Q.QLabel("Aday: 0", objectName="status")
        self.resource_label = Q.QLabel("CPU/RAM: ölçüm bekleniyor", objectName="status")
        operational.addWidget(self.throughput_label); operational.addWidget(self.eta_label); operational.addWidget(self.candidate_label)
        operational.addWidget(self.resource_label)
        operational.addStretch()
        box.addWidget(self.dashboard_operational)
        backup_actions = Q.QHBoxLayout()
        backup_actions.addStretch()
        backup = Q.QPushButton("Yedek oluştur"); backup.clicked.connect(self.create_portable_backup)
        self.dashboard_backup_button = backup
        backup_actions.addWidget(backup)
        self.restore_backup_button = Q.QPushButton("Yedeği yeni dosyaya aç")
        self.restore_backup_button.setToolTip("Mevcut veriyi değiştirmeden yeni bir veritabanı dosyası oluşturur.")
        self.restore_backup_button.clicked.connect(self.restore_portable_backup)
        backup_actions.addWidget(self.restore_backup_button)
        box.addLayout(backup_actions)
        self.dashboard_setup = Q.QFrame(objectName="metric")
        setup_layout = Q.QVBoxLayout(self.dashboard_setup)
        self.dashboard_setup_title = Q.QLabel("İlk taramanı kur")
        self.dashboard_setup_title.setStyleSheet("font-family:Georgia;font-size:21px;font-weight:700")
        self.dashboard_setup_text = Q.QLabel("Pine stratejini ekle; ayarları ve görev sayısını taramadan önce birlikte göreceğiz.")
        self.dashboard_setup_text.setWordWrap(True)
        self.dashboard_setup_action = Q.QPushButton("Yeni proje oluştur", objectName="primary")
        self.dashboard_setup_page = 1
        self.dashboard_setup_action.clicked.connect(lambda: self._show_page(self.dashboard_setup_page))
        setup_layout.addWidget(self.dashboard_setup_title)
        setup_layout.addWidget(self.dashboard_setup_text)
        setup_layout.addWidget(self.dashboard_setup_action, 0, QtCore.Qt.AlignLeft)
        box.addWidget(self.dashboard_setup)
        box.addSpacing(20)
        self.dashboard_projects_heading = Q.QLabel("Projeler", objectName="subtitle")
        box.addWidget(self.dashboard_projects_heading)
        self.dashboard_empty = Q.QLabel("Henüz proje yok. 'Yeni proje' bölümünde Pine stratejinizi ekleyin.", objectName="subtitle")
        box.addWidget(self.dashboard_empty)
        self.project_table = Q.QTableWidget(0, 6)
        self.project_table.setHorizontalHeaderLabels(["ID", "Proje", "Durum", "Öncelik", "Görev", "İlerleme"])
        self.project_table.horizontalHeader().setStretchLastSection(True)
        self.project_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.project_table.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.project_table.setMinimumHeight(140)
        box.addWidget(self.project_table, 1)
        self.dashboard_events_heading = Q.QLabel("Son olaylar", objectName="subtitle")
        box.addWidget(self.dashboard_events_heading)
        self.dashboard_events_empty = Q.QLabel("Henüz olay kaydı yok; tarama başladığında burada görünecek.", objectName="subtitle")
        box.addWidget(self.dashboard_events_empty)
        self.dashboard_events = Q.QTableWidget(0, 4)
        self.dashboard_events.setHorizontalHeaderLabels(["Seviye", "Worker", "Görev", "Olay"])
        self.dashboard_events.horizontalHeader().setStretchLastSection(True)
        self.dashboard_events.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.dashboard_events.setMaximumHeight(170)
        box.addWidget(self.dashboard_events)
        self.dashboard_actions = Q.QFrame()
        controls = Q.QHBoxLayout(self.dashboard_actions)
        controls.setContentsMargins(0, 0, 0, 0)
        self.project_priority = Q.QSpinBox(); self.project_priority.setRange(-100, 100); self.project_priority.setPrefix("Öncelik ")
        self.project_state = Q.QComboBox()
        for status, label in PROJECT_STATUS_LABELS.items():
            self.project_state.addItem(label, status)
        apply_project = Q.QPushButton("Projeyi güncelle"); apply_project.clicked.connect(self.update_selected_project)
        cancel = Q.QPushButton("Bekleyenleri iptal et"); cancel.clicked.connect(self.cancel_selected_project)
        retry = Q.QPushButton("Hatalıları yeniden sırala"); retry.clicked.connect(self.retry_selected_project)
        self.dashboard_project_actions = (self.project_priority, self.project_state,
                                          apply_project, cancel, retry)
        for widget in (self.project_priority, self.project_state, apply_project, cancel, retry): controls.addWidget(widget)
        controls.addStretch(); box.addWidget(self.dashboard_actions)
        self.dashboard_status = Q.QLabel("", objectName="status"); box.addWidget(self.dashboard_status)
        return page

    def open_dashboard_tasks(self, status, project_id=None):
        if status == "projects":
            self.project_table.setFocus()
            self.project_table.scrollToTop()
            return
        total, rows = self.store.task_summaries(status, project_id=project_id)
        dialog = self.QtWidgets.QDialog(self.window)
        project = self.store.project(project_id) if project_id is not None else None
        scope = project["name"] if project else (status or "Tüm")
        dialog.setWindowTitle(f"{scope} görevleri · {total:,}")
        dialog.resize(930, 560)
        layout = self.QtWidgets.QVBoxLayout(dialog)
        summary = self.QtWidgets.QLabel(
            f"Toplam {total:,} görev · son {len(rows)} kayıt gösteriliyor. Tüm kayıtlar CSV/Excel olarak dışa aktarılabilir."
        )
        layout.addWidget(summary)
        table = self.QtWidgets.QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(["Görev", "Proje", "Sembol", "TF", "Input sayısı"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        for index, row in enumerate(rows):
            payload = row["payload"]
            values = (row["task_key"], row["project"], payload.get("symbol"),
                      payload.get("timeframe"), len(payload.get("inputs") or {}))
            for column, value in enumerate(values):
                table.setItem(index, column, self.QtWidgets.QTableWidgetItem(str(value if value is not None else "—")))
        layout.addWidget(table)
        close = self.QtWidgets.QPushButton("Kapat")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        help_scope = self._configure_readonly_dialog_help(dialog, layout, "task_summary", (
            ("count", summary, "Toplam ve gösterilen görev sayısı", "Bu kapsamın toplam görev ve ekranda gösterilen son kayıt sayısıdır.",
             "Görüntülenen kayıt sayısının toplamdan az olması eski görevlerin silindiği anlamına gelmez. Bu pencere tam dışa aktarma dosyası değildir; dosya kapsamını dışa aktarma ekranında ayrıca seç."),
            ("table", table, "Görev özeti", "Seçili durum veya projedeki görevlerin kimlik ve test kapsamını gösterir.",
             "Bu salt okunur liste metrik veya test kanıtı sunmaz. Tamamlanan görev listesi bile tek başına başarı garantisi değildir. Burada görev iptal edilmez veya yeniden sıraya alınmaz."),
        ), close)
        help_scope.register_columns("viewer.task_summary.table", table, tuple(
            (title, short, short + " Bu liste görevleri veya sonuçları değiştirmez.")
            for title, short in (
                ("Görev", "Test görevinin kayıtlı anahtarıdır; sonuç metriği değildir."),
                ("Proje", "Görevin bağlı olduğu kayıtlı strateji adıdır."),
                ("Sembol", "Görev planındaki piyasa ve sağlayıcı kodudur; uygulanmış olduğunun kanıtı değildir."),
                ("Zaman dilimi", "Görev planındaki mum süresidir; 15, 15 dakikayı belirtir."),
                ("Ayar sayısı", "Görev yükündeki ayar sayısıdır; işlem veya kombinasyon sayısı değildir."),
            )))
        dialog.exec()

    def _settings_page(self):
        Q = self.QtWidgets
        page = Q.QWidget(); box = Q.QVBoxLayout(page); box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Ayarlar", "Yerel doğrulama ve bildirim seçenekleri"))
        form = Q.QFormLayout()
        self.default_timeout = Q.QDoubleSpinBox(); self.default_timeout.setRange(5, 600); self.default_timeout.setValue(75); self.default_timeout.setSuffix(" sn")
        self.default_poll = Q.QDoubleSpinBox(); self.default_poll.setRange(.05, 10); self.default_poll.setDecimals(2); self.default_poll.setValue(.7); self.default_poll.setSuffix(" sn")
        self.default_stable = Q.QSpinBox(); self.default_stable.setRange(1, 10); self.default_stable.setValue(3)
        self.notifications_enabled = SwitchToggle("Windows bildirimlerini göster"); self.notifications_enabled.setChecked(True)
        port = Q.QLineEdit("9222"); port.setReadOnly(True)
        database = Q.QLineEdit(str(self.store.path)); database.setReadOnly(True)
        self.settings_port = port
        self.settings_database = database
        form.addRow("Tek CDP portu", port); form.addRow("Yerel veritabanı", database)
        form.addRow("Bildirimler", self.notifications_enabled)
        box.addLayout(form)
        advanced_toggle = DisclosureButton("Gelişmiş bağlantı ayarları")
        self.settings_advanced_toggle = advanced_toggle
        advanced = Q.QFrame()
        advanced_form = Q.QFormLayout(advanced)
        advanced_form.addRow("Görev için azami bekleme", self.default_timeout)
        advanced_form.addRow("Kontrol sıklığı", self.default_poll)
        advanced_form.addRow("Doğrulama okuma sayısı", self.default_stable)
        advanced.setVisible(False)
        advanced_toggle.toggled.connect(advanced.setVisible)
        box.addWidget(advanced_toggle)
        box.addWidget(advanced)
        save = Q.QPushButton("Ayarları kaydet", objectName="primary"); save.clicked.connect(self.save_application_settings)
        self.settings_save_button = save
        box.addWidget(save); self.settings_status = Q.QLabel("Telemetri ve bulut bağlantısı kapalıdır.", objectName="status")
        box.addWidget(self.settings_status)
        archive = Q.QPushButton("Araştırma arşivi içe aktar (isteğe bağlı)")
        self.archive_import_button = archive
        archive.clicked.connect(self.import_research_archive)
        box.addWidget(archive)
        archive_open = Q.QPushButton("İçe aktarılan araştırma arşivini aç")
        archive_open.clicked.connect(lambda: self._show_auxiliary(5, "İçe aktarılan araştırma arşivi"))
        archive_open.setEnabled(bool(self.store.app_settings().get("imported_research_catalog")))
        self.archive_open_button = archive_open
        box.addWidget(archive_open)
        self.support_package_button = Q.QPushButton("Yerel destek paketi oluştur (isteğe bağlı)")
        self.support_package_button.clicked.connect(self.show_support_package)
        box.addWidget(self.support_package_button); box.addStretch()
        settings = self.store.app_settings()
        self.default_timeout.setValue(float(settings.get("timeout", 75)))
        self.default_poll.setValue(float(settings.get("poll_interval", .7)))
        self.default_stable.setValue(int(settings.get("stable_reads", 3)))
        self.notifications_enabled.setChecked(bool(settings.get("notifications", True)))
        return page

    def _scan_setup_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Tarama", "Stratejini, test koşullarını ve denenecek değerleri seç."))
        box.addWidget(self._first_use_help("scan", "Taramayı nasıl ayarlayacağım?",
            "Sembol seç ile test edeceğiniz piyasayı, Zaman dilimi seç ile grafik aralığını belirleyin. "
            "Tarih seç ile dönemi sınırlayabilirsiniz; boş bırakınca erişilebilen geçmiş kullanılır.\n"
            "Ayar tablosunda Sabit tut tek değeri kullanır. Farklı değerleri dene seçip tarama değerlerini düzenleyin: "
            "örneğin Fast EMA için 7, 8, 9 üç test oluşturur. Gelişmiş ayarlardan maliyet ve başarı ölçütlerini değiştirebilirsiniz.\n"
            "Alttaki özeti kontrol edin, Hazırla ve başlat seçin. Uygulama ayrı grafiği hazırlar; başlamadan önce değişiklikleri onaylarsınız."))
        self.connection_status = Q.QLabel("TradingView bağlantısı hazırlık sırasında kontrol edilecek.")
        self.connection_status.setWordWrap(True)
        box.addWidget(self.connection_status)
        self.scan_flow_status = Q.QLabel("Proje: eksik · Strateji: eksik · Plan: eksik · Sekmeler: onay gerekli", objectName="status")
        self.scan_flow_status.setWordWrap(True)
        self.scan_flow_status.hide()  # Internal compatibility; the visible summary is below.
        box.addWidget(self.scan_flow_status)
        context_form = Q.QFormLayout()
        scope_form = Q.QFormLayout()
        self.plan_project = Q.QComboBox()
        self.plan_project.setMaximumWidth(360)
        self.plan_project.setMaxVisibleItems(8)
        self.plan_project.currentIndexChanged.connect(self.load_plan_inputs)
        self.plan_project.activated.connect(lambda _index: self._remember_project(self.plan_project.currentData()))
        find_project = Q.QPushButton("Proje ara")
        self.project_search_button = find_project
        find_project.clicked.connect(self.open_project_picker)
        self.study_id = Q.QLineEdit()  # Internal binding; users select a named strategy below.
        self.strategy_picker = Q.QComboBox(); self.strategy_picker.setMaximumWidth(560)
        self.strategy_picker.addItem("Önce projeyi seçin", None)
        self.strategy_picker.currentIndexChanged.connect(self.select_plan_strategy)
        find_strategy = Q.QPushButton("Açık stratejiyi bul")
        self.strategy_discovery_button = find_strategy
        find_strategy.clicked.connect(self.discover_plan_strategies)
        self.symbols = Q.QLineEdit(); self.symbols.setPlaceholderText("Henüz sembol seçilmedi")
        self.symbol_profile = Q.QComboBox(); self.symbol_profile.addItem("Özel")
        self.symbol_profile.addItems(FTMO_SYMBOL_PROFILES.keys())
        self.symbol_profile.currentTextChanged.connect(self.apply_symbol_profile)
        self.timeframes = Q.QLineEdit(); self.timeframes.setPlaceholderText("Henüz zaman dilimi seçilmedi")
        self.analysis_timezone = Q.QComboBox()
        self.analysis_timezone.addItems(["UTC", "America/New_York", "Europe/Istanbul"])
        self.analysis_timezone.setCurrentText("America/New_York")
        self.date_from = Q.QLineEdit(); self.date_from.setPlaceholderText("Başlangıç — isteğe bağlı")
        self.date_to = Q.QLineEdit(); self.date_to.setPlaceholderText("Bitiş — isteğe bağlı")
        for date_field in (self.date_from, self.date_to):
            date_field.setToolTip(
                "Özel tarih seçimi plan önizlemesi içindir; TradingView'de otomatik uygulama henüz açık değil."
            )
        project_row = Q.QHBoxLayout()
        project_row.addWidget(self.plan_project)
        project_row.addWidget(find_project)
        project_row.addStretch()
        context_form.addRow("Strateji", project_row)
        strategy_row = Q.QHBoxLayout(); strategy_row.addWidget(self.strategy_picker); strategy_row.addWidget(find_strategy); strategy_row.addStretch()
        self.manual_strategy_row = Q.QWidget()
        self.manual_strategy_row.setLayout(strategy_row)
        symbol_row = Q.QHBoxLayout(); symbol_row.addWidget(self.symbol_profile); symbol_row.addWidget(self.symbols, 1)
        symbol_select = Q.QPushButton("Sembol seç")
        self.symbol_select_button = symbol_select
        symbol_select.clicked.connect(self.choose_symbols)
        symbol_row.addWidget(symbol_select)
        scope_form.addRow("Semboller", symbol_row)
        timeframe_row = Q.QHBoxLayout()
        timeframe_row.addWidget(self.timeframes)
        timeframe_select = Q.QPushButton("Zaman dilimi seç")
        self.timeframe_select_button = timeframe_select
        timeframe_select.clicked.connect(self.choose_timeframes)
        timeframe_row.addWidget(timeframe_select)
        scope_form.addRow("Zaman dilimleri", timeframe_row)
        scope_form.addRow("İşlem analizi saat dilimi", self.analysis_timezone)
        dates = Q.QHBoxLayout(); dates.addWidget(self.date_from); dates.addWidget(self.date_to)
        date_pick = Q.QPushButton("Tarih seç")
        self.date_select_button = date_pick
        date_pick.clicked.connect(self.choose_dates)
        dates.addWidget(date_pick)
        scope_form.addRow("Tarih aralığı", dates)
        date_note = Q.QLabel("Boş bırakılırsa grafikte erişilebilen geçmiş kullanılır. Özel tarihler yalnız doğrulanmış tarih desteği varsa çalıştırılır.")
        date_note.setWordWrap(True)
        scope_form.addRow(date_note)
        self.field_errors = Q.QLabel("")
        self.field_errors.setWordWrap(True)
        self.field_errors.setStyleSheet(f"color:{STATUS_ERROR}")
        scope_form.addRow(self.field_errors)
        criteria_frame = Q.QFrame()
        criteria = Q.QGridLayout(criteria_frame)
        self.min_trades = Q.QSpinBox(); self.min_trades.setRange(0, 1_000_000); self.min_trades.setValue(60); self.min_trades.setPrefix("İşlem ≥ ")
        self.min_pf = Q.QDoubleSpinBox(); self.min_pf.setRange(0, 100); self.min_pf.setValue(1.4); self.min_pf.setPrefix("PF ≥ ")
        self.min_win = Q.QDoubleSpinBox(); self.min_win.setRange(0, 100); self.min_win.setValue(40); self.min_win.setPrefix("WR ≥ "); self.min_win.setSuffix("%")
        self.max_dd = Q.QDoubleSpinBox(); self.max_dd.setRange(0, 100); self.max_dd.setValue(5); self.max_dd.setPrefix("DD < "); self.max_dd.setSuffix("%")
        self.min_net = Q.QDoubleSpinBox(); self.min_net.setRange(-1_000_000_000, 1_000_000_000); self.min_net.setPrefix("Net ≥ ")
        self.max_daily_loss = Q.QDoubleSpinBox(); self.max_daily_loss.setRange(0, 100); self.max_daily_loss.setValue(5); self.max_daily_loss.setPrefix("Kapanış günü ≤ "); self.max_daily_loss.setSuffix("%")
        self.max_total_loss = Q.QDoubleSpinBox(); self.max_total_loss.setRange(0, 100); self.max_total_loss.setValue(10); self.max_total_loss.setPrefix("Kapanış toplam ≤ "); self.max_total_loss.setSuffix("%")
        for index, widget in enumerate((self.min_trades, self.min_pf, self.min_win, self.max_dd,
                                        self.min_net, self.max_daily_loss, self.max_total_loss)):
            widget.setMinimumWidth(105)
            criteria.addWidget(widget, index // 2, index % 2)
        self.ftmo_risk_check = SwitchToggle("FTMO gün içi kayıp sınırlarını uygula (equity kanıtı gerekir)")
        self.ftmo_risk_check.setChecked(False)
        criteria.addWidget(self.ftmo_risk_check, 4, 0, 1, 2)
        for widget in (self.max_daily_loss, self.max_total_loss):
            widget.setEnabled(False)
            self.ftmo_risk_check.toggled.connect(widget.setEnabled)
        self.criteria_toggle = DisclosureButton("Başarı kriterleri")
        criteria_frame.setVisible(False)
        self.criteria_toggle.toggled.connect(criteria_frame.setVisible)
        self.criteria_toggle.toggled.connect(self._update_criteria_toggle)
        for field in (self.min_trades, self.min_pf, self.max_dd):
            field.valueChanged.connect(self._update_criteria_toggle)
        self._update_criteria_toggle()
        advanced_cost_toggle = DisclosureButton("Maliyet ve input eşlemesi")
        self.advanced_cost_toggle = advanced_cost_toggle
        advanced_cost = Q.QFrame()
        advanced_cost_form = Q.QFormLayout(advanced_cost)
        advanced_cost.setVisible(False)
        advanced_cost_toggle.toggled.connect(advanced_cost.setVisible)
        costs = Q.QGridLayout()
        self.commission = Q.QDoubleSpinBox(); self.commission.setRange(0, 100); self.commission.setDecimals(4); self.commission.setPrefix("Komisyon % ")
        self.slippage = Q.QSpinBox(); self.slippage.setRange(0, 10000); self.slippage.setPrefix("Slippage tick ")
        self.spread = Q.QDoubleSpinBox(); self.spread.setRange(0, 100000); self.spread.setDecimals(5); self.spread.setPrefix("Spread ")
        self.initial_capital = Q.QDoubleSpinBox(); self.initial_capital.setRange(1, 1_000_000_000); self.initial_capital.setValue(100000); self.initial_capital.setPrefix("Sermaye ")
        self.position_size = Q.QDoubleSpinBox(); self.position_size.setRange(0.00001, 1_000_000_000); self.position_size.setValue(1); self.position_size.setPrefix("Pozisyon ")
        self.cost_scenario = Q.QComboBox(); self.cost_scenario.addItems(COST_SCENARIOS.keys())
        self.cost_templates = dict(self.store.app_settings().get("cost_templates", {}))
        self.cost_scenario.addItems(self.cost_templates.keys())
        self.cost_scenario.currentTextChanged.connect(self.apply_cost_template)
        save_cost = Q.QPushButton("Maliyet şablonunu kaydet"); save_cost.clicked.connect(self.save_cost_template)
        self.save_cost_button = save_cost
        for index, widget in enumerate((self.initial_capital, self.position_size, self.commission,
                                        self.spread, self.slippage, self.cost_scenario)):
            costs.addWidget(widget, index // 2, index % 2)
        costs.addWidget(save_cost, 3, 0, 1, 2)
        advanced_cost_form.addRow("TradingView maliyetleri", costs)
        advanced_cost_form.addRow("Risk taraması", Q.QLabel(
            "Risk bütçesini strateji inputları listesinden seçin; buradaki maliyet alanları risk parametresini değiştirmez."))
        cost_ids = Q.QGridLayout()
        self.capital_input_id = Q.QLineEdit(); self.capital_input_id.setPlaceholderText("Sermaye in_N (opsiyonel)")
        self.position_input_id = Q.QLineEdit(); self.position_input_id.setPlaceholderText("Pozisyon in_N")
        self.commission_input_id = Q.QLineEdit(); self.commission_input_id.setPlaceholderText("Komisyon in_N (opsiyonel)")
        self.spread_input_id = Q.QLineEdit(); self.spread_input_id.setPlaceholderText("Spread in_N")
        self.slippage_input_id = Q.QLineEdit(); self.slippage_input_id.setPlaceholderText("Slippage in_N (opsiyonel)")
        self.cost_input_choices = {}
        cost_fields = (
            ("Başlangıç sermayesi", "initial_capital", self.capital_input_id),
            ("Pozisyon boyutu", "position_size", self.position_input_id),
            ("Komisyon", "commission_value", self.commission_input_id),
            ("Spread", "spread", self.spread_input_id),
            ("Kayma", "slippage", self.slippage_input_id),
        )
        for index, (label, key, internal_id) in enumerate(cost_fields):
            choice = Q.QComboBox()
            choice.setMinimumWidth(220)
            choice.setToolTip("Pine stratejisindeki ilgili inputu adıyla seçin. Emin değilseniz eşlemeyin.")
            choice.addItem("Eşleme yok", "")
            choice.currentIndexChanged.connect(
                lambda _index, source=choice, destination=internal_id:
                    destination.setText(str(source.currentData() or ""))
            )
            self.cost_input_choices[key] = choice
            cost_ids.addWidget(Q.QLabel(label), index // 2, (index % 2) * 2)
            cost_ids.addWidget(choice, index // 2, (index % 2) * 2 + 1)
        advanced_cost_form.addRow("Stratejideki karşılığı", cost_ids)
        box.addLayout(context_form)
        self.session_variants_check = SwitchToggle(
            "Aynı sembol/TF için araştırılmış session ayarlarını birlikte tara"
        )
        self.session_variants_check.setToolTip(
            "Yalnız bu Pine sürümünde ve seçili sembol/zaman diliminde gözlenmiş paketler. "
            "Geçmiş performansın tekrarlanacağı anlamına gelmez."
        )
        self.session_variants_check.toggled.connect(self.preview_plan)
        instructions = Q.QLabel("Hangi ayarları deneyelim? Diğer ayarlar mevcut değerlerinde kalır. Öneriler başlangıç içindir; en iyi değer garantisi değildir.", objectName="subtitle")
        instructions.setWordWrap(True)
        box.addWidget(instructions)
        self.auto_excluded_notice = Q.QLabel("", objectName="status")
        self.auto_excluded_notice.setWordWrap(True)
        self.auto_excluded_notice.hide()
        box.addWidget(self.auto_excluded_notice)
        self.plan_empty = Q.QLabel("Inputları görmek için bir proje seçin; Pine kodu 'Yeni proje' bölümünde eklenir.", objectName="subtitle")
        box.addWidget(self.plan_empty)
        self.plan_inputs = Q.QTableWidget(0, 7)
        self.plan_inputs.setAccessibleName("Strateji inputları")
        self.plan_inputs.setHorizontalHeaderLabels(["Teknik ID", "Input", "Varsayılan", "Karar", "Tarama değerleri", "Kaynak", "Not"])
        # Source and explanation live in the selected-input panel. Keep their
        # model cells for provenance, but avoid a horizontal scroll on 1280px.
        for hidden_column in (0, 5, 6):
            self.plan_inputs.setColumnHidden(hidden_column, True)
        self.plan_inputs.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.plan_inputs.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.plan_inputs.horizontalHeader().setStretchLastSection(False)
        self.plan_inputs.horizontalHeader().setSectionResizeMode(4, Q.QHeaderView.Stretch)
        self.plan_inputs.setColumnWidth(1, 160)
        self.plan_inputs.setColumnWidth(2, 80); self.plan_inputs.setColumnWidth(3, 190)
        self.plan_inputs.setColumnWidth(4, 200)
        self.plan_inputs.itemDoubleClicked.connect(self.edit_scan_values)
        self.plan_inputs.itemSelectionChanged.connect(self.refresh_input_detail)
        self.plan_inputs.setMinimumHeight(180)
        self.plan_inputs.setMaximumHeight(360)
        self.plan_inputs.hide()
        input_workspace = Q.QWidget()
        input_workspace_layout = Q.QVBoxLayout(input_workspace)
        input_workspace_layout.setContentsMargins(0, 0, 0, 0)
        input_workspace_layout.addWidget(self.plan_inputs, 1)
        self.input_detail_panel = Q.QFrame()
        self.input_detail_panel.setMinimumWidth(0)
        self.input_detail_panel.setStyleSheet(
            "QFrame { background:#fffdf8; border:1px solid #ddc9a3; border-radius:6px; }"
            "QLabel { border:0; }"
        )
        detail_layout = Q.QVBoxLayout(self.input_detail_panel)
        self.input_detail_title = Q.QLabel("Bir input seçin", objectName="subtitle")
        self.input_detail_values = Q.QLabel("")
        self.input_detail_note = Q.QLabel("")
        for label in (self.input_detail_title, self.input_detail_values, self.input_detail_note):
            label.setTextFormat(QtCore.Qt.PlainText)
            label.setWordWrap(True)
            detail_layout.addWidget(label)
        self.input_detail_mode = DecisionChoice()
        self.input_detail_mode.setAccessibleName("Seçili input için tarama kararı")
        self.input_detail_mode.addItems(["Sabit bırak", "Tara", "Hariç tut"])
        self.input_detail_mode.currentIndexChanged.connect(self.apply_input_detail_mode)
        detail_layout.addWidget(self.input_detail_mode)
        self.input_numeric_range = Q.QWidget()
        numeric_form = Q.QFormLayout(self.input_numeric_range)
        numeric_form.setContentsMargins(0, 0, 0, 0)
        self.input_range_start = Q.QLineEdit()
        self.input_range_start.setAccessibleName("Tarama aralığı başlangıcı")
        self.input_range_stop = Q.QLineEdit()
        self.input_range_stop.setAccessibleName("Tarama aralığı bitişi")
        self.input_range_step = Q.QLineEdit()
        self.input_range_step.setAccessibleName("Tarama aralığı adımı")
        for label, field in (("Başlangıç", self.input_range_start),
                             ("Bitiş", self.input_range_stop),
                             ("Adım", self.input_range_step)):
            numeric_form.addRow(label, field)
        apply_range = Q.QPushButton("Aralığı uygula", objectName="primary")
        self.apply_range_button = apply_range
        apply_range.clicked.connect(self.apply_input_numeric_range)
        numeric_form.addRow(apply_range)
        detail_layout.addWidget(self.input_numeric_range)
        detail_edit = Q.QPushButton("Önerilen aralığı değiştir")
        self.input_detail_edit = detail_edit
        detail_edit.clicked.connect(self.edit_selected_scan_values)
        detail_layout.addWidget(detail_edit)
        detail_layout.addStretch()
        input_workspace_layout.addWidget(self.input_detail_panel)
        detail_toggle = DisclosureButton("Seçili ayarın değerlerini düzenle")
        self.input_detail_toggle = detail_toggle
        detail_toggle.toggled.connect(self.input_detail_panel.setVisible)
        input_workspace_layout.insertWidget(1, detail_toggle)
        self.input_detail_panel.hide()
        self.input_workspace = input_workspace
        input_workspace.hide()
        box.addWidget(input_workspace, 1)
        scope_title = Q.QLabel("Test koşulları", objectName="sectionTitle")
        scope_frame = Q.QFrame()
        self.scope_frame = scope_frame
        scope_box = Q.QVBoxLayout(scope_frame)
        scope_box.setContentsMargins(8, 3, 8, 6)
        scope_box.setSpacing(8)
        from .run_choice import RunChoice
        self.run_choice = RunChoice(self.store)
        self.run_choice.restore_requested.connect(self._restore_run_plan)
        scope_box.addWidget(self.run_choice)
        scope_box.addLayout(scope_form)
        self.scan_advanced = Q.QWidget()
        advanced_box = Q.QVBoxLayout(self.scan_advanced)
        sampling_form = Q.QFormLayout()
        self.scan_method = Q.QComboBox()
        self.scan_method.addItem("Tam tarama", "cartesian")
        self.scan_method.addItem("Tohumlu örnekleme", "sample")
        self.scan_method.addItem("Kaba→ince: kaba aşama", "coarse")
        self.sample_budget = Q.QLineEdit("1000")
        self.sample_seed = Q.QLineEdit("0")
        self.sample_budget.setEnabled(False)
        self.sample_seed.setEnabled(False)
        sampling_form.addRow("Tarama yöntemi", self.scan_method)
        sampling_form.addRow("Örnekleme test bütçesi", self.sample_budget)
        sampling_form.addRow("Örnekleme tohumu", self.sample_seed)
        self.sampling_guide = Q.QPushButton("? Tarama yöntemi rehberi")
        sampling_form.addRow(self.sampling_guide)
        self.refinement_detach = Q.QPushButton("Aday bağlantısını kaldır; bağımsız plan kullan")
        self.refinement_detach.setEnabled(False)
        self.refinement_detach.clicked.connect(self.detach_refinement)
        sampling_form.addRow(self.refinement_detach)
        advanced_box.addLayout(sampling_form)
        from .constraint_editor import ConstraintEditor
        self.constraint_editor = ConstraintEditor()
        advanced_box.addWidget(self.constraint_editor)
        self.cancel_count_button = Q.QPushButton("Sayımı iptal et")
        self.cancel_count_button.hide()
        self.cancel_count_button.clicked.connect(self._cancel_or_retry_count)
        advanced_box.addWidget(self.cancel_count_button)
        self.constraint_editor.changed.connect(self.preview_plan)
        def sampling_changed(*_args):
            enabled = self.scan_method.currentData() == "sample"
            self.sample_budget.setEnabled(enabled)
            self.sample_seed.setEnabled(enabled)
            self.preview_plan()
        self.scan_method.currentIndexChanged.connect(sampling_changed)
        self.sample_budget.textChanged.connect(self.preview_plan)
        self.sample_seed.textChanged.connect(self.preview_plan)
        advanced_box.addWidget(self.criteria_toggle)
        advanced_box.addWidget(criteria_frame)
        advanced_box.addWidget(advanced_cost_toggle)
        advanced_box.addWidget(advanced_cost)
        advanced_box.addWidget(self.session_variants_check)
        advanced_box.addWidget(self.manual_strategy_row)
        worker_tools = Q.QPushButton("TradingView hazırlık ayrıntıları")
        self.preparation_details_button = worker_tools
        worker_tools.clicked.connect(lambda: self._show_auxiliary(3, "TradingView hazırlığı"))
        advanced_box.addWidget(worker_tools)
        self.scan_advanced.hide()
        advanced_toggle = DisclosureButton("Gelişmiş ayarlar")
        self.scan_advanced_toggle = advanced_toggle
        advanced_toggle.toggled.connect(self.scan_advanced.setVisible)
        scope_box.addWidget(advanced_toggle)
        scope_box.addWidget(self.scan_advanced)
        position = box.indexOf(input_workspace)
        box.insertWidget(position, scope_title)
        box.insertWidget(position + 1, scope_frame)
        action_bar = Q.QFrame()
        action_layout = Q.QVBoxLayout(action_bar)
        action_layout.setContentsMargins(12, 8, 12, 8)
        action_layout.setSpacing(5)
        actions = Q.QHBoxLayout()
        self.edit_input_button = Q.QPushButton("Seçili aralığı değiştir")
        self.edit_input_button.clicked.connect(self.edit_selected_scan_values)
        preview = Q.QPushButton("Özeti güncelle"); preview.clicked.connect(self.preview_plan)
        self.plan_preview_button = preview
        enqueue = Q.QPushButton("Hazırla ve başlat", objectName="primary"); enqueue.clicked.connect(self.prepare_and_start)
        self.enqueue_plan_button = enqueue
        enqueue.setEnabled(False)
        actions.addWidget(self.edit_input_button); actions.addWidget(preview)
        actions.addWidget(enqueue); actions.addStretch()
        self.cancel_queue_button = Q.QPushButton("Kuyruk hazırlığını iptal et")
        self.cancel_queue_button.hide()
        self.cancel_queue_button.clicked.connect(self._cancel_plan_admission)
        actions.addWidget(self.cancel_queue_button)
        self.edit_input_button.hide()
        preview.hide()  # The preview updates as fields change.
        fix = Q.QPushButton("Eksik alana git")
        self.missing_field_button = fix
        fix.clicked.connect(self.focus_missing_field)
        actions.addWidget(fix)
        stop = Q.QPushButton("Durdur")
        self.scan_stop_button = stop
        stop.clicked.connect(self.stop_workers)
        actions.addWidget(stop)
        self.plan_status = Q.QLabel("Bir proje seçin", objectName="status")
        self.plan_status.setWordWrap(True)
        self.plan_factors = Q.QLabel("", objectName="subtitle")
        self.plan_factors.setAccessibleName("İş yükü çarpanları")
        self.plan_factors.setWordWrap(True)
        action_layout.addWidget(self.plan_status)
        action_layout.addWidget(self.plan_factors)
        action_layout.addLayout(actions)
        for field in (self.symbols, self.timeframes, self.date_from, self.date_to):
            field.textChanged.connect(self.preview_plan)
        scroll = Q.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(Q.QFrame.NoFrame)
        scroll.setWidget(page)
        self.scan_scroll = scroll
        container = Q.QWidget()
        container_layout = Q.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(scroll, 1)
        container_layout.addWidget(action_bar)
        return container

    def _results_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Sonuçlar", "Tarama ilerlemesini ve doğrulanmış test sonuçlarını inceleyin."))
        self.results_help_button = Q.QPushButton("Grafikleri nasıl okuyacağım?")
        self.results_help_button.setToolTip("Grafiklerin anlamını ve sonuç ayrıntılarını açma yöntemini gösterir.")
        self.results_help_button.clicked.connect(lambda: self.start_guided_tour("results"))
        box.addWidget(self.results_help_button, 0, QtCore.Qt.AlignLeft)
        self.results_help_panel = Q.QFrame()
        help_layout = Q.QVBoxLayout(self.results_help_panel)
        self.results_help_text = Q.QLabel(
            "Her nokta bir testtir. Sağa doğru kâr faktörü (PF), yukarı doğru düşüş (DD) artar; "
            "noktanın büyüklüğü işlem sayısını gösterir. Yeşil, sonucun doğrulandığını belirtir; "
            "stratejinin başarılı veya gelecekte kârlı olacağını garanti etmez.\n\n"
            "Bir noktaya tıklayın veya sonuç satırına çift tıklayın: sağda ayrıntılar açılır. "
            "Sermaye eğrisi ve düşüş grafiği zaman içindeki değişimi; saat, gün ve seans grafikleri "
            "kapanmış işlemlerin dağılımını gösterir. Günlük takvimde günlerin kâr/zararını inceleyebilirsiniz. "
            "Grafiklerin üzerine gelerek değerleri okuyun.\n\n"
            "Filtreler görünen sonuçları daraltır. Dışa aktarırken seçili veya filtrelenmiş kapsamı kontrol edin.")
        self.results_help_text.setWordWrap(True)
        help_layout.addWidget(self.results_help_text)
        self.results_help_dismiss = Q.QPushButton("Anladım")
        self.results_help_dismiss.clicked.connect(self.dismiss_results_help)
        help_layout.addWidget(self.results_help_dismiss, 0, QtCore.Qt.AlignRight)
        self.results_help_panel.hide()  # Guidance now lives in anchored tour popups.
        box.addWidget(self.results_help_panel)
        controls = Q.QHBoxLayout()
        self.result_project = Q.QComboBox(); self.result_project.setMaximumWidth(260)
        self.result_project.currentIndexChanged.connect(self.refresh_results)
        self.result_filter = Q.QComboBox(); self.result_filter.addItems(["Tümü", "Başarılı", "dayanıklı", "hassas", "elenmiş", "geçersiz"])
        self.result_filter.setMaximumWidth(160)
        self.result_filter.currentIndexChanged.connect(self.refresh_results)
        filter_button = DisclosureButton("Filtrele")
        self.result_filter_toggle = filter_button
        filter_button.setIcon(funnel_icon())
        filter_button.setCheckable(True)
        filter_button.toggled.connect(lambda checked: self.result_filter_panel.setVisible(checked))
        self.saved_result_filter = Q.QComboBox()
        self.saved_result_filter.setMaximumWidth(180)
        self.saved_result_filter.addItem("Kayıtlı filtre seç", None)
        self.saved_result_filter.currentIndexChanged.connect(self.apply_saved_result_filter)
        save_filter = Q.QPushButton("Filtreyi kaydet")
        self.result_save_filter_button = save_filter
        save_filter.clicked.connect(self.save_result_filter)
        export = Q.QPushButton("Dışa aktar", objectName="primary"); export.clicked.connect(self.export_current_results)
        self.result_export_button = export
        self.result_compare = Q.QPushButton("Seçilenleri karşılaştır")
        self.result_compare.clicked.connect(self.compare_selected_results)
        self.result_validate = Q.QPushButton("Aşamalı doğrula")
        self.result_validate.clicked.connect(self.validate_selected_results)
        self.result_refine = Q.QPushButton("Adaylardan ayrıntılı tara")
        self.result_refine.clicked.connect(self.refine_selected_results)
        self.result_period = Q.QPushButton("Ayrı dönemde doğrula")
        self.result_period.clicked.connect(lambda: self.period_selected_results(training=False))
        self.result_next_training = Q.QPushButton("Sonraki eğitim dönemi")
        self.result_next_training.clicked.connect(lambda: self.period_selected_results(training=True))
        retry = Q.QPushButton("Hatalıları yeniden sırala"); retry.clicked.connect(self.retry_result_project)
        self.result_retry_button = retry
        controls.addWidget(self.result_project); controls.addWidget(self.result_filter)
        controls.addWidget(filter_button); controls.addWidget(export)
        controls.addStretch()
        box.addLayout(controls)
        saved_controls = Q.QHBoxLayout()
        saved_controls.addWidget(self.saved_result_filter)
        saved_controls.addWidget(save_filter)
        saved_controls.addStretch()
        box.addLayout(saved_controls)
        result_actions = Q.QHBoxLayout()
        result_actions.addWidget(self.result_compare)
        result_actions.addWidget(self.result_validate)
        result_actions.addWidget(retry)
        result_actions.addStretch()
        box.addLayout(result_actions)
        refinement_actions = Q.QHBoxLayout()
        refinement_actions.addWidget(self.result_refine)
        refinement_actions.addStretch()
        box.addLayout(refinement_actions)
        period_actions = Q.QHBoxLayout()
        period_actions.addWidget(self.result_period); period_actions.addWidget(self.result_next_training)
        period_actions.addStretch(); box.addLayout(period_actions)
        self.result_filter_panel = Q.QFrame()
        filter_layout = Q.QGridLayout(self.result_filter_panel)
        self.filter_pf = Q.QDoubleSpinBox(); self.filter_pf.setRange(0, 100); self.filter_pf.setPrefix("PF ≥ ")
        self.filter_dd = Q.QDoubleSpinBox(); self.filter_dd.setRange(0, 100); self.filter_dd.setValue(100); self.filter_dd.setPrefix("DD ≤ "); self.filter_dd.setSuffix("%")
        self.filter_trades = Q.QSpinBox(); self.filter_trades.setRange(0, 1_000_000); self.filter_trades.setPrefix("İşlem ≥ ")
        self.filter_win = Q.QDoubleSpinBox(); self.filter_win.setRange(0, 100); self.filter_win.setPrefix("WR ≥ "); self.filter_win.setSuffix("%")
        self.filter_net = Q.QDoubleSpinBox(); self.filter_net.setRange(-1_000_000_000, 1_000_000_000); self.filter_net.setValue(-1_000_000_000); self.filter_net.setPrefix("Net ≥ ")
        self.filter_symbol = Q.QLineEdit(); self.filter_symbol.setPlaceholderText("Sembol ara")
        self.filter_tf = Q.QLineEdit(); self.filter_tf.setPlaceholderText("Zaman dilimi")
        self.filter_evidence = Q.QComboBox(); self.filter_evidence.addItems(["Tümü", "Doğrulanmış", "Doğrulanmamış"])
        self.filter_cost_scenario = Q.QComboBox(); self.filter_cost_scenario.addItem("Tüm maliyet senaryoları", "Tümü")
        self.filter_dates = SwitchToggle("Tarih aralığı")
        self.filter_from = Q.QDateEdit(); self.filter_from.setCalendarPopup(True); self.filter_from.setDate(QtCore.QDate.currentDate().addYears(-1))
        self.filter_to = Q.QDateEdit(); self.filter_to.setCalendarPopup(True); self.filter_to.setDate(QtCore.QDate.currentDate())
        for index, widget in enumerate((self.filter_pf, self.filter_dd, self.filter_trades,
                                        self.filter_win, self.filter_net, self.filter_symbol,
                                        self.filter_tf, self.filter_evidence, self.filter_cost_scenario,
                                        self.filter_dates,
                                        self.filter_from, self.filter_to)):
            filter_layout.addWidget(widget, index // 4, index % 4)
            signal = getattr(widget, "valueChanged", None) or getattr(widget, "textChanged", None)
            if signal is None: signal = getattr(widget, "currentIndexChanged", None)
            if signal is None: signal = getattr(widget, "toggled", None)
            if signal is None: signal = getattr(widget, "dateChanged", None)
            if signal is not None: signal.connect(self.refresh_results)
        box.addWidget(self.result_filter_panel)
        self.result_filter_panel.hide()
        self.result_active_filters = Q.QFrame()
        self.result_active_filters.setSizePolicy(Q.QSizePolicy.Expanding, Q.QSizePolicy.Maximum)
        active_layout = Q.QHBoxLayout(self.result_active_filters)
        active_layout.setContentsMargins(0, 2, 0, 4)
        self.result_chip_grid = Q.QGridLayout()
        self.result_chip_grid.setHorizontalSpacing(6)
        self.result_chip_grid.setVerticalSpacing(6)
        active_layout.addLayout(self.result_chip_grid)
        active_layout.addStretch(1)
        self.result_clear_filters = Q.QPushButton("Filtreleri temizle")
        self.result_clear_filters.setAccessibleName("Tüm sonuç filtrelerini temizle")
        self.result_clear_filters.clicked.connect(self.clear_result_filters)
        active_layout.addWidget(self.result_clear_filters, 0, QtCore.Qt.AlignTop)
        box.addWidget(self.result_active_filters)
        self.result_empty = Q.QLabel("Henüz tarama sonucu yok. Önce tarama planı hazırlayın.", objectName="subtitle")
        box.addWidget(self.result_empty)
        self.result_scatter = ResultScatterChart(page)
        self.result_scatter.selected.connect(self.open_result_details_by_id)
        self.results_table = Q.QTableWidget(0, 10)
        self.results_table.setHorizontalHeaderLabels(
            ["Görev", "Sembol", "TF", "Sınıf", "İşlem", "PF", "WR %", "DD %", "Net", "Kanıt"]
        )
        for column, explanation in {
            2: "Testin zaman dilimi.",
            5: "Kâr faktörü: toplam kazancın toplam kayba oranı. Tek başına başarı ölçütü değildir.",
            6: "Kazançla kapanan işlemlerin yüzdesi.",
            7: "En yüksek sermayeden sonraki en büyük düşüş yüzdesi.",
            9: "Doğrulandı: test ayarları ve rapor kontrol edildi; kârlılık garantisi değildir.",
        }.items():
            self.results_table.horizontalHeaderItem(column).setToolTip(explanation)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((95, 145, 46, 80, 55, 55, 62, 62, 88)):
            self.results_table.setColumnWidth(column, width)
        # Keep decision metrics and evidence visible when the detail dock narrows the table.
        result_header = self.results_table.horizontalHeader()
        for position, logical_column in enumerate((0, 5, 6, 7, 8, 9, 1, 2, 3, 4)):
            result_header.moveSection(result_header.visualIndex(logical_column), position)
        self.results_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(Q.QAbstractItemView.ExtendedSelection)
        self.results_table.setSortingEnabled(True)
        self.results_table.hide()
        self.results_table.selectionModel().selectionChanged.connect(self.update_result_actions)
        self.results_table.doubleClicked.connect(self.show_result_details)
        box.addWidget(self.results_table, 2)
        box.addWidget(self.result_scatter)
        box.addWidget(Q.QLabel("Son olaylar", objectName="subtitle"))
        self.result_events_empty = Q.QLabel("Henüz olay kaydı yok.", objectName="subtitle")
        self.result_events_empty.setSizePolicy(Q.QSizePolicy.Preferred, Q.QSizePolicy.Maximum)
        self.result_events_empty.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        box.addWidget(self.result_events_empty)
        self.events_table = Q.QTableWidget(0, 5)
        self.events_table.setHorizontalHeaderLabels(["Seviye", "Worker", "Görev", "Mesaj", "Ekran görüntüsü"])
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.events_table.cellDoubleClicked.connect(self.check_event_evidence)
        box.addWidget(self.events_table, 1)
        scroll = Q.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(Q.QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def show_results_help(self):
        self.results_help_panel.show()

    def dismiss_results_help(self):
        self.store.save_app_settings({"results_help_dismissed_v1": True})
        self.results_help_panel.hide()

    def _first_use_help(self, key, title, text):
        Q = self.QtWidgets
        container = Q.QWidget()
        layout = Q.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = Q.QPushButton(title)
        button.setToolTip("Bu ekranın kullanım ipuçlarını ayrı bir pencerede açar.")
        layout.addWidget(button, 0, QtCore.Qt.AlignLeft)
        panel = Q.QFrame()
        contents = Q.QVBoxLayout(panel)
        label = Q.QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(QtCore.Qt.PlainText)
        contents.addWidget(label)
        dismiss = Q.QPushButton("Anladım")
        setting = "usage_help_" + key + "_dismissed_v1"
        def close_help():
            self.store.save_app_settings({setting: True})
            panel.hide()
        dismiss.clicked.connect(close_help)
        def open_help():
            self.start_guided_tour(key)
        button.clicked.connect(open_help)
        contents.addWidget(dismiss, 0, QtCore.Qt.AlignRight)
        layout.addWidget(panel)
        panel.hide()  # Retain legacy text for compatibility, not as a long inline guide.
        if not hasattr(self, "usage_help"):
            self.usage_help = {}
        self.usage_help[key] = (panel, button, dismiss, label)
        return container

    def start_guided_tour(self, key, automatic=False):
        setting = "guided_tour_" + key + "_v1"
        if automatic and (not self.window.isVisible() or self.store.app_settings().get(setting)):
            return
        previous = getattr(self, "guided_tour", None)
        if previous is not None:
            previous.finish()
        if key == "strategies":
            steps = [
                (self.strategy_list, "Bir strateji seç", "Kayıtlı stratejini buradan seçebilirsin. Yeni strateji eklemek için aşağıdaki adımlarla devam et.", None),
                (self.pine_source, "Pine kodunu yapıştır", "TradingView strategy kodunu bu alana yapıştır. Ayarlar otomatik okunacak. Kod girilince İleri açılır.", lambda: bool(self.pine_source.toPlainText().strip())),
                (self.project_name, "Stratejine ad ver", "Bu çalışmayı tanıyacağın bir ad yaz. Kayıtlı strateji seçtiysen mevcut adı kullanabilirsin.", lambda: bool(self.project_name.text().strip())),
                (self.strategy_save_button, "Stratejiyi kaydet", "Bu düğmeye bas. Aynı kod yeniden kaydedilirse yeni kopya oluşmaz. Kayıt tamamlanınca İleri açılır.", lambda: self._saved_project_id is not None),
                (self.prepare_saved_button, "Taramaya geç", "Taramayı hazırla düğmesi seni Tarama ekranına götürür. Orada sembol, zaman dilimi ve denenecek değerleri seçeceksin.", None),
            ]
        elif key == "scan":
            steps = [
                (self.plan_project, "Stratejini kontrol et", "Taranacak strateji burada seçili olmalı.", lambda: self.plan_project.currentData() is not None),
                (self.symbols, "Sembol seç", "Yanındaki Seç düğmesinden piyasayı ara ve ekle. Örneğin BIST:XU030D1!. Sembol seçilince İleri açılır.", lambda: bool(self.symbols.text().strip())),
                (self.timeframes, "Zaman dilimi seç", "Yanındaki Seç düğmesiyle örneğin 15 dakika seç. Zaman dilimi seçilince İleri açılır.", lambda: bool(self.timeframes.text().strip())),
                (self.date_from, "Test dönemini belirle", "Tarih aralığı isteğe bağlıdır. Boş bırakınca erişilebilen geçmiş kullanılır; belirli dönem için başlangıç ve bitiş seç.", None),
                (self.plan_inputs, "Denenecek ayarı seç", "Fast EMA satırında Farklı değerleri dene seç. Değerleri 7, 8, 9 yaparsan üç kombinasyon oluşur. Diğer ayarları Sabit tut bırakabilirsin.", None),
                (self.parallel_count, "Paralel grafik sayısını seç", "Bir grafikle başlayabilir veya aynı anda birden fazla test çalıştırabilirsin. Kaynakları ölç öneri verir; hızı Sonuçlar ekranında test/saat olarak ölçeriz. Her grafik bağımsız hazırlanır ve doğrulanır.", None),
                (self.enqueue_plan_button, "Özeti kontrol edip başlat", "Hazırla ve başlat ayrı test grafiğini hazırlar ve değişiklikleri onayına sunar. Tur bu düğmeye senin yerine basmaz. Eksik varsa Eksik alana git düğmesini kullan.", None),
            ]
        else:
            target = self.usage_help["detail"][1] if key == "detail" else self.results_help_button
            steps = [(target, "Sonuçları incele", "Her nokta bir testtir. Bir sonucu seçerek testte kullanılan ayarlara, işlem eğrisine ve teknik doğrulamaya bak. Yüksek kâr tek başına güvenilirlik garantisi değildir.", None)]
            if key == "results":
                steps.extend([
                    (self.result_filter, "Sonuçları filtrele", "Tümü veya Başarılı gibi filtrelerle görmek istediğin sonuçları seç. Filtre seçmek kayıtlı sonuçları değiştirmez.", None),
                    (self.result_scatter, "Bir testi aç", "Her nokta bir testtir. Noktaya tıklayarak kullanılan ayarları ve sonuç ayrıntılarını aç. Yeşil doğrulanmış demektir, gelecekte kâr garantisi değildir.", None),
                ])
        from .help_system import TourSpec
        # Registered controls share the same wording across tooltip, F1 and
        # onboarding; readiness remains a read-only condition.
        steps = [(target, title, text + "\n\n" + spec.tooltip if
                  (spec := self.help_registry.resolve(target)) else text, ready)
                 for target, title, text, ready in steps]
        self.help_registry.register_tour(TourSpec(
            key, 1, tuple(steps), (setting,),
            frozenset({3} if key == "strategies" else {1, 2} if key == "scan" else set())))
        self.guided_tour = self.help_registry.start_tour(
            key, automatic=automatic, finished=lambda: setattr(self, "guided_tour", None))

    def _research_page(self):
        Q = self.QtWidgets
        self._research_catalog = self.store.app_settings().get("imported_research_catalog") or load_catalog()
        self._visible_research_catalog = self._research_catalog
        research_available = self._research_catalog.get("available", True)
        page = Q.QWidget(); box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header(
            "Araştırma presetleri", (
                "23 Eylül session sonuçları; ağır maliyet geçti, alternatif sağlayıcı bekliyor."
                if research_available else
                "Yerel araştırma arşivi bu kurulumda yok; yeni proje ve tarama işlevleri kullanılabilir."
            )
        ))
        if research_available:
            box.addWidget(ResearchFunnelChart(self._research_catalog, page))
        self.research_table = Q.QTableWidget(len(self._research_catalog["records"]), 9)
        self.research_table.setHorizontalHeaderLabels(
            ["Preset", "Session seçimi", "Sembol", "TF/FVG", "Dönem", "İşlem", "PF", "DD %", "Kanıt"]
        )
        self.research_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.research_table.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.research_table.setSelectionMode(Q.QAbstractItemView.ExtendedSelection)
        self.research_table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((110, 280, 130, 65, 115, 58, 58, 58)):
            self.research_table.setColumnWidth(column, width)
        self.research_table.verticalHeader().setDefaultSectionSize(31)
        for index, record in enumerate(self._research_catalog["records"]):
            period = record["period_label"]
            start, end = period.split(" - ", 1)
            compact_period = f"{start[5:7]}/{start[2:4]} - {end[5:7]}/{end[2:4]}"
            values = (record["preset_id"], describe_session_choice(record), record["symbol"],
                      f'{record["chart_tf"]}/{record["fvg_tf"]}', compact_period,
                      record["heavy_metrics"]["trades"],
                      f'{record["heavy_metrics"]["pf"]:.3f}',
                      f'{record["heavy_metrics"]["dd"]:.2f}', "Sağlayıcı bekliyor")
            for column, value in enumerate(values):
                cell = Q.QTableWidgetItem(str(value))
                if column == 1:
                    cell.setToolTip(f"{describe_session_choice(record)}\nKaynak kod: {record['variant']}")
                self.research_table.setItem(index, column, cell)
        self.research_table.itemSelectionChanged.connect(self.show_research_details)
        self.research_table.doubleClicked.connect(self.open_research_details)
        self.research_table.setMinimumHeight(275)
        self.research_table.setMaximumHeight(275)
        box.addWidget(self.research_table)
        controls = Q.QHBoxLayout()
        self.research_project = Q.QComboBox()
        self.research_project.currentIndexChanged.connect(self.refresh_research_evidence)
        self.research_provider_symbol = Q.QLineEdit()
        self.research_provider_symbol.setPlaceholderText("Alternatif sağlayıcının tam TradingView sembolü")
        prepare = Q.QPushButton("Seçilenlerin sağlayıcı görevlerini hazırla", objectName="primary")
        self.research_prepare_button = prepare
        prepare.clicked.connect(self.prepare_research_provider_tasks)
        export_pdf = Q.QPushButton("Araştırma PDF'i")
        self.research_pdf_button = export_pdf
        export_pdf.clicked.connect(self.export_research_report)
        export_success = Q.QPushButton("Arşiv kayıtlarını CSV/Excel indir")
        self.research_export_button = export_success
        export_success.clicked.connect(self.export_successful_research_records)
        export_raw = Q.QPushButton("Yerel ham araştırma kayıtlarını indir")
        self.research_raw_button = export_raw
        export_raw.clicked.connect(self.export_historical_records)
        for control in (prepare, export_pdf, export_success, export_raw):
            control.setEnabled(research_available)
            control.setVisible(research_available)
        export_raw.setVisible(False)  # Catalog import excludes separate raw records.
        controls.addWidget(self.research_project)
        controls.addWidget(self.research_provider_symbol, 1)
        controls.addWidget(prepare)
        box.addLayout(controls)
        exports = Q.QHBoxLayout()
        exports.addWidget(export_pdf)
        exports.addWidget(export_success)
        exports.addWidget(export_raw)
        exports.addStretch()
        box.addLayout(exports)
        self.research_status = Q.QLabel(
            ("Görev hazırlamak worker başlatmaz. DE30 ve NAS100 sağlayıcı sembolleri ayrı hazırlanır."
             if research_available else
             "Bu geçmiş araştırma isteğe bağlı yerel veridir; eksik kayıt için sonuç uydurulmaz."),
            objectName="status",
        )
        box.addWidget(self.research_status)
        if self._research_catalog.get("imported_unverified"):
            self.research_status.setText("İçe aktarılan tarihsel arşiv. Dosyadaki sonuçlar bu uygulamada yeniden doğrulanmadı; kendi testlerinden kaydettiğin presetlerden ayrıdır.")
        self.research_details = Q.QPlainTextEdit(); self.research_details.setReadOnly(True)
        self.research_details.setMinimumHeight(140)
        box.addWidget(self.research_details, 1)
        scans = " | ".join(f'{item["priority"]}. {item["name"]}' for item in self._research_catalog["next_scans"])
        note = Q.QLabel(f"Sonraki taramalar: {scans}", objectName="subtitle")
        note.setWordWrap(True); box.addWidget(note)
        if research_available:
            self.research_table.selectRow(0)
        self.show_research_details()
        scroll = Q.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(Q.QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def refresh_research_evidence(self, *_args):
        project_id = self.research_project.currentData()
        status = self.store.research_provider_status(project_id) if project_id is not None else {}
        self._visible_research_catalog = with_provider_status(self._research_catalog, status)
        labels = {"passed": "Sağlayıcı geçti", "queued": "Kuyrukta", "running": "Çalışıyor",
                  "failed": "Sağlayıcı geçmedi", "pending": "Sağlayıcı bekliyor"}
        for index, record in enumerate(self._visible_research_catalog["records"]):
            evidence = record["evidence"]["alternative_provider"]
            self.research_table.item(index, 8).setText(labels.get(evidence, evidence))
        self.show_research_details()

    def show_research_details(self):
        selected = self.research_table.selectionModel().selectedRows()
        if not selected:
            self.research_details.setPlainText("Ayar farklarını görmek için bir satır seçin.")
            return
        record = self._visible_research_catalog["records"][selected[0].row()]
        heavy, moderate = record["heavy_metrics"], record["moderate_metrics"]
        lines = [
            f'{record["id"]} | {record["symbol"]} | Grafik/FVG {record["chart_tf"]}/{record["fvg_tf"]}',
            f'Session: {describe_session_choice(record)}',
            f'Dönem: {record["period_label"]} ({record["coverage_days"]} gün)',
            f'Orta maliyet: PF {moderate["pf"]:.3f}, DD %{moderate["dd"]:.2f}, net %{moderate["net_pct"]:.2f}',
            f'Ağır maliyet: PF {heavy["pf"]:.3f}, DD %{heavy["dd"]:.2f}, net %{heavy["net_pct"]:.2f}',
            f'Alternatif sağlayıcı: {record["evidence"]["alternative_provider"]} | Demo forward: başlamadı',
            'Tarihsel testin Pine kaynak hash’i yok; aşağıdaki adlar güncel eşleme kaynağındandır.',
            '', 'Varsayılandan farklı girdiler:',
        ]
        for item in record["changed_inputs"]:
            value = "ON" if item["value"] is True else "OFF" if item["value"] is False else item["value"]
            lines.append(f'  {item["id"]}  {item["title"]}: {value}')
        for attempt in record.get("provider_attempts", []):
            lines.append(f'  Sağlayıcı görevi #{attempt["task_id"]}: {attempt["symbol"]} - {attempt["status"]}')
        lines.append('Strategy Properties: komisyon %0,04; toplam spread/kayma 10 tick.')
        self.research_details.setPlainText("\n".join(lines))

    def open_research_details(self, *_args):
        self.show_research_details()
        dialog = self.QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Preset ayrıntısı")
        dialog.resize(760, 660)
        layout = self.QtWidgets.QVBoxLayout(dialog)
        details = self.QtWidgets.QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(self.research_details.toPlainText())
        layout.addWidget(details)
        close = self.QtWidgets.QPushButton("Kapat")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        self._configure_readonly_dialog_help(dialog, layout, "research_details", (
            ("text", details, "Araştırma presetinin ayrıntıları", "Seçili yerel araştırma kaydının ayar, dönem ve kanıt açıklamasını gösterir.",
             "Metin mevcut arşiv kaydından okunur. Bu pencere yeni test yapmaz veya geçmiş kaydı yeniden doğrulamaz. Eksik dönem, kaynak veya kanıt varsa doğrulanmış gibi kabul etme; sağlayıcı kontrolü ayrı bir işlemdir."),
        ), close)
        dialog.exec()

    def prepare_research_provider_tasks(self):
        try:
            if self.supervisor and self.supervisor.running:
                raise ValueError("Görev hazırlamadan önce çalışan workerları durdurun.")
            project_id = self.research_project.currentData()
            if project_id is None:
                raise ValueError("Önce aynı Pine kaynağıyla bir proje seçin.")
            indices = sorted({index.row() for index in self.research_table.selectionModel().selectedRows()})
            ids = [self._research_catalog["records"][index]["id"] for index in indices]
            settings = self.store.settings(project_id) or {}
            tasks = provider_check_tasks(
                self._research_catalog, ids, self.store.project(project_id),
                str(settings.get("study_id") or ""), self.research_provider_symbol.text(),
            )
            inserted = self.store.enqueue_many(project_id, tasks)
            self.research_status.setStyleSheet(f"color:{STATUS_SUCCESS}")
            self.research_status.setText(f"{inserted} yeni sağlayıcı görevi hazırlandı; worker başlatılmadı.")
            self.refresh_dashboard()
            self.refresh_research_evidence()
        except ValueError as exc:
            self.research_status.setStyleSheet(f"color:{STATUS_ERROR}")
            self.research_status.setText(str(exc))

    def export_research_report(self):
        path, _ = self.QtWidgets.QFileDialog.getSaveFileName(
            self.window, "Araştırma PDF'i", "ftmo-session-arastirma-2026-09-23.pdf", "PDF (*.pdf)"
        )
        if not path:
            return
        try:
            self.refresh_research_evidence()
            count = export_research_pdf(self._visible_research_catalog, path)
            self.research_status.setText(f"{count} presetlik araştırma PDF'i kaydedildi.")
        except Exception as exc:
            self.research_status.setStyleSheet(f"color:{STATUS_ERROR}")
            self.research_status.setText(f"PDF oluşturulamadı: {exc}")

    def export_historical_records(self):
        """The historical archive is independent from new project tasks."""
        Q = self.QtWidgets
        path, selected_filter = Q.QFileDialog.getSaveFileName(
            self.window, "33.075 tarihsel ham kaydı dışa aktar",
            "ftmo-session-33075-ham-kayit.xlsx", CSV_FILTERS
        )
        if not path:
            return
        excel = "*.xlsx" in selected_filter if selected_filter else Path(path).suffix.lower() == ".xlsx"
        destination = str(Path(path).with_suffix(".xlsx" if excel else ".csv"))
        try:
            input_ids_seen = {}
            archived_count = 0
            for record in iter_historical_records():
                archived_count += 1
                for input_id in (record["payload"].get("inputs") or {}):
                    input_ids_seen.setdefault(input_id, None)
            if not archived_count:
                self.research_status.setText("Tarihsel ham arşiv bulunamadı.")
                return
            if archived_count != 33_075:
                raise RuntimeError(f"Beklenen 33.075 kayıt yerine {archived_count} kayıt okundu.")
            input_ids = tuple(input_ids_seen)
            writer = export_task_xlsx if excel else export_task_csv
            options = {} if excel else {"excel_tr": "Türkçe Excel" in selected_filter}
            count = writer(iter_historical_records(), destination, input_ids, **options)
            if count != 33_075:
                raise RuntimeError(f"Beklenen 33.075 kayıt yerine {count} kayıt yazıldı.")
            self.research_status.setText(f"{count:,} gerçek ham tarama kaydı {Path(destination).name} dosyasına kaydedildi.")
            if options.get("excel_tr"):
                self.research_status.setText(self.research_status.text() + " Excel sihirbazında UTF-8 ve noktalı virgül ayracını seçin; doğrudan açmak için XLSX kullanın.")
        except Exception as exc:
            self.research_status.setStyleSheet("color:#b54c42")
            self.research_status.setText(f"Ham kayıtlar dışa aktarılamadı: {exc}")

    def export_successful_research_records(self):
        Q = self.QtWidgets
        path, selected_filter = Q.QFileDialog.getSaveFileName(
            self.window, "Ağır maliyeti geçen 7 preset", "ftmo-7-basarili.xlsx",
            CSV_FILTERS)
        if not path:
            return
        excel = "*.xlsx" in selected_filter if selected_filter else Path(path).suffix.lower() == ".xlsx"
        destination = str(Path(path).with_suffix(".xlsx" if excel else ".csv"))
        records = iter(iter_successful_research_records(self._visible_research_catalog))
        first = next(records)
        writer = export_task_xlsx if excel else export_task_csv
        try:
            options = {} if excel else {"excel_tr": "Türkçe Excel" in selected_filter}
            count = writer(itertools.chain((first,), records), destination,
                           first["payload"]["inputs"], **options)
            self.research_status.setText(f"{count} ağır maliyet preseti kaydedildi; sağlayıcı/forward kanıtı ayrıca gösterilir.")
            if options.get("excel_tr"):
                self.research_status.setText(self.research_status.text() + " Excel sihirbazında UTF-8 ve noktalı virgül ayracını seçin; doğrudan açmak için XLSX kullanın.")
        except Exception as exc:
            self.research_status.setStyleSheet("color:#b54c42")
            self.research_status.setText(f"Başarılı presetler dışa aktarılamadı: {exc}")

    def _workers_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Çalışma sekmeleri", "Her çalışma sekmesi aynı TradingView 9222 oturumunu kullanır."))
        form = Q.QFormLayout()
        self.motor_path = Q.QLineEdit()
        self.motor_path.setPlaceholderText("Boş bırakılırsa paket içindeki gnc-zihin CDP köprüsü kullanılır")
        self.tv_executable = Q.QLineEdit(); self.tv_executable.setPlaceholderText("TradingView.exe yolu")
        self.worker_project = Q.QComboBox()
        tv_row = Q.QHBoxLayout(); tv_row.addWidget(self.tv_executable)
        find_tv = Q.QPushButton("Bul"); find_tv.clicked.connect(self.find_tradingview); tv_row.addWidget(find_tv)
        self.worker_find_tv = find_tv
        open_tv = Q.QPushButton("9222 ile aç"); open_tv.clicked.connect(self.open_tradingview); tv_row.addWidget(open_tv)
        self.worker_open_tv = open_tv
        form.addRow("TradingView Desktop", tv_row)
        motor_advanced = DisclosureButton("Gelişmiş motor yolu")
        self.worker_motor_toggle = motor_advanced
        self.motor_path.setVisible(False)
        motor_advanced.toggled.connect(self.motor_path.setVisible)
        form.addRow(motor_advanced, self.motor_path)
        form.addRow("Atanacak proje", self.worker_project)
        box.addLayout(form)
        resource_row = Q.QHBoxLayout()
        self.resource_status = Q.QLabel("Kaynak ölçümü yapılmadı", objectName="status")
        measure = Q.QPushButton("Kaynakları ölç"); measure.clicked.connect(self.measure_resources)
        self.worker_measure_button = measure
        resource_row.addWidget(measure); resource_row.addWidget(self.resource_status); resource_row.addStretch()
        box.addLayout(resource_row)
        note = Q.QLabel("TradingView bağlantısı 9222 üzerinde açık olmalı. Yeni sekmeler yalnız bu oturumda açılır; mevcut grafikler değiştirilmez.")
        note.setWordWrap(True); note.setObjectName("subtitle"); box.addWidget(note)
        tab_row = Q.QHBoxLayout()
        self.new_tab_count = Q.QSpinBox(); self.new_tab_count.setRange(1, 16); self.new_tab_count.setValue(2); self.new_tab_count.setPrefix("Yeni sekme ")
        open_tabs = Q.QPushButton("9222 içinde yeni sekme aç"); open_tabs.clicked.connect(self.create_worker_tabs)
        claim_tabs = Q.QPushButton("Hazır worker layoutlarını bağla"); claim_tabs.clicked.connect(self.claim_worker_layouts)
        bind = Q.QPushButton("Seçili kaynağı projeye bağla"); bind.clicked.connect(self.bind_selected_strategy)
        self.worker_open_tabs = open_tabs
        self.worker_claim_tabs = claim_tabs
        self.worker_bind_button = bind
        tab_row.addWidget(self.new_tab_count); tab_row.addWidget(open_tabs); tab_row.addWidget(claim_tabs); tab_row.addWidget(bind); tab_row.addStretch(); box.addLayout(tab_row)
        self.worker_table = Q.QTableWidget(0, 7)
        self.worker_table.setHorizontalHeaderLabels(["Kullan", "Çalışan", "Sekme", "Proje", "Strateji", "Hazırlık", "Tamamlanan"])
        worker_header = self.worker_table.horizontalHeader()
        for column, width in enumerate((66, 80, 160, 150, 155, 220, 100)):
            self.worker_table.setColumnWidth(column, width)
        worker_header.setSectionResizeMode(5, Q.QHeaderView.Stretch)
        self.worker_table.setHorizontalScrollMode(Q.QAbstractItemView.ScrollPerPixel)
        self.worker_table.itemChanged.connect(self.update_worker_actions)
        self.worker_empty = Q.QLabel("Henüz çalışma sekmesi bulunmadı. Önce 9222 bağlantısını kontrol edip 'Sekmeleri bul' seçin.", objectName="subtitle")
        box.addWidget(self.worker_empty)
        self.worker_table.hide()
        box.addWidget(self.worker_table, 1)
        actions = Q.QHBoxLayout()
        discover = Q.QPushButton("Sekmeleri bul", objectName="primary"); discover.clicked.connect(self.discover_targets)
        self.worker_discover_button = discover
        start = Q.QPushButton("Taramayı başlat", objectName="primary"); start.clicked.connect(self.start_workers)
        self.start_workers_button = start
        start.setEnabled(False)
        stop = Q.QPushButton("Durdur"); stop.clicked.connect(self.stop_workers)
        self.worker_stop_button = stop
        actions.addWidget(discover); actions.addWidget(start); actions.addWidget(stop); actions.addStretch()
        self.worker_status = Q.QLabel("Bağlantı kontrol edilmedi", objectName="status"); actions.addWidget(self.worker_status)
        box.addLayout(actions)
        return page

    def find_tradingview(self):
        try:
            found = find_tradingview_executables()
        except Exception as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}")
            self.worker_status.setText(self._friendly_error(exc))
            self.worker_status.setToolTip(str(exc))
            found = []  # Offer the same explicit file picker after discovery failure.
        if found:
            self.tv_executable.setText(str(found[0]))
            self.store.save_app_settings({"tradingview_executable": str(found[0])})
            self.worker_status.setText(f"TradingView bulundu · CDP {'hazır' if cdp_healthy() else 'kapalı'}")
        else:
            path, _ = self.QtWidgets.QFileDialog.getOpenFileName(self.window, "TradingView.exe seç", "", "Uygulama (*.exe)")
            if path:
                self.tv_executable.setText(path)
                self.store.save_app_settings({"tradingview_executable": path})

    def open_tradingview(self):
        try:
            launch_with_cdp(self.tv_executable.text().strip())
            self.worker_status.setText("TradingView CDP ile başlatıldı; bağlantı hazırlanıyor")
        except Exception as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.worker_status.setText(str(exc))

    def create_worker_tabs(self):
        try:
            targets = open_chart_tabs(self.new_tab_count.value(), port=9222)
            self.worker_status.setStyleSheet(f"color:{STATUS_WARNING}")
            self.worker_status.setText(
                f"{len(targets)} sekme açıldı; her biri için ayrı 'TV Scan Worker N' layoutu oluşturup bağlayın.")
            QtCore.QTimer.singleShot(1200, self.window,
                                     lambda: self.discover_targets()
                                     if not getattr(self, "_closing", False) else None)
        except TabCreationError as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}")
            count = len(exc.created_targets)
            self.worker_status.setText(
                f"{exc} {count} sekme doğrulanmış olabilir; yeniden açmadan önce listeyi yenileyin. "
                "Her worker için ayrı 'TV Scan Worker 1/2' layoutu oluşturun.")
            QtCore.QTimer.singleShot(1200, self.window,
                                     lambda: self.discover_targets()
                                     if not getattr(self, "_closing", False) else None)
        except Exception as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.worker_status.setText(
                f"{exc} TradingView'de ayrı 'TV Scan Worker 1/2' layoutları açıp 'Hazır worker layoutlarını bağla' seçin.")

    def claim_worker_layouts(self):
        """Adopt user-created, uniquely named chart layouts after explicit confirmation."""
        try:
            if not cdp_healthy(9222):
                raise ValueError("TradingView 9222 bağlantısı hazır değil.")
            driver = GncZihinDriver(self.motor_path.text().strip())
            targets = chart_targets(port=9222)
            names = {item["id"]: driver.layout_name(item["id"]) for item in targets}
            candidates = worker_layout_candidates(targets, names)
            if not candidates:
                raise ValueError("Benzersiz 'TV Scan Worker 1/2' layoutları bulunamadı.")
            display = "\n".join(sorted(names[target] for target in candidates))
            answer = self.QtWidgets.QMessageBox.question(
                self.window, "Worker layoutlarını bağla",
                f"Bu ayrı TradingView layoutları tarama sırasında değiştirilebilir:\n{display}\n\n"
                "Yalnız bunları çalışma sekmesi olarak bağlamak istiyor musunuz?")
            if answer != self.QtWidgets.QMessageBox.Yes:
                return
            self._safe_worker_layouts.update(candidates)
            self._safe_worker_targets.update(candidates)
            self.driver = driver
            self.discover_targets()
        except Exception as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}")
            self.worker_status.setText(str(exc))

    def _new_project_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Stratejiler", "İlk stratejini ekle veya kayıtlı bir stratejiyle devam et."))
        box.addWidget(self._first_use_help("strategies", "Nereden başlayacağım?",
            "Üstteki listeden kayıtlı bir strateji seçin veya Pine strategy kodunuzu aşağıya yapıştırın. "
            "Ayarlar otomatik okunur. Proje adını girip Stratejiyi kaydet seçin; ardından Taramayı hazırla ile devam edin. "
            "Aynı kodu tekrar kaydetmek kopya oluşturmaz; ayrı bir çalışma için Kopya oluştur kullanın."))
        self.project_name = Q.QLineEdit()
        self.project_name.setPlaceholderText("Proje adı")
        box.addWidget(self.project_name)
        self.pine_source = Q.QPlainTextEdit()
        self.pine_source.setPlaceholderText('//@version=6\nstrategy("Stratejim")\nlength = input.int(20, "Length")')
        self.pine_source.setMinimumHeight(230)
        box.addWidget(self.pine_source)
        controls = Q.QHBoxLayout()
        analyze = Q.QPushButton("Ayarları tekrar oku")
        self.strategy_analyze_button = analyze
        analyze.clicked.connect(self.analyze_source)
        save = Q.QPushButton("Stratejiyi kaydet", objectName="primary")
        self.strategy_save_button = save
        save.clicked.connect(self.save_project)
        controls.addWidget(analyze)
        controls.addWidget(save)
        copy = Q.QPushButton("Kopya oluştur")
        self.strategy_copy_button = copy
        copy.clicked.connect(lambda: self.save_project(copy=True))
        controls.addWidget(copy)
        controls.addStretch()
        box.addLayout(controls)
        self.project_status = Q.QLabel("Pine kodu bekleniyor", objectName="status")
        box.addWidget(self.project_status)
        self.input_table = Q.QTableWidget(0, 9)
        self.input_table.setHorizontalHeaderLabels(["Değişken", "Başlık", "Tür", "Varsayılan", "Seçenekler", "Min/Max/Adım", "Grup", "Tooltip", "Durum"])
        self.input_table.horizontalHeader().setStretchLastSection(True)
        self.input_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        for column in (0, 2, 4, 5, 6, 8):
            self.input_table.setColumnHidden(column, True)
        self.input_table.horizontalHeader().setSectionResizeMode(1, Q.QHeaderView.Stretch)
        self.input_table.horizontalHeader().setSectionResizeMode(7, Q.QHeaderView.Stretch)
        technical = DisclosureButton("Teknik ayrıntılar")
        self.strategy_technical_toggle = technical
        technical.toggled.connect(lambda shown: [self.input_table.setColumnHidden(c, not shown) for c in (0, 2, 4, 5, 6, 8)])
        box.addWidget(technical)
        box.addWidget(self.input_table, 1)
        self.source_timer = QtCore.QTimer(self.window)
        self.source_timer.setSingleShot(True)
        self.source_timer.setInterval(400)
        self.source_timer.timeout.connect(self.analyze_source)
        self.pine_source.textChanged.connect(self.source_timer.start)
        scroll = Q.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(Q.QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _show_page(self, index):
        active_tour = getattr(self, "guided_tour", None)
        if active_tour is not None:
            active_tour.finish()
        nav_button = self.nav_group.button(index)
        if nav_button is not None:
            nav_button.setChecked(True)
        if index != 4:
            self.result_detail_dock.hide()
        self.pages.setCurrentIndex(index)
        tour_key = {1: "strategies", 2: "scan", 4: "results"}.get(index)
        if tour_key:
            QtCore.QTimer.singleShot(300, self.window,
                                     lambda: self.start_guided_tour(tour_key, automatic=True)
                                     if not getattr(self, "_closing", False)
                                     and self.pages.currentIndex() == index else None)
        if index == 0:
            self.refresh_dashboard()
        elif index == 2:
            self.refresh_project_selectors()
        elif index == 3:
            self.refresh_project_selectors()
        elif index == 4:
            self.refresh_project_selectors(); self.refresh_results()
        elif index == 5:
            self.refresh_project_selectors()
            self.refresh_research_evidence()

    def save_application_settings(self):
        self.store.save_app_settings({
            "timeout": self.default_timeout.value(), "poll_interval": self.default_poll.value(),
            "stable_reads": self.default_stable.value(), "notifications": self.notifications_enabled.isChecked(),
            "cdp_port": 9222,
        })
        self.settings_status.setText("Ayarlar yerel veritabanına kaydedildi.")

    def analyze_source(self):
        Q = self.QtWidgets
        try:
            inputs = parse_strategy_inputs(self.pine_source.toPlainText())
        except ValueError as exc:
            self.project_status.setText(str(exc))
            self.input_table.setRowCount(0)
            self.project_status.setStyleSheet(f"color:{STATUS_ERROR}")
            return
        self.input_table.setRowCount(len(inputs))
        for row, item in enumerate(inputs):
            limits = "/".join("—" if value is None else str(value) for value in (item.minimum, item.maximum, item.step))
            status = (
                "Varsayılan okunamadı" if item.manual_definition_required else
                "Değer hazır · ek bilgi eksik" if item.metadata_warnings else "Hazır"
            )
            values = (item.variable, item.title, item.kind, repr(item.default), repr(item.options or ""),
                      limits, item.group or "", item.tooltip or "",
                      status)
            for column, value in enumerate(values):
                self.input_table.setItem(row, column, Q.QTableWidgetItem(str(value)))
        self.project_status.setStyleSheet(f"color:{STATUS_INFO}")
        unresolved = sum(item.manual_definition_required for item in inputs)
        self.project_status.setText(f"{len(inputs)} input bulundu · {len(inputs) - unresolved} varsayılan hazır · {unresolved} değer ayrıca doğrulanmalı")
        return inputs

    def save_project(self, _checked=False, *, copy=False):
        name = self.project_name.text().strip()
        source = self.pine_source.toPlainText()
        if not name:
            self.project_status.setText("Proje adı gerekli")
            self.project_status.setStyleSheet(f"color:{STATUS_ERROR}")
            return
        try:
            self.analyze_source()
            parse_strategy_inputs(source)
        except ValueError:
            return
        project_id, created = self.store.save_unique_project(name, source, copy=copy)
        self._saved_project_id = project_id
        self.project_status.setStyleSheet(f"color:{STATUS_SUCCESS}")
        self.project_status.setText("Strateji kaydedildi. Taramayı hazırlayabilirsiniz." if created else "Bu kod zaten kayıtlı. Mevcut strateji açıldı.")
        self.prepare_saved_button.setEnabled(True)
        self.strategy_list.blockSignals(True)
        self.strategy_list.clear()
        self.strategy_list.addItem("Yeni strateji ekle", None)
        for project in self.store.projects():
            self.strategy_list.addItem(project["name"], project["id"])
        self.strategy_list.setCurrentIndex(self.strategy_list.findData(project_id))
        self.strategy_list.blockSignals(False)
        self.refresh_dashboard()
        self.refresh_project_selectors()

    def refresh_project_selectors(self):
        previous_plan_project = getattr(self, "_loaded_plan_project_id", None)
        projects = self.store.projects()
        for combo in (self.plan_project, self.result_project, self.worker_project, self.research_project):
            current = combo.currentData()
            combo.blockSignals(True); combo.clear()
            for project in projects: combo.addItem(project["name"], project["id"])
            index = combo.findData(current)
            if index >= 0: combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if self.plan_project.currentData() != previous_plan_project:
            self.load_plan_inputs()

    def _remember_project(self, project_id):
        if project_id is None:
            return
        recent = self.store.app_settings().get("recent_project_ids", [])
        recent = [value for value in recent if value != project_id]
        self.store.save_app_settings({"recent_project_ids": [project_id, *recent][:5]})

    def open_project_picker(self):
        """Search by name without changing the active project until confirmed."""
        Q = self.QtWidgets
        dialog = Q.QDialog(self.window)
        dialog.setWindowTitle("Proje seç")
        dialog.resize(400, 380)
        layout = Q.QVBoxLayout(dialog)
        search = Q.QLineEdit()
        search.setPlaceholderText("Proje adı ara")
        results = Q.QListWidget()
        results.setAlternatingRowColors(True)
        projects = self.store.projects()
        active_id = self.plan_project.currentData()
        recent_ids = self.store.app_settings().get("recent_project_ids", [])

        def search_key(value):
            decomposed = unicodedata.normalize("NFKD", value.casefold())
            return "".join(char for char in decomposed if not unicodedata.combining(char)).replace("ı", "i")

        def refresh_results(query=""):
            results.clear()
            needle = search_key(query.strip())
            matches = [project for project in projects
                       if not needle or needle in search_key(project["name"])]
            if not needle and recent_ids:
                positions = {project_id: index for index, project_id in enumerate(recent_ids)}
                matches.sort(key=lambda project: positions.get(project["id"], len(positions)))
            previous_group = None
            for project in matches:
                if not needle and project["id"] in recent_ids:
                    group = "Son kullanılanlar"
                else:
                    group = "Diğer projeler"
                if not needle and recent_ids and group != previous_group:
                    heading = Q.QListWidgetItem(group)
                    heading.setFlags(QtCore.Qt.NoItemFlags)
                    results.addItem(heading)
                    previous_group = group
                item = Q.QListWidgetItem(project["name"])
                item.setData(QtCore.Qt.UserRole, project["id"])
                count = int(project.get("task_count") or 0)
                item.setToolTip(f"{count} görev · {project['status']}")
                results.addItem(item)
                if project["id"] == active_id:
                    results.setCurrentItem(item)
            if results.currentItem() is None:
                for row in range(results.count()):
                    if results.item(row).flags() & QtCore.Qt.ItemIsSelectable:
                        results.setCurrentRow(row)
                        break

        search.textChanged.connect(refresh_results)
        layout.addWidget(search)
        layout.addWidget(results)
        new_project = Q.QPushButton("+ Yeni proje oluştur")
        new_project.setObjectName("projectPickerNewProject")
        new_project.clicked.connect(lambda: dialog.done(2))
        layout.addWidget(new_project)
        buttons = Q.QDialogButtonBox(Q.QDialogButtonBox.Ok | Q.QDialogButtonBox.Cancel)
        buttons.button(Q.QDialogButtonBox.Ok).setText("Projeyi seç")
        buttons.button(Q.QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        results.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addWidget(buttons)
        refresh_results()
        search.setFocus()
        self._configure_selection_help(dialog, layout, "projects", (
            ("search", search, "Kayıtlı stratejiyi ara", "Yerel strateji adlarını yazdığın metne göre süzer.",
             "Arama yeni proje oluşturmaz ve aktif stratejiyi değiştirmez. Son kullanılanlar yalnız sıralamadır; görünmeyen kayıtlar silinmez."),
            ("list", results, "Taranacak stratejiyi seç", "Projeyi seç veya satıra çift tıkla ile planın stratejisini değiştirir.",
             "Satıra tek tıklamak yalnız pencere seçimini değiştirir. Onaydan sonra seçilen stratejinin ayar ve plan kapsamı yüklenir; görev ve tarama kendiliğinden başlamaz. Aynı adlı kayıtları görev ve durum açıklamasıyla birlikte incele."),
            ("new", new_project, "Yeni strateji ekranına git", "Seçim penceresini kapatıp strateji ekleme ekranına geçer.",
             "Bu düğme tek başına yeni kayıt oluşturmaz. Kodu ve adı strateji ekranında girip ayrıca kaydetmelisin; var olan projeler korunur."),
        ), buttons)
        choice = dialog.exec()
        if choice == 2:
            self._show_page(1)
            self.project_name.setFocus()
            return
        if choice != Q.QDialog.Accepted or results.currentItem() is None:
            return
        project_id = results.currentItem().data(QtCore.Qt.UserRole)
        index = self.plan_project.findData(project_id)
        if index >= 0:
            self.plan_project.setCurrentIndex(index)
            self._remember_project(project_id)

    def discover_targets(self):
        try:
            previous = {}
            for old_row in range(self.worker_table.rowCount()):
                target_item = self.worker_table.item(old_row, 2)
                project_widget = self.worker_table.cellWidget(old_row, 3)
                enabled_item = self.worker_table.item(old_row, 0)
                if target_item and project_widget:
                    previous[target_item.data(QtCore.Qt.UserRole)] = (
                        project_widget.currentData(),
                        enabled_item.checkState() == QtCore.Qt.Checked if enabled_item else False)
            self.driver = GncZihinDriver(self.motor_path.text().strip())
            inventory = self.driver.inventory()
            self._last_inventory = inventory
            projects = self.store.projects()
            default_project = self.worker_project.currentData()
            self.worker_table.setRowCount(len(inventory))
            for row, item in enumerate(inventory):
                target = item["target_id"]
                enabled = self.QtWidgets.QTableWidgetItem()
                enabled.setFlags(enabled.flags() | QtCore.Qt.ItemIsUserCheckable)
                enabled.setCheckState(QtCore.Qt.Unchecked)
                self.worker_table.setItem(row, 0, enabled)
                self.worker_table.setItem(row, 1, self.QtWidgets.QTableWidgetItem(str(row + 1)))
                safe = target in self._safe_worker_targets
                tab_cell = self.QtWidgets.QTableWidgetItem(
                    f"Çalışma sekmesi {row + 1}" if safe else f"Mevcut grafik {row + 1}"
                )
                tab_cell.setData(QtCore.Qt.UserRole, target)
                self.worker_table.setItem(row, 2, tab_cell)
                project_combo = self.QtWidgets.QComboBox()
                project_combo.addItem("Atanmadı", None)
                for project in projects: project_combo.addItem(project["name"], project["id"])
                remembered = previous.get(target)
                index = project_combo.findData(remembered[0] if remembered else default_project if safe else None)
                if index >= 0: project_combo.setCurrentIndex(index)
                project_combo.currentIndexChanged.connect(lambda _index, r=row: self.refresh_worker_match(r))
                self.worker_table.setCellWidget(row, 3, project_combo)
                for column in (4, 5, 6): self.worker_table.setItem(row, column, self.QtWidgets.QTableWidgetItem("0" if column == 6 else ""))
                self.refresh_worker_match(row)
                if remembered and not remembered[1]:
                    self.worker_table.item(row, 0).setCheckState(QtCore.Qt.Unchecked)
            ready_count = sum(self.worker_table.item(row, 0).checkState() == QtCore.Qt.Checked
                              for row in range(self.worker_table.rowCount()))
            bound_count = sum(item["target_id"] in self._safe_worker_targets for item in inventory)
            color = STATUS_SUCCESS if ready_count >= 2 else STATUS_WARNING
            self.worker_status.setStyleSheet(f"color:{color}")
            self.worker_status.setText(
                f"{len(inventory)} sekme · {bound_count} ayrı layout bağlı · {ready_count} taramaya hazır")
            self.worker_empty.setVisible(not inventory)
            self.worker_table.setVisible(bool(inventory))
            self.update_worker_actions()
        except Exception as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.worker_status.setText(str(exc))

    def refresh_worker_match(self, row):
        project_combo = self.worker_table.cellWidget(row, 3)
        project_id = project_combo.currentData() if project_combo else None
        project = self.store.project(project_id) if project_id is not None else None
        item = self._last_inventory[row]
        safe_target = item["target_id"] in self._safe_worker_targets
        candidate = None; identity_ok = False; named_strategy = None; named_unready = False
        input_mismatch = None
        if project:
            expected_inputs = parse_strategy_inputs(project["pine_source"])
            expected_title = strategy_title(project["pine_source"])
            identity = (self.store.settings(project_id) or {}).get("tradingview_identity", {})
            named = [strategy for strategy in item["strategies"]
                     if strategy.get("name") == expected_title]
            named_strategy = named[0] if len(named) == 1 else None
            if named_strategy:
                observed_count = len(named_strategy.get("input_ids") or [])
                if observed_count != len(expected_inputs):
                    input_mismatch = (len(expected_inputs), observed_count)
            named_unready = bool(named_strategy and
                                 (named_strategy.get("status") or {}).get("type") != 2)
            ready = [strategy for strategy in item["strategies"] if (strategy.get("status") or {}).get("type") == 2]
            matched = [strategy for strategy in ready
                       if strategy_structure_matches(strategy, expected_title, len(expected_inputs))]
            candidate = matched[0] if len(matched) == 1 else None
            identity_ok = bool(
                candidate
                and safe_target
                and confirmed_strategy_identity_matches(
                    candidate, identity, pine_hash=project["pine_hash"],
                    expected_title=expected_title,
                    expected_input_count=len(expected_inputs),
                    expected_source=project["pine_source"],
                )
            )
        enabled = self.worker_table.item(row, 0)
        enabled.setCheckState(QtCore.Qt.Checked if identity_ok else QtCore.Qt.Unchecked)
        strategy_cell = self.worker_table.item(row, 4)
        visible_strategy = candidate or named_strategy
        strategy_cell.setText(str(visible_strategy.get("name", "") if visible_strategy else ""))
        strategy_cell.setToolTip("Grafikteki strateji adı; teknik kimlik arka planda tutulur.")
        strategy_cell.setData(QtCore.Qt.UserRole, candidate)
        status = (
            WORKER_READY_LABEL if identity_ok else
            "Mevcut sekme korunuyor · yeni çalışma sekmesi açın" if not safe_target else
            "yapısal eşleşme · ilk kaynak onayı gerekli" if candidate else
            (f"Strateji sürümü farklı · projede {input_mismatch[0]}, grafikte {input_mismatch[1]} input"
             if input_mismatch else
            "Strateji bulundu · TradingView test raporu hazır değil" if named_unready else
            (item["error"] or "proje adı/input yapısı eşleşmedi"))
        )
        self.worker_table.item(row, 5).setText(status)
        self.worker_table.item(row, 5).setToolTip(status)
        self.update_worker_actions()

    def update_worker_actions(self, *_args):
        if not hasattr(self, "start_workers_button"):
            return
        ready = any(
            self.worker_table.item(row, 0) is not None
            and self.worker_table.item(row, 0).checkState() == QtCore.Qt.Checked
            and self.worker_table.item(row, 5) is not None
            and self.worker_table.item(row, 5).text() == WORKER_READY_LABEL
            for row in range(self.worker_table.rowCount())
        )
        self.start_workers_button.setEnabled(ready and self.driver is not None)

    def bind_selected_strategy(self):
        try:
            if self.supervisor and self.supervisor.running:
                raise ValueError("Kaynak doğrulamadan önce çalışan workerları durdurun.")
            row = self.worker_table.currentRow()
            project_widget = self.worker_table.cellWidget(row, 3) if row >= 0 else None
            project_id = project_widget.currentData() if project_widget else None
            if row < 0 or project_id is None:
                raise ValueError("Önce proje ve yapısal eşleşen worker satırını seçin.")
            strategy = self.worker_table.item(row, 4).data(QtCore.Qt.UserRole)
            if not strategy or not strategy.get("pine_id"):
                raise ValueError("Bu satırda bağlanabilir Pine kimliği yok.")
            project = self.store.project(project_id)
            target_cell = self.worker_table.item(row, 2)
            target_id = target_cell.data(QtCore.Qt.UserRole) if target_cell else None
            automatic_source_hash = None
            reader = getattr(self.driver, "strategy_source_hash", None)
            if callable(reader) and target_id in self._safe_worker_targets:
                try:
                    saved_reader = getattr(self.driver, "saved_strategy_source_hash", None)
                    if callable(saved_reader):
                        self._guard_worker_layout(target_id)
                        try:
                            automatic_source_hash = saved_reader(target_id, strategy["id"])
                        except SourceReadUnavailable:
                            pass
                    if automatic_source_hash is None:
                        opener = getattr(self.driver, "ensure_strategy_source_hash", None)
                        automatic_source_hash = (opener(target_id, strategy["id"], guard=self._guard_worker_layout)
                                                 if callable(opener) else reader(target_id, strategy["id"]))
                except SourceReadUnavailable:
                    pass  # An unavailable editor is not a match or a mismatch.
            if (automatic_source_hash is not None
                    and automatic_source_hash != pine_source_hash(project["pine_source"])):
                raise ValueError("Grafikteki Pine kaynağı proje koduyla farklı; worker bağlanmadı.")
            if automatic_source_hash:
                observed = [item for item in self.driver.strategies(target_id)
                            if item.get("id") == strategy["id"]]
                if (len(observed) != 1 or not strategy.get("pine_digest")
                        or not strategy.get("pine_version")
                        or any(observed[0].get(key) != strategy.get(key)
                               for key in ("pine_id", "pine_digest", "pine_version", "input_ids"))):
                    raise ValueError("Kaynak okunurken strateji kimliği değişti; worker bağlanmadı.")
            answer = self.QtWidgets.QMessageBox.Yes if automatic_source_hash else self.QtWidgets.QMessageBox.question(
                self.window, "Strateji kaynağını kontrol et",
                f"Grafik: {target_cell.text() if target_cell else 'Seçili çalışma grafiği'}\n"
                f"Grafikteki strateji: {strategy.get('name', 'Adı okunamadı')}\n"
                f"Kayıtlı strateji: {project['name']}\n\n"
                "Tam Pine kaynağı otomatik doğrulanamadı. Bu grafikteki stratejinin "
                "kaynağını kayıtlı strateji koduyla karşılaştırıp aynı olduğunu kontrol ettiniz mi? "
                "Yalnız ayarların veya adın benzemesi yeterli değildir."
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                return
            self.store.save_settings(project_id, {"tradingview_identity": {
                "pine_id": strategy["pine_id"], "name": strategy.get("name"),
                "pine_digest": strategy.get("pine_digest"),
                "pine_version": strategy.get("pine_version"),
                "input_ids": strategy.get("input_ids", []),
                "pine_hash": self.store.project(project_id)["pine_hash"],
                "user_source_confirmed": True,
                "source_verification": "editor_saved_source_sha256" if automatic_source_hash else "user_confirmation",
                "source_sha256": automatic_source_hash,
            }})
            self.discover_targets()
        except (ValueError, TradingViewError) as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.worker_status.setText(str(exc))

    def start_workers(self, _checked=False, *, confirmed=False, prepared_assignments=None):
        try:
            if self.driver is None: raise ValueError("Önce çalışma sekmelerini bulun.")
            if self.supervisor and self.supervisor.running:
                raise ValueError("Workerlar zaten çalışıyor; ikinci kez başlatılamaz.")
            if not cdp_healthy(9222):
                raise ValueError("9222 bağlantısı hazır değil; worker başlatılmadı.")
            assignments = list(prepared_assignments) if prepared_assignments is not None else []
            for row in range(self.worker_table.rowCount()) if prepared_assignments is None else ():
                if self.worker_table.item(row, 0).checkState() == QtCore.Qt.Checked:
                    if self.worker_table.item(row, 5).text() != WORKER_READY_LABEL:
                        raise ValueError("Seçili workerın kullanıcı kaynak onayı ve input yapısı hazır değil.")
                    project_id = self.worker_table.cellWidget(row, 3).currentData()
                    target_id = self.worker_table.item(row, 2).data(QtCore.Qt.UserRole)
                    if target_id not in self._safe_worker_targets:
                        raise ValueError("Mevcut canlı sekmeler taramada kullanılamaz. Yeni çalışma sekmesi açın.")
                    assignments.append(WorkerAssignment(
                        int(self.worker_table.item(row, 1).text()),
                        target_id, (project_id,),
                        (self.worker_table.item(row, 4).data(QtCore.Qt.UserRole) or {}).get("id"),
                    ))
            if not assignments: raise ValueError("En az bir worker seçin.")
            answer = self.QtWidgets.QMessageBox.Yes if confirmed else self.QtWidgets.QMessageBox.question(
                self.window, "Taramayı başlat",
                f"{len(assignments)} yeni çalışma sekmesinde tarama başlatılsın mı? "
                "Mevcut canlı grafiklere dokunulmayacak."
            )
            if answer != self.QtWidgets.QMessageBox.Yes:
                return
            self._validate_live_worker_assignments(assignments)
            supervisor = WorkerSupervisor(
                self.store, self.driver, target_guard=self._worker_target_guard(assignments),
                download_directory=Path.home() / "Downloads")
            try:
                if confirmed:
                    supervisor.start(assignments, stop_when_idle=True)
                else:
                    supervisor.start(assignments)
            except Exception:
                if hasattr(self.driver, "target_guard"):
                    self.driver.target_guard = None
                raise
            self.supervisor = supervisor
            scoped_runs = {run_id for assignment in assignments for run_id in (assignment.run_ids or ())}
            self._active_run_id = next(iter(scoped_runs)) if len(scoped_runs) == 1 else None
            self._active_run_project = (assignments[0].project_ids[0] if self._active_run_id is not None else None)
            self.worker_status.setStyleSheet(f"color:{STATUS_SUCCESS}")
            self.worker_status.setText(f"{len(assignments)} worker çalışıyor")
        except Exception as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.worker_status.setText(str(exc))

    def _worker_target_guard(self, assignments):
        """Bind each target to exactly one confirmed project/study for the run."""
        by_target = {assignment.target_id: assignment for assignment in assignments}
        if len(by_target) != len(assignments):
            raise ValueError("Worker targetları benzersiz olmalı.")
        def guard(target_id: str) -> None:
            assignment = by_target.get(target_id)
            if assignment is None:
                raise ValueError("Worker targetı bu çalışmaya atanmamış; grafik korunuyor.")
            self._guard_worker_assignment(assignment)
        return guard

    def _guard_worker_layout(self, target_id: str) -> None:
        """Fail closed before every task if a worker tab has changed layout."""
        expected = self._safe_worker_layouts.get(target_id)
        if not expected or self.driver is None:
            raise ValueError("Worker layoutu bu oturumda güvenle bağlanmadı.")
        targets = chart_targets(port=9222)
        name = self.driver.layout_name(target_id)
        current = worker_layout_candidates(targets, {target_id: name})
        if current.get(target_id) != expected:
            raise ValueError("Tarama grafiği değişti veya benzersiz değil: başka sekmeyle çakışıyor; görev uygulanmadı.")
        if self.driver.replay_active(target_id):
            raise ValueError("Worker sekmesinde Bar Replay açık; görev uygulanmadı.")

    def _guard_worker_assignment(self, assignment: WorkerAssignment) -> None:
        """Recheck layout and the confirmed study inventory before every chart action."""
        self._guard_worker_layout(assignment.target_id)
        if len(assignment.project_ids) != 1 or not assignment.study_id:
            raise ValueError("Worker proje/strateji ataması geçersiz; grafik korunuyor.")
        project_id = assignment.project_ids[0]
        project = self.store.project(project_id)
        if project is None:
            raise ValueError("Worker projesi bulunamadı; grafik korunuyor.")
        identity = (self.store.settings(project_id) or {}).get("tradingview_identity") or {}
        expected_title = strategy_title(project["pine_source"])
        expected_count = len(parse_strategy_inputs(project["pine_source"]))
        strategies = self.driver.strategies(assignment.target_id)
        matches = [strategy for strategy in strategies if strategy.get("id") == assignment.study_id]
        if len(matches) != 1 or not confirmed_strategy_identity_matches(
                matches[0], identity, pine_hash=project["pine_hash"],
                expected_title=expected_title, expected_input_count=expected_count,
                expected_source=project["pine_source"]):
            raise ValueError("Worker strateji/input kimliği değişti; görev uygulanmadı.")

    def _validate_live_worker_assignments(self, assignments):
        """Read-only identity check immediately before workers may alter new tabs."""
        claimed = {assignment.target_id for assignment in assignments}
        if not claimed.issubset(self._safe_worker_layouts):
            raise ValueError("Her worker ayrı kaydedilmiş ve açıkça bağlanmış bir layout kullanmalı.")
        if claimed:
            live_targets = chart_targets(port=9222)
            names = {target_id: self.driver.layout_name(target_id) for target_id in claimed}
            current = worker_layout_candidates(live_targets, names)
            if any(current.get(target_id) != self._safe_worker_layouts[target_id]
                   for target_id in claimed):
                raise ValueError("Worker layout kimliği değişti veya başka sekmeyle çakışıyor; tarama başlamadı.")
            if any(self.driver.replay_active(target_id) for target_id in claimed):
                raise ValueError("Worker sekmesinde Bar Replay açık; tarama başlamadı.")
        inventory = {item["target_id"]: item for item in self.driver.inventory()}
        seen_targets = set()
        for assignment in assignments:
            if assignment.target_id in seen_targets or assignment.target_id not in self._safe_worker_targets:
                raise ValueError("Çalışma sekmesi benzersiz ve bu oturumda yeni açılmış olmalı.")
            seen_targets.add(assignment.target_id)
            tab = inventory.get(assignment.target_id)
            if tab is None:
                raise ValueError("Çalışma sekmesi artık 9222 oturumunda bulunamadı; tarama başlamadı.")
            project_id = assignment.project_ids[0]
            project = self.store.project(project_id)
            if project is None:
                raise ValueError("Atanan proje bulunamadı; tarama başlamadı.")
            identity = (self.store.settings(project_id) or {}).get("tradingview_identity") or {}
            expected_title = strategy_title(project["pine_source"])
            expected_count = len(parse_strategy_inputs(project["pine_source"]))
            matches = [strategy for strategy in tab.get("strategies", [])
                       if strategy.get("id") == assignment.study_id
                       and (strategy.get("status") or {}).get("type") == 2
                       and strategy_structure_matches(strategy, expected_title, expected_count)]
            if (len(matches) != 1 or not confirmed_strategy_identity_matches(
                    matches[0], identity, pine_hash=project["pine_hash"],
                    expected_title=expected_title, expected_input_count=expected_count,
                    expected_source=project["pine_source"])):
                raise ValueError(
                    "Strateji kimliği, kullanıcı kaynak onayı veya input yapısı geçerli değil; "
                    "sekmeleri yeniden doğrulayın."
                )

    def stop_workers(self):
        if self._admission_job is not None:
            self._cancel_plan_admission()
            return
        job = getattr(self, "_preparation_job", None)
        if job and job.isRunning():
            job.cancelled.set()
            self.connection_status.setText("İşlem gerekli: hazırlık durduruluyor; mevcut kayıtlar korunacak.")
        if getattr(self, "_connection_timer", None) and self._connection_timer.isActive():
            self._connection_timer.stop()
            self._preparing = False
            self.preview_plan()
        if self.supervisor and self.supervisor.running:
            self.supervisor.request_stop()
            message = "Durduruluyor: mevcut test güvenli noktada tamamlanacak; yeni görev alınmayacak."
            if hasattr(self, "worker_status"): self.worker_status.setText(message)
            if hasattr(self, "connection_status"): self.connection_status.setText(message)
            if hasattr(self, "run_progress"): self.run_progress.setText(message)

    def shutdown(self):
        self._closing = True
        job = getattr(self, "_preparation_job", None)
        if job and job.isRunning():
            job.cancelled.set()
            job.wait(30000)
        for timer in self.window.findChildren(QtCore.QTimer):
            timer.stop()
        self._preparing = False
        if self.supervisor and self.supervisor.running:
            self.supervisor.stop()
        self.tray.hide()
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.removeEventFilter(self._wheel_filter)

    def refresh_worker_states(self):
        if not self.supervisor: return
        if getattr(self.supervisor, "stop_requested", False):
            self.worker_status.setText(
                "Durduruluyor: mevcut testin güvenli noktaya ulaşması bekleniyor."
                if self.supervisor.running else "Durdu: yeni görev alınmıyor; bekleyen görevler korundu.")
        for worker_id in self.supervisor.restart_failed():
            state = self.supervisor.states[worker_id]
            marker = (worker_id, state.restarts)
            if marker not in self._notified_worker_restarts:
                self._notified_worker_restarts.add(marker)
                self.notify("Worker yeniden başlatıldı", f"Worker {worker_id} yeniden başlatma {state.restarts}/3")
        for row in range(self.worker_table.rowCount()):
            worker_id = int(self.worker_table.item(row, 1).text())
            state = self.supervisor.states.get(worker_id)
            if state:
                self.worker_table.item(row, 5).setText(state.status)
                self.worker_table.item(row, 6).setText(str(state.completed))
                if state.status == "failed" and worker_id not in self._notified_worker_errors:
                    self._notified_worker_errors.add(worker_id)
                    self.notify("Worker müdahalesi gerekiyor", f"Worker {worker_id}: {state.error or 'bilinmeyen hata'}")
        self.refresh_dashboard()
        if hasattr(self, "connection_status"):
            project_id = self.plan_project.currentData()
            tasks = self.store.tasks(project_id) if project_id is not None else []
            completed = sum(task["status"] == "done" for task in tasks)
            failed = sum(task["status"] in {"failed", "manual_review", "invalid"} for task in tasks)
            current = next((task for task in tasks if task["status"] == "running"), None)
            operation = (f" Şimdi: {current['payload'].get('symbol')} / "
                f"{self._timeframe_label(current['payload'].get('timeframe', ''))}." if current else "")
            errors = [state.error for state in self.supervisor.states.values() if state.error]
            run_label = ("Durduruluyor" if getattr(self.supervisor, "stopping", False) else
                "Tarama durdu" if getattr(self.supervisor, "stop_requested", False) else
                "Tarama çalışıyor" if self.supervisor.running else
                "Tarama tamamlandı" if tasks and completed == len(tasks) else "Tarama durdu")
            self.connection_status.setText(
                self._friendly_error(errors[0]) if errors else
                f"{run_label}: "
                f"{completed}/{len(tasks)} test tamamlandı; {failed} test işlem gerektiriyor.{operation}")
            self._refresh_result_progress()
        if self.pages.currentIndex() == 4:
            progress_key = (completed, tuple(errors), self.supervisor.running)
            if progress_key != getattr(self, "_last_run_progress", None):
                self.refresh_results()
                self._last_run_progress = progress_key
        if self.pages.currentIndex() == 5:
            self.refresh_research_evidence()

    def _restore_run_plan(self, snapshot):
        if self._preparing or self._admission_job is not None:
            return
        self.load_plan_inputs(saved_snapshot=snapshot)

    def load_plan_inputs(self, _index=None, *, saved_snapshot=None):
        self._loading_plan_inputs = True
        try:
            self._load_plan_inputs(_index, saved_snapshot=saved_snapshot)
        finally:
            self._loading_plan_inputs = False
        self.preview_plan()

    def _load_plan_inputs(self, _index=None, *, saved_snapshot=None):
        project_id = self.plan_project.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        self._loaded_plan_project_id = project_id if project else None
        if saved_snapshot is None:
            self.run_choice.refresh(project_id if project else None)
        self.session_variants_check.blockSignals(True)
        self.session_variants_check.setChecked(False)
        self.session_variants_check.setEnabled(bool(
            project and self._research_catalog.get("mapping_source_sha256")
            and project["pine_hash"] == self._research_catalog["mapping_source_sha256"]
        ))
        self.session_variants_check.blockSignals(False)
        self.study_id.clear()
        self.strategy_picker.blockSignals(True)
        self.strategy_picker.clear()
        self.strategy_picker.addItem("Açık stratejiyi bul ile bağlanın", None)
        self.strategy_picker.blockSignals(False)
        if not project:
            self._loaded_research = {}
            self.refinement_detach.setEnabled(False)
            self.auto_excluded_notice.hide()
            self.constraint_editor.load({}, [])
            self._populate_cost_input_choices(())
            self.plan_inputs.setRowCount(0)
            self.input_workspace.hide()
            self.plan_empty.show()
            self.plan_status.setText("Önce proje seçin")
            self.plan_factors.clear()
            self.scan_flow_status.setText("Proje: eksik · Strateji: eksik · Plan: eksik · Sekmeler: onay gerekli")
            self.enqueue_plan_button.setEnabled(False)
            return
        inputs = parse_strategy_inputs(project["pine_source"])
        saved_plan = saved_snapshot if saved_snapshot is not None else (self.store.settings(project_id) or {})
        from copy import deepcopy
        self._loaded_variants = deepcopy(saved_plan.get("variants") or [])
        self._loaded_research = deepcopy(saved_plan.get("research") or {})
        self.refinement_detach.setEnabled(bool(self._loaded_research))
        self._loaded_variant_scope = (tuple(saved_plan.get("symbols", [])), tuple(saved_plan.get("timeframes", [])))
        if self._loaded_variants:
            # Restore frozen packages, not a possibly changed research catalogue.
            self.session_variants_check.blockSignals(True)
            self.session_variants_check.setEnabled(True)
            self.session_variants_check.setChecked(True)
            self.session_variants_check.blockSignals(False)
        for widget in (self.scan_method, self.sample_budget, self.sample_seed):
            widget.blockSignals(True)
        self.scan_method.setCurrentIndex(max(0, self.scan_method.findData(saved_plan.get("method", "cartesian"))))
        self.sample_budget.setText(str(saved_plan.get("sample_budget") or 1000))
        self.sample_seed.setText(str(saved_plan.get("sample_seed", 0)))
        sampling = self.scan_method.currentData() == "sample"
        self.sample_budget.setEnabled(sampling)
        self.sample_seed.setEnabled(sampling)
        for widget in (self.scan_method, self.sample_budget, self.sample_seed):
            widget.blockSignals(False)
        self.symbols.setText(", ".join(saved_plan.get("symbols", [])))
        self.timeframes.setText(", ".join(self._timeframe_label(tf) for tf in saved_plan.get("timeframes", [])))
        saved_dates = saved_plan.get("date_range") or {}
        self.date_from.setText(saved_dates.get("from", ""))
        self.date_to.setText(saved_dates.get("to", ""))
        self._populate_cost_input_choices(inputs)
        self.input_workspace.setVisible(bool(inputs))
        self.plan_inputs.setVisible(bool(inputs))
        self.plan_empty.setVisible(not inputs)
        if not inputs:
            self.plan_empty.setText("Bu Pine kaynağında taranabilir input bulunamadı. Yeni proje ekranında kodu kontrol edin.")
        self._plan_parsed_inputs = inputs
        self.constraint_editor.load({f"in_{index}": spec for index, spec in enumerate(inputs)},
                                    saved_plan.get("constraints", []))
        dependencies = input_dependencies(project["pine_source"])
        previous_results = self.store.results(project_id)
        prior_values = historical_values_by_input(previous_results)
        possible_no_effect = verified_no_effect_inputs(self.store, previous_results)
        self.plan_inputs.blockSignals(True)
        self.plan_inputs.setRowCount(len(inputs))
        source_excluded = 0
        color_excluded = 0
        for row, item in enumerate(inputs):
            suggestion = suggest_input(item, project["pine_source"],
                                       prior_values=prior_values.get(f"in_{row}", ()),
                                       active_when=dependencies.get(item.variable))
            default_text = "—" if item.manual_definition_required else str(item.default)
            display_title = item.title.strip() or (
                f"{item.variable} (grafik rengi)" if item.kind == "color" else item.variable
            )
            for column, value in enumerate((f"in_{row}", display_title, default_text)):
                cell = self.QtWidgets.QTableWidgetItem(str(value))
                cell.setToolTip(f"{item.variable} · {item.kind}" + (f" · {item.group}" if item.group else ""))
                self.plan_inputs.setItem(row, column, cell)
            choice = DecisionChoice()
            choice.addItems(["Sabit bırak", "Tara", "Hariç tut"])
            if (suggestion.unused_in_source or suggestion.declared_no_backtest_effect
                    or (item.kind == "color" and item.manual_definition_required)):
                choice.setCurrentText("Hariç tut")
            if suggestion.unused_in_source:
                source_excluded += 1
            if suggestion.declared_no_backtest_effect and not suggestion.unused_in_source:
                source_excluded += 1
            elif item.kind == "color" and item.manual_definition_required:
                color_excluded += 1
            choice.currentIndexChanged.connect(self.preview_plan)
            choice.currentIndexChanged.connect(self.refresh_input_detail)
            self.plan_inputs.setCellWidget(row, 3, choice)
            values = self.QtWidgets.QTableWidgetItem(" · ".join(map(str, suggestion.values)) or "Değer gerekli")
            values.setData(QtCore.Qt.UserRole, list(suggestion.values))
            stored_values = (saved_plan.get("input_values") or {}).get(f"in_{row}")
            if "input_values" in saved_plan:
                if stored_values is None:
                    choice.setCurrentText("Hariç tut")
                elif isinstance(stored_values, list) and stored_values:
                    # Scan mode also preserves an explicitly chosen single value.
                    choice.setCurrentText("Tara")
                    values.setText(" · ".join(map(str, stored_values)))
                    values.setData(QtCore.Qt.UserRole, stored_values)
            stored_ui = {} if self._loaded_research else ((saved_plan.get("input_ui") or {}).get(f"in_{row}") or {})
            if stored_ui.get("decision") in {"Sabit bırak", "Tara", "Hariç tut"}:
                choice.setCurrentText(stored_ui["decision"])
            if isinstance(stored_ui.get("values"), list):
                values.setData(QtCore.Qt.UserRole, stored_ui["values"])
                values.setText(" · ".join(map(str, stored_ui["values"])))
            if isinstance(stored_ui.get("range"), dict):
                values.setData(QtCore.Qt.UserRole + 1, stored_ui["range"])
            values.setToolTip("Tara seçip 'Seçili aralığı değiştir' düğmesiyle bu öneriyi düzenleyebilirsiniz.")
            self.plan_inputs.setItem(row, 4, values)
            choice.currentIndexChanged.connect(lambda _index, r=row: self._sync_scan_value_display(r))
            source_cell = self.QtWidgets.QTableWidgetItem(suggestion.source)
            source_cell.setToolTip(suggestion.source)
            self.plan_inputs.setItem(row, 5, source_cell)
            note = suggestion.note
            if suggestion.unused_in_source:
                note = "Kaynakta tanım dışında kullanım yok; otomatik dışlandı. İsterseniz seçimi değiştirebilirsiniz. " + note
            elif suggestion.declared_no_backtest_effect:
                note = "Pine açıklamasına göre backtesti etkilemez; başlangıçta dışlandı. İsterseniz seçimi değiştirebilirsiniz. " + note
            if f"in_{row}" in possible_no_effect:
                compared = possible_no_effect[f"in_{row}"]
                note = (f"{compared} farklı değer, aynı koşullarda aynı kayıtlı sonuçları verdi; "
                        f"etkisiz olabilir. Otomatik dışlanmadı. {note}")
            if item.metadata_warnings:
                note += " Okunamayan gösterim: " + ", ".join(item.metadata_warnings) + "."
            if item.kind == "color" and item.manual_definition_required:
                note = "Grafik rengi; tarama dışında. " + note
            note_cell = self.QtWidgets.QTableWidgetItem(note)
            note_cell.setToolTip(note)
            self.plan_inputs.setItem(row, 6, note_cell)
            self._sync_scan_value_display(row)
        self.plan_inputs.blockSignals(False)
        assumptions = (saved_plan.get("costs") or {}).get("assumptions") or {}
        scenario = assumptions.get("scenario", next(iter(COST_SCENARIOS)))
        self.cost_scenario.blockSignals(True)
        self.cost_scenario.setCurrentText(scenario)
        self.cost_scenario.blockSignals(False)
        multiplier = COST_SCENARIOS.get(scenario, 1.0)
        cost_defaults = {"initial_capital": 100000, "position_size": 1,
                         "commission_value": 0, "spread": 0, "slippage": 0}
        for key, widget in (("initial_capital", self.initial_capital),
                            ("position_size", self.position_size),
                            ("commission_value", self.commission),
                            ("spread", self.spread), ("slippage", self.slippage)):
            value = assumptions.get(key, cost_defaults[key])
            if key in {"commission_value", "spread", "slippage"}:
                value /= multiplier
            widget.setValue(int(round(value)) if key == "slippage" else value)
        criteria = saved_plan.get("criteria") or {}
        criteria_defaults = {"min_trades": 60, "min_profit_factor": 1.4,
                             "min_win_rate_pct": 40, "max_drawdown_pct_exclusive": 5,
                             "min_net_profit": 0, "max_daily_loss_pct": 5,
                             "max_total_loss_pct": 10}
        for key, widget in (("min_trades", self.min_trades), ("min_profit_factor", self.min_pf),
                            ("min_win_rate_pct", self.min_win),
                            ("max_drawdown_pct_exclusive", self.max_dd), ("min_net_profit", self.min_net)):
            widget.setValue(criteria.get(key, criteria_defaults[key]))
        self.analysis_timezone.setCurrentText(assumptions.get("analysis_timezone", "America/New_York"))
        self.ftmo_risk_check.setChecked("max_daily_loss_pct" in criteria or "max_total_loss_pct" in criteria)
        for key, widget in (("max_daily_loss_pct", self.max_daily_loss),
                            ("max_total_loss_pct", self.max_total_loss)):
            widget.setValue(criteria.get(key, criteria_defaults[key]))
        mappings = (saved_plan.get("costs") or {}).get("input_mapping") or {}
        for key, widget in (("initial_capital", self.capital_input_id),
                            ("position_size", self.position_input_id),
                            ("commission_value", self.commission_input_id),
                            ("spread", self.spread_input_id), ("slippage", self.slippage_input_id)):
            widget.setText(mappings.get(key, ""))
        if inputs:
            self.plan_inputs.selectRow(0)
        self.refresh_input_detail()
        self.auto_excluded_notice.setVisible(bool(source_excluded or color_excluded))
        reasons = []
        if source_excluded:
            reasons.append(f"{source_excluded} input kaynak kullanımı veya Pine açıklamasına göre başlangıçta dışlandı")
        if color_excluded:
            reasons.append(f"{color_excluded} grafik rengi inputu otomatik taramaya alınmadı")
        self.auto_excluded_notice.setText(
            "; ".join(reasons) + ". Bu ayarlar başlangıçta dışlandı; satırdaki seçimi değiştirebilirsiniz."
            if reasons else ""
        )
        self.preview_plan()

    def _sync_scan_value_display(self, row):
        choice = self.plan_inputs.cellWidget(row, 3)
        values = self.plan_inputs.item(row, 4)
        if choice is None or values is None:
            return
        if choice.currentText() == "Tara":
            selected = values.data(QtCore.Qt.UserRole) or []
            values.setText(" · ".join(map(str, selected[:8])) + (" …" if len(selected) > 8 else ""))
        else:
            values.setText("—")

    def refresh_input_detail(self, *_args):
        row = self.plan_inputs.currentRow()
        if row < 0 or row >= self.plan_inputs.rowCount():
            self.input_detail_title.setText("Bir input seçin")
            self.input_detail_values.clear()
            self.input_detail_note.clear()
            self.input_detail_mode.setEnabled(False)
            self.input_numeric_range.hide()
            return
        self.input_detail_mode.setEnabled(True)
        title = self.plan_inputs.item(row, 1).text()
        default = self.plan_inputs.item(row, 2).text()
        values = self.plan_inputs.item(row, 4).text()
        source = self.plan_inputs.item(row, 5).text()
        note = self.plan_inputs.item(row, 6).text()
        self.input_detail_title.setText(title)
        self.input_detail_values.setText(
            f"Varsayılan: {default}\nÖneri / seçim: {values}\nKaynak: {source}"
        )
        self.input_detail_note.setText(note)
        choice = self.plan_inputs.cellWidget(row, 3)
        self.input_detail_mode.blockSignals(True)
        self.input_detail_mode.setCurrentText(choice.currentText())
        self.input_detail_mode.blockSignals(False)
        item = self._plan_parsed_inputs[row]
        numeric = (item.kind in {"int", "float"} and not item.options
                   and not item.manual_definition_required)
        scanning = choice.currentText() == "Tara"
        self.input_numeric_range.setVisible(numeric and scanning)
        self.input_detail_edit.setVisible(not numeric and scanning)
        if numeric:
            selected_values = self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole) or []
            saved_range = self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole + 1) or {}
            self.input_range_start.setText(str(saved_range.get(
                "start", min(selected_values) if selected_values else item.default)))
            self.input_range_stop.setText(str(saved_range.get(
                "stop", max(selected_values) if selected_values else item.default)))
            self.input_range_step.setText(str(saved_range.get(
                "step", item.step or (1 if item.kind == "int" else .1))))

    def apply_input_detail_mode(self, *_args):
        row = self.plan_inputs.currentRow()
        if 0 <= row < self.plan_inputs.rowCount():
            self.plan_inputs.cellWidget(row, 3).setCurrentText(self.input_detail_mode.currentText())

    def apply_input_numeric_range(self):
        row = self.plan_inputs.currentRow()
        if row < 0 or row >= self.plan_inputs.rowCount():
            return
        item = self._plan_parsed_inputs[row]
        if item.kind not in {"int", "float"} or item.options or item.manual_definition_required:
            return
        range_spec = {
            "start": self.input_range_start.text().strip(),
            "stop": self.input_range_stop.text().strip(),
            "step": self.input_range_step.text().strip(),
        }
        try:
            values = parse_scan_values(range_spec)
            if item.kind == "int" and any(not isinstance(value, int) for value in values):
                raise ValueError("Bu input için yalnız tam sayı kullanın.")
            if item.minimum is not None and any(value < item.minimum for value in values):
                raise ValueError(f"En küçük değer {item.minimum} olmalı.")
            if item.maximum is not None and any(value > item.maximum for value in values):
                raise ValueError(f"En büyük değer {item.maximum} olmalı.")
        except ValueError as exc:
            self.plan_status.setText(f"{item.title}: {exc}")
            return
        cell = self.plan_inputs.item(row, 4)
        cell.setData(QtCore.Qt.UserRole, values)
        cell.setData(QtCore.Qt.UserRole + 1, range_spec)
        cell.setText(" · ".join(map(str, values[:8])) + (f" … ({len(values)})" if len(values) > 8 else ""))
        self.plan_inputs.cellWidget(row, 3).setCurrentText("Tara")
        self.refresh_input_detail()
        self.preview_plan()

    def _populate_cost_input_choices(self, inputs):
        """Present Pine input titles while keeping TradingView's in_N IDs internal."""
        title_counts = {}
        for item in inputs:
            title_counts[item.title] = title_counts.get(item.title, 0) + 1
        for choice in self.cost_input_choices.values():
            choice.blockSignals(True)
            choice.clear()
            choice.addItem("Eşleme yok", "")
            for index, item in enumerate(inputs):
                if item.kind in {"int", "float"} and not item.manual_definition_required:
                    label = item.title if title_counts[item.title] == 1 else f"{item.title} · {index + 1}"
                    choice.addItem(label, f"in_{index}")
                    choice.setItemData(choice.count() - 1, item.variable, QtCore.Qt.ToolTipRole)
            choice.setCurrentIndex(0)
            choice.blockSignals(False)
        for field in (self.capital_input_id, self.position_input_id,
                      self.commission_input_id, self.spread_input_id,
                      self.slippage_input_id):
            field.clear()

    def select_plan_strategy(self, *_args):
        selected = self.strategy_picker.currentData()
        self.study_id.setText(str(selected["study_id"]) if isinstance(selected, dict) else "")
        self.preview_plan()

    def discover_plan_strategies(self):
        """Read only: inspect existing 9222 tabs, never create or configure a chart."""
        project_id = self.plan_project.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        if not project:
            self.plan_status.setText("Önce proje seçin.")
            return
        # A failed refresh must never leave a stale study selected for queueing.
        self.strategy_picker.blockSignals(True)
        self.strategy_picker.clear()
        self.strategy_picker.addItem("Strateji aranıyor", None)
        self.strategy_picker.blockSignals(False)
        self.select_plan_strategy()
        try:
            driver = GncZihinDriver(self.motor_path.text().strip())
            inventory = driver.inventory()
            expected_title = strategy_title(project["pine_source"])
            expected_count = len(parse_strategy_inputs(project["pine_source"]))
            identity = (self.store.settings(project_id) or {}).get("tradingview_identity", {})
            matches = []
            unreadable_contexts = 0
            mismatched_counts = set()
            unready_count = 0
            for tab_index, tab in enumerate(inventory, 1):
                for strategy in tab["strategies"]:
                    if strategy.get("name") == expected_title:
                        observed_count = len(strategy.get("input_ids") or [])
                        if observed_count != expected_count:
                            mismatched_counts.add(observed_count)
                            continue
                        if (strategy.get("status") or {}).get("type") != 2:
                            unready_count += 1
                            continue
                    if not strategy_structure_matches(strategy, expected_title, expected_count):
                        continue
                    if (strategy.get("status") or {}).get("type") != 2:
                        continue
                    try:
                        snapshot = driver.snapshot(tab["target_id"], strategy["id"])
                        symbol = str(snapshot.symbol or "").strip()
                        timeframe = str(snapshot.timeframe or "").strip()
                        if not symbol or not timeframe:
                            raise ValueError("Sembol veya zaman dilimi boş")
                    except Exception:
                        unreadable_contexts += 1
                        continue
                    context = f"{symbol} · {timeframe}"
                    source_confirmed = confirmed_strategy_identity_matches(
                        strategy, identity, pine_hash=project["pine_hash"],
                        expected_title=expected_title, expected_input_count=expected_count,
                        expected_source=project["pine_source"],
                    )
                    evidence_label = "kaynak onaylı" if source_confirmed else "kaynak onayı gerekli"
                    matches.append((f"{expected_title} · {context} · Grafik sekmesi {tab_index} · {evidence_label}",
                                    {"study_id": strategy["id"], "target_id": tab["target_id"],
                                     "source_confirmed": source_confirmed}))
            self.strategy_picker.blockSignals(True)
            self.strategy_picker.clear()
            self.strategy_picker.addItem("Strateji seçin", None)
            for label, identity in matches:
                self.strategy_picker.addItem(label, identity)
            self.strategy_picker.blockSignals(False)
            if len(matches) == 1:
                self.strategy_picker.setCurrentIndex(1)
            else:
                self.select_plan_strategy()
            selected = self.strategy_picker.currentData()
            if matches:
                evidence = (
                    "Seçili stratejinin kaynağı onaylı." if isinstance(selected, dict) and selected.get("source_confirmed")
                    else "Yapısal eşleşme; kaynak onayı worker ekranında gerekli."
                )
                self.plan_status.setText(
                    f"{len(matches)} eşleşen açık strateji bulundu; grafikler değiştirilmedi. {evidence}"
                    + (f" {unreadable_contexts} stratejinin sembol/zaman dilimi okunamadığı için seçime alınmadı."
                       if unreadable_contexts else "")
                )
            else:
                self.plan_status.setText(
                    (f"{unreadable_contexts} stratejinin sembol/zaman dilimi okunamadı; "
                     "görev hazırlamak için bağlantıyı yeniden kontrol edin."
                     if unreadable_contexts else
                     f"Strateji sürümü farklı: projede {expected_count} input, grafikte "
                     f"{', '.join(map(str, sorted(mismatched_counts)))} input. "
                     "Projede ve TradingView çalışma sekmesinde aynı Pine sürümünü açın."
                     if mismatched_counts else
                     f"{unready_count} eşleşen stratejinin TradingView test raporu hazır değil."
                     if unready_count else
                     "Eşleşen açık strateji bulunamadı. 9222 oturumunu ve grafikteki Pine kaynağını kontrol edin.")
                )
        except Exception as exc:
            self.strategy_picker.setItemText(0, "Açık stratejiyi yeniden bul")
            self.plan_status.setText(f"Strateji okunamadı: {exc}")

    def edit_scan_values(self, cell):
        if cell.column() != 4:
            return
        row = cell.row()
        if self.plan_inputs.cellWidget(row, 3).currentText() != "Tara":
            self.plan_status.setText("Değer düzenlemek için önce bu inputta Tara seçin.")
            return
        item = self._plan_parsed_inputs[row]
        values = cell.data(QtCore.Qt.UserRole) or []
        Q = self.QtWidgets
        if item.kind in {"int", "float"} and not item.options and not item.manual_definition_required:
            dialog = Q.QDialog(self.window); dialog.setWindowTitle(f"{item.title} aralığı")
            form = Q.QFormLayout(dialog)
            spin_type = Q.QSpinBox if item.kind == "int" else Q.QDoubleSpinBox
            start, stop, step = spin_type(), spin_type(), spin_type()
            for spin in (start, stop, step):
                spin.setRange(-1_000_000_000, 1_000_000_000)
                if item.kind == "float": spin.setDecimals(6)
            start.setValue(min(values) if values else item.default)
            stop.setValue(max(values) if values else item.default)
            step.setValue(item.step or (1 if item.kind == "int" else .1))
            form.addRow("Başlangıç", start); form.addRow("Bitiş", stop); form.addRow("Adım", step)
            buttons = Q.QDialogButtonBox(Q.QDialogButtonBox.Ok | Q.QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
            self._configure_selection_help(dialog, form, "input_range", (
                ("start", start, "İlk denenecek değer", "Seçili ayarın aday aralığının başlangıcıdır.",
                 "Onaydan önce yalnız bu pencerede düzenlenir. Oluşan değerler ayarın türü, kodda bulunan sınırlar ve adımla doğrulanır; kodda olmayan bir sınır en iyi değer gibi sunulmaz."),
                ("stop", stop, "Son değer sınırı", "Aday değer üretiminin bitiş sınırıdır.",
                 "Başlangıç, bitiş ve adım birlikte aday listesini üretir. Bitiş ancak adımla ulaşılabiliyorsa listeye girer. Bu aralık bir performans önerisi değildir."),
                ("step", step, "Değerler arasındaki adım", "Aday değerler arasındaki pozitif artışı belirler.",
                 "Adım sıfır veya negatif olamaz; tam sayı ayarı tam sayı değerler gerektirir. Küçük adım daha fazla test üretir. İptal eski aday listesini korur."),
            ), buttons)
            if dialog.exec() != Q.QDialog.Accepted:
                return
            try:
                values = parse_scan_values({"start": start.value(), "stop": stop.value(), "step": step.value()})
            except ValueError as exc:
                self.plan_status.setText(str(exc)); return
        elif item.kind == "bool" or item.options:
            dialog = Q.QDialog(self.window); dialog.setWindowTitle(f"{item.title} değerleri")
            layout = Q.QVBoxLayout(dialog)
            list_widget = Q.QListWidget()
            for value in (item.options or (False, True)):
                option = Q.QListWidgetItem(str(value)); option.setData(QtCore.Qt.UserRole, value)
                option.setFlags(option.flags() | QtCore.Qt.ItemIsUserCheckable)
                option.setCheckState(QtCore.Qt.Checked if value in values else QtCore.Qt.Unchecked)
                list_widget.addItem(option)
            layout.addWidget(list_widget)
            buttons = Q.QDialogButtonBox(Q.QDialogButtonBox.Ok | Q.QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
            self._configure_selection_help(dialog, layout, "input_options", (
                ("values", list_widget, item.title + " seçenekleri", "İşaretlenen kod seçeneklerini aday listesine ekler.",
                 "En az bir değer seç. Kodda tanımlanan seçenekler veya doğru/yanlış değerleri kullanılır; seçim onaylanana kadar plan değişmez. Birden fazla değer toplam test sayısını artırır."),
            ), buttons)
            if dialog.exec() != Q.QDialog.Accepted:
                return
            values = [list_widget.item(i).data(QtCore.Qt.UserRole)
                      for i in range(list_widget.count()) if list_widget.item(i).checkState() == QtCore.Qt.Checked]
        else:
            text, accepted = self._ask_text_with_help(
                "input_values", title=f"{item.title} değerleri",
                text=", ".join(map(str, values))
            )
            if not accepted:
                return
            values = [value.strip() for value in text.split(",") if value.strip()]
        if not values:
            self.plan_status.setText(f"{item.title}: en az bir değer seçin.")
            return
        try:
            for value in values:
                validate_input_value(item, value)
        except ValueError as exc:
            self.plan_status.setText(str(exc))
            return
        cell.setData(QtCore.Qt.UserRole, values)
        cell.setText(" · ".join(map(str, values[:8])) + (f" … ({len(values)})" if len(values) > 8 else ""))
        self.preview_plan()

    def edit_selected_scan_values(self):
        row = self.plan_inputs.currentRow()
        if row < 0 or row >= self.plan_inputs.rowCount():
            self.plan_status.setText("Önce düzenlemek istediğiniz input satırını seçin.")
            return
        self.edit_scan_values(self.plan_inputs.item(row, 4))

    def apply_symbol_profile(self, name):
        profile = FTMO_SYMBOL_PROFILES.get(name)
        if profile:
            self.symbols.setText(", ".join(profile))
            self.preview_plan()

    def apply_cost_template(self, name):
        template = self.cost_templates.get(name)
        if not template:
            return
        self.initial_capital.setValue(float(template["initial_capital"]))
        self.position_size.setValue(float(template["position_size"]))
        self.commission.setValue(float(template["commission_value"]))
        self.spread.setValue(float(template["spread"]))
        self.slippage.setValue(int(template["slippage"]))
        self.preview_plan()

    def save_cost_template(self):
        name, accepted = self._ask_text_with_help("cost_name")
        name = name.strip()
        if not accepted or not name:
            return
        self.cost_templates[name] = {
            "initial_capital": self.initial_capital.value(), "position_size": self.position_size.value(),
            "commission_value": self.commission.value(), "spread": self.spread.value(),
            "slippage": self.slippage.value(),
        }
        self.store.save_app_settings({"cost_templates": self.cost_templates})
        if self.cost_scenario.findText(name) < 0:
            self.cost_scenario.addItem(name)
        self.cost_scenario.setCurrentText(name)
        self.plan_status.setText(f"Maliyet şablonu kaydedildi: {name}")

    def _update_criteria_toggle(self, *_args):
        if self.criteria_toggle.isChecked():
            self.criteria_toggle.setText("Başarı kriterleri")
            return
        profit_factor = f"{self.min_pf.value():.2f}".replace(".", ",")
        drawdown = f"{self.max_dd.value():.2f}".replace(".", ",")
        self.criteria_toggle.setText(
            f"Başarı kriterleri · İşlem ≥{self.min_trades.value()} · "
            f"PF ≥{profit_factor} · DD <{drawdown}%"
        )

    def _current_plan(self):
        values = {}
        for row in range(self.plan_inputs.rowCount()):
            key = self.plan_inputs.item(row, 0).text()
            choice = self.plan_inputs.cellWidget(row, 3).currentText()
            item = self._plan_parsed_inputs[row]
            if choice == "Hariç tut":
                continue
            if choice == "Sabit bırak":
                if item.manual_definition_required:
                    raise ValueError(f"{item.title}: varsayılan okunamadı; değeri tanımlayın veya hariç tutun.")
                values[key] = [item.default]
            else:
                suggested = self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole) or []
                if not suggested:
                    raise ValueError(f"{item.title}: tarama için en az bir değer seçin.")
                if item.kind in {"int", "float"}:
                    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in suggested):
                        raise ValueError(f"{item.title}: geçerli sayısal değerler girin.")
                    if item.kind == "int" and any(not isinstance(v, int) for v in suggested):
                        raise ValueError(f"{item.title}: yalnız tam sayılar kullanılabilir.")
                    if item.minimum is not None and min(suggested) < item.minimum:
                        raise ValueError(f"{item.title}: en küçük değer {item.minimum}.")
                    if item.maximum is not None and max(suggested) > item.maximum:
                        raise ValueError(f"{item.title}: en büyük değer {item.maximum}.")
                if item.options and any(v not in item.options for v in suggested):
                    raise ValueError(f"{item.title}: kodda tanımlı seçenekleri kullanın.")
                values[key] = suggested
            for selected_value in values[key]:
                validate_input_value(item, selected_value)
        split = lambda text: tuple(value.strip() for value in text.split(",") if value.strip())
        variants = []
        if self.session_variants_check.isChecked():
            symbols = split(self.symbols.text())
            timeframes = self._timeframe_codes(self.timeframes.text())
            if not getattr(self, "_loaded_variants", None) and (len(symbols) != 1 or len(timeframes) != 1):
                raise ValueError("Birlikte session önerisi için tek sembol ve tek zaman dilimi seçin.")
            project = self.store.project(self.plan_project.currentData())
            if getattr(self, "_loaded_variants", None):
                if (tuple(symbols), tuple(timeframes)) != self._loaded_variant_scope:
                    raise ValueError("Kayıtlı ayar paketleri farklı sembol veya zaman dilimine taşınamaz. "
                                     "Yeni kapsam için seans paketleri seçimini kapatın.")
                from copy import deepcopy
                variants = deepcopy(self._loaded_variants)
            else:
                variants = observed_session_variants(
                    self._research_catalog, pine_hash=project["pine_hash"],
                    symbol=symbols[0], timeframe=timeframes[0],
                )
            if not variants:
                raise ValueError("Bu Pine sürümü/sembol/zaman dilimi için gözlenmiş session paketi yok.")
            variant_keys = {key for variant in variants for key in variant}
            if any(key in variant_keys and len(selected) > 1 for key, selected in values.items()):
                raise ValueError("Session paketleri açıkken session inputlarını ayrıca Tara yapmayın.")
            for key in variant_keys:
                values.pop(key, None)
        date_range = {}
        if self.date_from.text().strip(): date_range["from"] = self.date_from.text().strip()
        if self.date_to.text().strip(): date_range["to"] = self.date_to.text().strip()
        multiplier = COST_SCENARIOS.get(self.cost_scenario.currentText(), 1.0)
        scenario_costs = apply_cost_multiplier(
            self.commission.value(), self.spread.value(), self.slippage.value(), multiplier
        )
        assumptions = {"initial_capital": self.initial_capital.value(),
                       "position_size": self.position_size.value(),
                       "commission_type": "percent",
                       "analysis_timezone": self.analysis_timezone.currentText(),
                       "scenario": self.cost_scenario.currentText(), **scenario_costs}
        tradingview_inputs = {}
        input_mapping = {}
        mappings = {
            "initial_capital": (self.capital_input_id.text().strip(), assumptions["initial_capital"]),
            "position_size": (self.position_input_id.text().strip(), assumptions["position_size"]),
            "commission_value": (self.commission_input_id.text().strip(), assumptions["commission_value"]),
            "spread": (self.spread_input_id.text().strip(), assumptions["spread"]),
            "slippage": (self.slippage_input_id.text().strip(), assumptions["slippage"]),
        }
        for name, (input_id, value) in mappings.items():
            if input_id:
                if not input_id.startswith("in_") or not input_id[3:].isdigit():
                    raise ValueError(f"Geçersiz maliyet input ID: {input_id}")
                if input_id in tradingview_inputs:
                    raise ValueError("Aynı strateji inputu iki farklı maliyet alanına eşlenemez.")
                tradingview_inputs[input_id] = value
                input_mapping[name] = input_id
        from .cost_application import validate_spread_mapping, validate_direct_order_quantity
        validate_spread_mapping({"assumptions": assumptions, "tradingview_inputs": tradingview_inputs,
                                 "input_mapping": input_mapping})
        selected_project = self.store.project(self.plan_project.currentData())
        if selected_project:
            validate_direct_order_quantity(selected_project["pine_source"], values,
                {"assumptions": assumptions, "tradingview_inputs": tradingview_inputs})
        success_criteria = {
            "min_trades": self.min_trades.value(), "min_profit_factor": self.min_pf.value(),
            "min_win_rate_pct": self.min_win.value(), "max_drawdown_pct_exclusive": self.max_dd.value(),
            "min_net_profit": self.min_net.value(),
        }
        if self.ftmo_risk_check.isChecked():
            success_criteria.update(
                max_daily_loss_pct=self.max_daily_loss.value(),
                max_total_loss_pct=self.max_total_loss.value(),
            )
        return ScanPlan(
            study_id=self.study_id.text().strip(), symbols=split(self.symbols.text()),
            method=self.scan_method.currentData(),
            constraints=[dict(rule) for rule in self.constraint_editor.rules],
            sample_budget=int(self.sample_budget.text()) if self.scan_method.currentData() == "sample" else None,
            sample_seed=int(self.sample_seed.text()) if self.scan_method.currentData() == "sample" else 0,
            timeframes=self._timeframe_codes(self.timeframes.text()), input_values=values, date_range=date_range,
            criteria=success_criteria,
            costs={"assumptions": assumptions, "tradingview_inputs": tradingview_inputs,
                   "input_mapping": input_mapping},
            timeout=self.default_timeout.value(), poll_interval=self.default_poll.value(),
            stable_reads=self.default_stable.value(), variants=variants,
            research=getattr(self, "_loaded_research", {}),
        )

    def _before_count_close(self):
        support_dialog = getattr(self, "_support_dialog", None)
        if support_dialog is not None and support_dialog.job is not None:
            self._count_closing = True
            support_dialog.reject()
            return False
        backup_dialog = getattr(self, "_backup_dialog", None)
        if backup_dialog is not None and backup_dialog.job is not None:
            self._count_closing = True
            backup_dialog.request_cancel()
            return False
        if self.plan_counter.jobs or self._admission_job is not None:
            self._count_closing = True
            self.plan_counter.cancel()
            if self._admission_job is not None:
                self._admission_job.cancel()
            return False
        return True

    def _plan_count_drained(self):
        if self._count_closing:
            QtCore.QTimer.singleShot(0, self.window, self.window.close)

    def _plan_count_progress(self, value):
        if not self._count_closing and self._count_key is not None and value.get("revision") == self.plan_counter.revision:
            self.constraint_editor.status.setText(f"Sayılıyor: {value['examined']:,} ayar birleşimi incelendi…")

    def _receive_plan_count(self, value):
        if self._count_closing or self._count_key is None or value.get("revision") != self.plan_counter.revision:
            return
        self._count_result = value
        self.preview_plan()

    def _cancel_or_retry_count(self):
        if self._count_result and self._count_result.get("status") in {"cancelled", "error"}:
            self._count_key = None
            self.preview_plan()
        else:
            self.plan_counter.cancel()
            self.cancel_count_button.setEnabled(False)
            self.plan_status.setText("Sayım iptal ediliyor…")

    def preview_plan(self, *_args):
        if getattr(self, "_loading_plan_inputs", False):
            return
        if self._admission_job is not None:
            self.enqueue_plan_button.setEnabled(False)
            return
        try:
            plan = self._current_plan()
            self.run_choice.request(self.plan_project.currentData(), plan)
            key = json.dumps(plan.to_dict(), sort_keys=True, allow_nan=False)
            if plan.constraints and plan.cartesian_count > 10000:
                if key != self._count_key:
                    self._count_key = key
                    self._count_result = None
                    self.plan_counter.start(plan)
                self.cancel_count_button.show()
                value = self._count_result
                if value is None or value.get("status") != "ready":
                    self.enqueue_plan_button.setEnabled(False)
                    self.cancel_count_button.setEnabled(True)
                    cancelled = value and value.get("status") in {"cancelled", "error"}
                    self.cancel_count_button.setText("Sayımı yeniden dene" if cancelled else "Sayımı iptal et")
                    self.plan_status.setText(value.get("message", "Sayım iptal edildi; yeniden deneyebilirsin.") if cancelled
                                             else "Kombinasyonlar arka planda sayılıyor; tamamlanmadan başlatılamaz.")
                    self.plan_factors.clear()
                    return
                relation_counts, count = value, value["tasks"]
                self.cancel_count_button.hide()
            else:
                self.plan_counter.cancel()
                self._count_key = None
                self._count_result = None
                self.cancel_count_button.hide()
                count = plan.task_count
                relation_counts = plan.constraint_counts()
            self.constraint_editor.status.setText(
                f"Kural öncesi: {relation_counts['before']:,} · Atlanan: {relation_counts['skipped']:,} · Kalan: {relation_counts['remaining']:,}")
            if hasattr(self, "field_errors"):
                self.field_errors.clear()
            factors = dict(plan.workload_factors())
            input_product = 1
            input_titles = {self.plan_inputs.item(row, 0).text(): item.title
                            for row, item in enumerate(self._plan_parsed_inputs)}
            growing_inputs = []
            for key, size in plan.workload_factors()[3:]:
                input_product *= size
                if size > 1:
                    growing_inputs.append((input_titles.get(key, key), size))
            growing_inputs.sort(key=lambda entry: (-entry[1], entry[0]))
            top = ", ".join(f"{title} ×{size}" for title, size in growing_inputs[:3])
            if len(growing_inputs) > 3:
                top += f" ve {len(growing_inputs) - 3} diğer input"
            self.plan_factors.setText(
                f"{factors['symbols']} sembol × {factors['timeframes']} zaman dilimi × "
                f"{factors['variants']} ayar paketi × {input_product} ayar birleşimi = {count:,} test"
                + (f" · En büyük çarpanlar: {top}" if top else " · Değişken input yok")
            )
            self.session_variants_check.setText(
                f"Araştırılmış session ayarlarını birlikte tara ({len(plan.variants)} paket)"
                if plan.variants else "Aynı sembol/TF için araştırılmış session ayarlarını birlikte tara"
            )
            disk_kb = count * 2.5
            disk_text = (f"{disk_kb:.1f} KB" if disk_kb < 1024 else
                         f"{disk_kb / 1024:.1f} MB")
            warning = " · geniş arama/curve-fitting riski" if count > 10_000 else ""
            observed = self.store.observed_seconds_per_test(self.plan_project.currentData(), plan=plan.to_dict())
            duration = f" · tek grafik tahmini {self._format_duration(count * observed)}" if observed else " · süre için karşılaştırılabilir geçmiş veri yok"
            selected = self.strategy_picker.currentData()
            selected_strategy = bool(self.study_id.text().strip())
            source_confirmed = bool(isinstance(selected, dict) and selected.get("source_confirmed"))
            dates_blocked = bool(plan.date_range) and not (
                GncZihinDriver.date_range_ready and GncZihinDriver.deep_capture_ready)
            if hasattr(self, "enqueue_plan_button"):
                waiting = bool(getattr(self, "_connection_timer", None) and self._connection_timer.isActive())
                self.enqueue_plan_button.setEnabled(count > 0 and not dates_blocked and not self._preparing and not waiting)
            self.plan_status.setStyleSheet("color:#6b4c22")
            ready = (
                " · strateji kaynağı onaylı" if source_confirmed else
                " · strateji bulundu, kaynak onayı worker ekranında gerekli" if selected_strategy else
                " · TradingView hazırlık sırasında bağlanacak"
            )
            if dates_blocked:
                ready = (
                    " · özel tarih henüz TradingView'e otomatik uygulanamıyor; "
                    "tarihli görev kuyruğa alınamaz"
                )
            self.plan_status.setText(f"{count:,} görev · tahmini {disk_text}{duration}{warning}{ready}")
            if plan.method == "sample":
                self.plan_status.setText(self.plan_status.text() +
                    f" · {plan.cartesian_count:,} olası testten örnekleme; denenmeyen değerler sonuç değildir (tohum {plan.sample_seed})")
            if self.cost_scenario.currentText() in {"Orta stres", "Ağır stres"} and not any(
                    field.value() for field in (self.commission, self.spread, self.slippage)):
                self.field_errors.setText("Stres senaryosu seçili, fakat tüm maliyetler sıfır. Bu ayarlar maliyet stresi uygulamaz.")
            self.scan_flow_status.setText(
                f"Proje: hazır · Strateji: {'kaynak onaylı' if source_confirmed else 'yapısal eşleşme' if selected_strategy else 'eksik'} · "
                f"Plan: {count:,} kombinasyon hazır · Sekmeler: başlatmadan önce kullanıcı onayı"
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self.plan_counter.cancel()
            self._count_key = None
            self._count_result = None
            self.cancel_count_button.hide()
            if hasattr(self, "enqueue_plan_button"):
                self.enqueue_plan_button.setEnabled(False)
            self.plan_status.setStyleSheet("color:#b54c42"); self.plan_status.setText(str(exc))
            lengths = [len(self.plan_inputs.item(r, 4).data(QtCore.Qt.UserRole) or [])
                       if self.plan_inputs.cellWidget(r, 3).currentText() == "Tara" else 1
                       for r in range(self.plan_inputs.rowCount())]
            self.plan_factors.setText(f"Ayar birleşimi: {math.prod(lengths) if lengths else 0}. Sembol ve zaman dilimleri tamamlandığında toplam test sayısı hesaplanır.")
            if hasattr(self, "field_errors"):
                self.field_errors.setText(str(exc))
            self.scan_flow_status.setText("Proje/strateji/plan: eksik bilgiyi tamamlayın · Sekmeler: onay gerekli")

    def enqueue_current_plan(self):
        if self._admission_job is not None:
            return
        try:
            project_id = self.plan_project.currentData()
            if project_id is None: raise ValueError("Proje seçilmedi.")
            selected = self.strategy_picker.currentData()
            if not isinstance(selected, dict) or selected.get("study_id") != self.study_id.text().strip():
                raise ValueError("Görev hazırlamadan önce açık stratejiyi yeniden seçin.")
            plan = self._current_plan()
            if plan.date_range and not (GncZihinDriver.date_range_ready and GncZihinDriver.deep_capture_ready):
                raise ValueError(
                    "Özel tarih aralığı henüz TradingView'de otomatik uygulanmıyor; "
                    "tarihli görevler kuyruklanamaz."
                )
            self._start_plan_admission(project_id, plan, **self.run_choice.request(project_id, plan))
        except (ValueError, json.JSONDecodeError) as exc:
            self.plan_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.plan_status.setText(str(exc))

    def _start_plan_admission(self, project_id, plan, callback=None, *, require_pending_subset=False,
                              new_run=False, run_id=None, settings=None):
        if self._admission_job is not None:
            return False
        from .plan_jobs import PlanAdmissionJob
        self._admission_result = None
        self._admission_callback = callback
        job = PlanAdmissionJob(self.store, project_id, plan, settings=self._input_choices_settings() if settings is None else settings,
                               require_pending_subset=require_pending_subset, new_run=new_run, run_id=run_id)
        self._admission_job = job
        self._preparing = True
        self.update_result_actions()
        self.enqueue_plan_button.setEnabled(False)
        self.parallel_count.setEnabled(False)
        self.run_choice.setEnabled(False)
        self.plan_project.setEnabled(False)
        self.cancel_queue_button.setEnabled(True)
        self.cancel_queue_button.show()
        self.plan_status.setText("Görevler arka planda hazırlanıyor; tamamlanana kadar kayıt kalıcı değildir.")
        job.progress.connect(self._plan_admission_progress)
        job.result.connect(self._plan_admission_result)
        job.finished.connect(self._finish_plan_admission)
        job.start()
        return True

    def _plan_admission_progress(self, value):
        if not self._count_closing and self._admission_job is not None:
            self.plan_status.setText(f"Kuyruk hazırlanıyor: {value['processed']:,} test işlendi · "
                                    f"{value['inserted']:,} aday görev · henüz kalıcı kayıt değil.")

    def _plan_admission_result(self, value):
        self._admission_result = value

    def _cancel_plan_admission(self):
        if self._admission_job is not None:
            self._admission_job.cancel()
            self.cancel_queue_button.setEnabled(False)
            self.plan_status.setText("Kuyruk hazırlığı iptal ediliyor; işlem geri alınıyor…")

    def _finish_plan_admission(self):
        job = self._admission_job
        result = self._admission_result or {"status": "error", "message": "Kuyruk işlemi sonuç bildirmedi."}
        callback = self._admission_callback
        self._admission_job = None
        self._admission_callback = None
        self._preparing = False
        self.update_result_actions()
        job.deleteLater()
        if self._count_closing:
            QtCore.QTimer.singleShot(0, self.window, self.window.close)
            return
        self.cancel_queue_button.hide()
        self.run_choice.setEnabled(True)
        self.plan_project.setEnabled(True)
        if result["status"] == "ready":
            self.run_choice.refresh(result["project_id"], selected=result["run_id"])
        self.parallel_count.setEnabled(not bool(self.supervisor and self.supervisor.running))
        self.preview_plan()
        if result["status"] == "ready":
            self.plan_status.setText(f"{result['inserted']:,} yeni görev kalıcı kuyruğa eklendi.")
            self.refresh_dashboard()
            if callback is not None:
                try:
                    callback(result["run_id"])
                except Exception as error:
                    self.connection_status.setText("İşlem gerekli: " + self._friendly_error(error))
        elif result["status"] == "cancelled":
            self.plan_status.setText("Kuyruk hazırlığı iptal edildi; bu işlemin görevleri ve ayarları geri alındı.")
        else:
            self.plan_status.setText("Kuyruk hazırlanamadı; değişiklikler geri alındı. " +
                                     self._friendly_error(RuntimeError(result["message"])))

    def _active_result_filter_labels(self):
        labels = []
        if self.result_filter.currentText() != "Tümü":
            labels.append(self.result_filter.currentText())
        if self.filter_pf.value() > 0:
            labels.append(self.filter_pf.text())
        if self.filter_dd.value() < 100:
            labels.append(self.filter_dd.text())
        if self.filter_trades.value() > 0:
            labels.append(self.filter_trades.text())
        if self.filter_win.value() > 0:
            labels.append(self.filter_win.text())
        if self.filter_net.value() > -1_000_000_000:
            labels.append(self.filter_net.text())
        if self.filter_symbol.text().strip():
            labels.append(f"Sembol: {self.filter_symbol.text().strip()}")
        if self.filter_tf.text().strip():
            labels.append(f"Zaman: {self.filter_tf.text().strip()}")
        if self.filter_evidence.currentText() != "Tümü":
            labels.append(self.filter_evidence.currentText())
        if self.filter_cost_scenario.currentData() != "Tümü":
            labels.append(f"Maliyet: {self.filter_cost_scenario.currentData()}")
        if self.filter_dates.isChecked():
            labels.append(
                f"Dönem: {self.filter_from.date().toString('yyyy-MM-dd')}–"
                f"{self.filter_to.date().toString('yyyy-MM-dd')}"
            )
        return labels

    def _refresh_result_filter_chips(self):
        while self.result_chip_grid.count():
            item = self.result_chip_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        labels = self._active_result_filter_labels()
        for index, label in enumerate(labels):
            chip = self.QtWidgets.QLabel(label, objectName="filterChip")
            chip.setSizePolicy(self.QtWidgets.QSizePolicy.Maximum, self.QtWidgets.QSizePolicy.Fixed)
            chip.setToolTip(label)
            self.result_chip_grid.addWidget(chip, index // 4, index % 4)
        self.result_active_filters.setVisible(bool(labels))

    def clear_result_filters(self):
        controls = (
            self.result_filter, self.filter_pf, self.filter_dd, self.filter_trades,
            self.filter_win, self.filter_net, self.filter_symbol, self.filter_tf,
            self.filter_evidence, self.filter_cost_scenario, self.filter_dates,
            self.saved_result_filter,
        )
        previous = [control.blockSignals(True) for control in controls]
        try:
            self.result_filter.setCurrentText("Tümü")
            self.filter_pf.setValue(0)
            self.filter_dd.setValue(100)
            self.filter_trades.setValue(0)
            self.filter_win.setValue(0)
            self.filter_net.setValue(-1_000_000_000)
            self.filter_symbol.clear()
            self.filter_tf.clear()
            self.filter_evidence.setCurrentText("Tümü")
            self.filter_cost_scenario.setCurrentIndex(0)
            self.filter_dates.setChecked(False)
            self.saved_result_filter.setCurrentIndex(0)
        finally:
            for control, was_blocked in zip(controls, previous):
                control.blockSignals(was_blocked)
        self.refresh_results()

    def _refresh_result_progress(self):
        if not hasattr(self, "run_progress"):
            return
        project_id = self.result_project.currentData()
        active_run_id = (getattr(self, "_active_run_id", None)
                         if project_id == getattr(self, "_active_run_project", None) else None)
        tasks = (self.store.run_tasks(active_run_id) if active_run_id is not None else
                 self.store.tasks(project_id) if project_id is not None else [])
        active = bool(self.supervisor and self.supervisor.running and
                      project_id == self.plan_project.currentData())
        errors = ([state.error for state in self.supervisor.states.values() if state.error]
                  if self.supervisor and project_id == self.plan_project.currentData() else [])
        completed = sum(task["status"] == "done" for task in tasks)
        failed = sum(task["status"] in {"failed", "manual_review", "invalid"} for task in tasks)
        label = ("Durduruluyor" if active and getattr(self.supervisor, "stopping", False) else
                 "Tarama durdu" if self.supervisor and getattr(self.supervisor, "stop_requested", False) else
                 "Tarama çalışıyor" if active else
                 "Tarama tamamlandı" if tasks and completed == len(tasks) else "Tarama durdu")
        current = next((task for task in tasks if task["status"] == "running"), None)
        operation = (f" Şimdi: {current['payload'].get('symbol')} / "
                     f"{self._timeframe_label(current['payload'].get('timeframe', ''))}."
                     if active and current else "")
        self.run_progress.setText(self._friendly_error(errors[0]) if errors else
            f"{label}: {completed}/{len(tasks)} test tamamlandı; {failed} test işlem gerektiriyor.{operation}"
            if tasks else "Bu stratejide henüz tarama başlatılmadı.")
        self.run_progress.setToolTip("\n".join(errors))
        self.parallel_count.setEnabled(not bool(getattr(self, "_preparing", False) or (self.supervisor and self.supervisor.running)))
        if active_run_id is not None:
            performance = self.store.run_performance(active_run_id)
            recent = performance["tests_per_hour"]
            average = performance["average_tests_per_hour"]
            rate = f"{recent:.0f} test/saat" if recent else "yeterli veri yok"
            mean = f"{average:.0f} test/saat" if average else "yeterli veri yok"
            graphs = sum(state.status in {"starting", "running", "restarting", "idle", "stopping"} for state in self.supervisor.states.values()) if active else 0
            eta = performance["eta_seconds"]
            self.run_performance.setText(
                f"Son 5 dk: {rate} · çalışma ortalaması: {mean} · aktif grafik: {graphs}"
                f" · doğrulanmış: {performance['verified_count']} · ETA: "
                + (self._format_duration(eta) if eta is not None else "yeterli karşılaştırılabilir veri yok"))
        else:
            self.run_performance.setText("Hız: ölçüm bekleniyor · aktif grafik: 0")

    def measure_parallel_resources(self):
        try:
            snapshot = system_snapshot()
            recommendation = recommend_workers(snapshot)
            self.parallel_recommendation.setText(f"Kaynak önerisi: {recommendation.recommended} grafik · boş RAM {snapshot.available_memory_bytes / 1024**3:.1f} GB")
        except Exception as exc:
            self.parallel_recommendation.setText("Kaynaklar ölçülemedi.")
            self.parallel_recommendation.setToolTip(str(exc))

    def refresh_results(self, *_args):
        project_id = self.result_project.currentData()
        self._refresh_result_progress()
        self.refresh_saved_result_filters(project_id)
        classification = self.result_filter.currentText() if hasattr(self, "result_filter") else "Tümü"
        # Keep the unfiltered result count for an honest empty state: a project
        # may have completed scans even when none passed the success criteria.
        source_rows = self.store.results(project_id) if project_id is not None else []
        selected_scenario = self.filter_cost_scenario.currentData()
        scenarios = sorted({
            str((((row.get("payload") or {}).get("costs") or {}).get("assumptions") or {}).get("scenario")
                or "Belirtilmedi") for row in source_rows
        })
        self.filter_cost_scenario.blockSignals(True)
        self.filter_cost_scenario.clear()
        self.filter_cost_scenario.addItem("Tüm maliyet senaryoları", "Tümü")
        for scenario in scenarios:
            self.filter_cost_scenario.addItem(scenario, scenario)
        index = self.filter_cost_scenario.findData(selected_scenario)
        self.filter_cost_scenario.setCurrentIndex(index if index >= 0 else 0)
        self.filter_cost_scenario.blockSignals(False)
        dates_enabled = self.filter_dates.isChecked()
        rows = filter_results(
            source_rows, classification=classification,
            min_pf=self.filter_pf.value(), max_dd=self.filter_dd.value(),
            min_trades=self.filter_trades.value(), min_win=self.filter_win.value(),
            min_net=self.filter_net.value(), symbol=self.filter_symbol.text(),
            timeframe=self.filter_tf.text(), evidence=self.filter_evidence.currentText(),
            cost_scenario=self.filter_cost_scenario.currentData(),
            date_from=self.filter_from.date().toString("yyyy-MM-dd") if dates_enabled else "",
            date_to=self.filter_to.date().toString("yyyy-MM-dd") if dates_enabled else "",
        )
        self._refresh_result_filter_chips()
        self._result_rows = rows
        self._result_by_id = {row["task_id"]: row for row in rows}
        if self._open_result_task_id not in self._result_by_id:
            self.result_detail_dock.hide()
        self.result_scatter.set_rows(rows)
        self.result_scatter.setVisible(bool(rows))
        self.result_export_button.setEnabled(project_id is not None)
        self.result_retry_button.setEnabled(project_id is not None)
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(rows))
        project = self.store.project(project_id) if project_id is not None else None
        parsed = parse_strategy_inputs(project["pine_source"]) if project else []
        for row_index, row in enumerate(rows):
            payload, metrics = row["payload"], row["metrics"]
            differences = [f"{item.title}: {payload.get('inputs', {}).get(f'in_{index}')}"
                for index, item in enumerate(parsed) if f'in_{index}' in payload.get('inputs', {})
                and payload['inputs'][f'in_{index}'] != item.default]
            name = ", ".join(differences) if differences else "Varsayılan ayarlar"
            values = (name, payload.get("symbol"), self._timeframe_label(payload.get("timeframe", "")),
                      row["classification"], metrics.get("trades"), metrics.get("profit_factor"),
                      metrics.get("win_rate_pct"), metrics.get("max_drawdown_pct"),
                      metrics.get("net_profit"), "Doğrulandı" if row["verified"] else "İncele")
            for column, value in enumerate(values):
                cell = self.QtWidgets.QTableWidgetItem()
                cell.setData(QtCore.Qt.DisplayRole, value if value is not None else "—")
                cell.setData(QtCore.Qt.UserRole, row["task_id"])
                if column == 0:
                    cell.setToolTip("Teknik kayıt kimliği: " + row["task_key"])
                if 4 <= column <= 8:
                    cell.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                if column == 9:
                    cell.setToolTip("Doğrulama ayrıntısı için satıra çift tıklayın.")
                self.results_table.setItem(row_index, column, cell)
        self.results_table.setSortingEnabled(True)
        visible_rows = min(len(rows), 12)
        table_height = (self.results_table.horizontalHeader().height()
                        + visible_rows * self.results_table.verticalHeader().defaultSectionSize()
                        + self.results_table.frameWidth() * 2 + 12)
        self.results_table.setMaximumHeight(max(108, min(470, table_height)))
        self.results_table.setMinimumHeight(max(108, min(240, table_height)))
        self.results_table.setVisible(bool(rows))
        self.result_empty.setVisible(not rows)
        if source_rows:
            empty_message = (
                "Bu filtrelere uyan sonuç yok. Dönemi bilinmeyen kayıtlar tarih filtresine dahil edilmez."
                if dates_enabled else
                "Bu görünümde sonuç yok. Filtreyi gevşetin veya tüm kayıtları dışa aktarın."
            )
        elif project_id is None:
            empty_message = "Sonuçları görmek için bir proje seçin."
        else:
            task_counts = self.store.counts(project_id)
            if not sum(task_counts.values()):
                empty_message = "Bu projede henüz görev yok. Tarama ayarlarından bir plan hazırlayın."
            elif task_counts.get("failed", 0) or task_counts.get("manual_review", 0):
                empty_message = "Henüz sonuç yok; müdahale gerektiren görevleri ve son olayları inceleyin."
            elif task_counts.get("pending", 0) or task_counts.get("running", 0):
                empty_message = "Görevler bekliyor veya çalışıyor. Çalışma sekmelerinin durumunu kontrol edin."
            else:
                empty_message = "Bu projede gösterilecek sonuç yok. Tüm görev kayıtlarını dışa aktarabilirsiniz."
        self.result_empty.setText(empty_message)
        self.update_result_actions()
        events = self.store.events(100)
        if project_id is not None:
            task_ids = {task["id"] for task in self.store.tasks(project_id)}
            events = [event for event in events if event["task_id"] in task_ids]
        self.result_events_empty.setVisible(not events)
        self.events_table.setVisible(bool(events))
        self.events_table.setRowCount(len(events))
        for row_index, event in enumerate(events):
            for column, value in enumerate((event["level"], event["worker_id"], event["task_id"], event["message"], event["screenshot_path"])):
                cell = self.QtWidgets.QTableWidgetItem(str(self._friendly_error(value) if column == 3 else value if value is not None else "—"))
                if column == 3:
                    cell.setToolTip("Teknik ayrıntılar:\n" + str(value))
                elif column == 4:
                    cell.setToolTip(event_evidence_tooltip(self.store, value, verify=False))
                    cell.setData(QtCore.Qt.UserRole, value)
                self.events_table.setItem(row_index, column, cell)

    def check_event_evidence(self, row, column):
        if column != 4:
            return
        cell = self.events_table.item(row, column)
        if cell is None:
            return
        reference = cell.data(QtCore.Qt.UserRole)
        # Verification is deliberately requested by the user, not a refresh side effect.
        from .backup_jobs import EvidenceJob
        from .backup_dialog import BackupProgressDialog
        dialog = BackupProgressDialog(EvidenceJob(self.store, reference), self.window, self.help_registry)
        dialog.setWindowTitle("Kanıt dosyası kontrolü")
        dialog.note.setText("Salt okunur dosya kontrolü arka planda yapılır; özgün olay kaydı değiştirilmez.")
        dialog.start()
        dialog.exec()
        result = dialog.outcome or {}
        if result.get('status') == 'cancelled':
            return
        if result.get('status') == 'error':
            message = "Kanıt kontrolü başarısız: " + result.get('message', '')
        elif result.get('path'):
            message = "Geri yüklenen kanıtın dosya bütünlüğü doğrulandı:\n" + result['path']
        else:
            message = "Geri yüklenen kanıt bağlantısı bulunamadı; özgün dosyanın mevcut olduğu varsayılmaz."
        message += "\n\nÖzgün kayıt (değiştirilmedi):\n" + str(reference)
        self.QtWidgets.QMessageBox.information(self.window, "Kanıt dosyası", message)

    def refresh_saved_result_filters(self, project_id):
        presets = ((self.store.settings(project_id) or {}).get("result_filters") or {}) if project_id else {}
        current = self.saved_result_filter.currentText()
        self.saved_result_filter.blockSignals(True)
        self.saved_result_filter.clear()
        self.saved_result_filter.addItem("Kayıtlı filtre seç", None)
        for name in sorted(presets):
            self.saved_result_filter.addItem(name, presets[name])
        index = self.saved_result_filter.findText(current)
        if index >= 0:
            self.saved_result_filter.setCurrentIndex(index)
        self.saved_result_filter.blockSignals(False)

    def _current_result_filter_values(self):
        return {
            "classification": self.result_filter.currentText(), "min_pf": self.filter_pf.value(),
            "max_dd": self.filter_dd.value(), "min_trades": self.filter_trades.value(),
            "min_win": self.filter_win.value(), "min_net": self.filter_net.value(),
            "symbol": self.filter_symbol.text(), "timeframe": self.filter_tf.text(),
            "evidence": self.filter_evidence.currentText(), "dates": self.filter_dates.isChecked(),
            "cost_scenario": self.filter_cost_scenario.currentData(),
            "date_from": self.filter_from.date().toString("yyyy-MM-dd"),
            "date_to": self.filter_to.date().toString("yyyy-MM-dd"),
        }

    def save_result_filter(self):
        project_id = self.result_project.currentData()
        if project_id is None:
            return
        name, accepted = self._ask_text_with_help("filter_name")
        name = name.strip()
        if not accepted or not name:
            return
        presets = (self.store.settings(project_id) or {}).get("result_filters") or {}
        presets[name] = self._current_result_filter_values()
        self.store.save_settings(project_id, {"result_filters": presets})
        self.refresh_saved_result_filters(project_id)
        self.saved_result_filter.setCurrentText(name)

    def apply_saved_result_filter(self, _index):
        values = self.saved_result_filter.currentData()
        if not isinstance(values, dict):
            return
        widgets = (self.result_filter, self.filter_pf, self.filter_dd, self.filter_trades,
                   self.filter_win, self.filter_net, self.filter_symbol, self.filter_tf,
                   self.filter_evidence, self.filter_cost_scenario,
                   self.filter_dates, self.filter_from, self.filter_to)
        blockers = [QtCore.QSignalBlocker(widget) for widget in widgets]
        try:
            self.result_filter.setCurrentText(values.get("classification", "Başarılı"))
            for key, widget in (("min_pf", self.filter_pf), ("max_dd", self.filter_dd),
                                ("min_trades", self.filter_trades), ("min_win", self.filter_win),
                                ("min_net", self.filter_net)):
                widget.setValue(values.get(key, widget.value()))
            self.filter_symbol.setText(values.get("symbol", ""))
            self.filter_tf.setText(values.get("timeframe", ""))
            self.filter_evidence.setCurrentText(values.get("evidence", "Tümü"))
            scenario_index = self.filter_cost_scenario.findData(values.get("cost_scenario", "Tümü"))
            self.filter_cost_scenario.setCurrentIndex(scenario_index if scenario_index >= 0 else 0)
            self.filter_dates.setChecked(bool(values.get("dates")))
            for key, widget in (("date_from", self.filter_from), ("date_to", self.filter_to)):
                date = QtCore.QDate.fromString(values.get(key, ""), "yyyy-MM-dd")
                if date.isValid():
                    widget.setDate(date)
        finally:
            del blockers
        self.refresh_results()

    def selected_result_rows(self):
        indices = self.results_table.selectionModel().selectedRows()
        return [self._result_by_id[self.results_table.item(index.row(), 0).data(QtCore.Qt.UserRole)]
                for index in indices if self.results_table.item(index.row(), 0) is not None]

    def update_result_actions(self, *_args):
        count = len(self.results_table.selectionModel().selectedRows())
        self.result_compare.setEnabled(2 <= count <= 5)
        self.result_validate.setEnabled(count >= 1)
        self.result_refine.setEnabled(count >= 1 and not self._preparing and self._admission_job is None)
        self.result_period.setEnabled(self.result_refine.isEnabled())
        self.result_next_training.setEnabled(self.result_refine.isEnabled())

    def period_selected_results(self, *, training):
        from .period_research import selection_context, validation_plan, completed_validation, training_plan, run_snapshot
        from .period_dialog import PeriodDialog
        from .comparison import period_summary
        if self._preparing or self._admission_job is not None:
            return
        project_id = self.result_project.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        rows = self.selected_result_rows()
        try:
            if project is None or not rows or any(not row.get("verified") for row in rows):
                raise ValueError("Aynı araştırma koşusundan doğrulanmış sonuçları seç.")
            histories = [self.store.result_history(row["task_id"]) for row in rows]
            if any(not history for history in histories):
                raise ValueError("Seçilen sonuçların değişmez kaynak ve dönem geçmişi gerekli.")
            ids = [history[-1]["id"] for history in histories]
            source = project["pine_source"]
            if training:
                with self.store.connect() as connection:
                    run_ids = {connection.execute("SELECT run_id FROM run_tasks WHERE task_id=?", (row["task_id"],)).fetchone()[0] for row in rows}
                    if len(run_ids) != 1:
                        raise ValueError("Sonraki eğitim için tek tamamlanmış doğrulama koşusu seç.")
                    previous_id = next(iter(run_ids))
                    previous = completed_validation(connection, project_id, previous_id, source)
                    selection = run_snapshot(connection, project_id, previous["research"]["selection_run_id"], source)
                summary = "Önceki doğrulama dönemi:\n" + period_summary(previous["date_range"]) + "\nSembol: " + ", ".join(previous["symbols"]) + "\nZaman dilimi: " + ", ".join(self._timeframe_label(tf) for tf in previous["timeframes"]) + "\n\nÖnceki eğitim aralıkları korunur; doğrulama kazananı otomatik seçilmez. Yeni eğitim sonuçlarından adayları ayrıca seçeceksin."
                builder = lambda window: training_plan(previous, selection, previous_id, window)
            else:
                with self.store.connect() as connection:
                    context = selection_context(connection, project_id, ids, source)
                    previous_id = context["previous_validation_run_id"]
                    previous = completed_validation(connection, project_id, previous_id, source) if previous_id is not None else None
                payload = context["records"][0]["payload"]
                summary = "Seçim dönemi:\n" + period_summary(context["selection_period"]) + "\nSembol: " + payload["symbol"] + "\nZaman dilimi: " + self._timeframe_label(payload["timeframe"]) + "\n\n" + "\n".join(
                    "Aday " + str(index + 1) + ": " + ", ".join(f"{context['definitions'][key].title}: {value}" for key, value in record["payload"]["inputs"].items())
                    for index, record in enumerate(context["records"]))
                builder = lambda window: validation_plan(context, window, previous_validation_period=previous["date_range"] if previous else None)
        except (ValueError, TypeError) as error:
            self.QtWidgets.QMessageBox.information(self.window, "Dönem araştırması", str(error))
            return
        dialog = PeriodDialog(builder, summary, training=training, parent=self.window, help_registry=self.help_registry)
        try:
            if dialog.exec() != self.QtWidgets.QDialog.Accepted or dialog.approved_plan is None:
                return
            plan = dialog.approved_plan
        finally:
            dialog.scope.finish_scope(); dialog.deleteLater()
        self._admit_research_plan(project_id, plan)

    def refine_selected_results(self):
        from .coarse_fine import candidate_context
        from .refinement_dialog import RefinementDialog
        if self._preparing or self._admission_job is not None:
            return
        project_id = self.result_project.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        rows = self.selected_result_rows()
        try:
            if project is None or not rows or any(not row.get("verified") for row in rows):
                raise ValueError("Aynı tamamlanmış kaba koşudan doğrulanmış aday sonuçları seç.")
            histories = [self.store.result_history(row["task_id"]) for row in rows]
            if any(not history for history in histories):
                raise ValueError("Adayların değişmez sonuç geçmişi bulunamadı; yeniden kaba tara.")
            with self.store.connect() as connection:
                context = candidate_context(connection, project_id, [history[-1]["id"] for history in histories], project["pine_source"])
        except (ValueError, TypeError) as error:
            self.QtWidgets.QMessageBox.information(self.window, "Ayrıntılı tarama", str(error))
            return
        dialog = RefinementDialog(context, self.window, self.help_registry)
        try:
            if dialog.exec() != self.QtWidgets.QDialog.Accepted or dialog.approved_plan is None:
                return
            plan = dialog.approved_plan
        finally:
            dialog.scope.finish_scope()
            dialog.deleteLater()
        self._admit_research_plan(project_id, plan)

    def _admit_research_plan(self, project_id, plan):
        if plan.date_range and not (GncZihinDriver.date_range_ready and GncZihinDriver.deep_capture_ready):
            self.QtWidgets.QMessageBox.information(self.window, "Dönem doğrulaması gerekli",
                "Bu sürümde seçilen rapor dönemini doğrulayan sürücü hazır değil. Araştırma görevleri eklenmedi.")
            return
        def loaded(run_id):
            self.plan_project.setCurrentIndex(self.plan_project.findData(project_id))
            self.load_plan_inputs(saved_snapshot=plan.to_dict())
            self.run_choice.refresh(project_id, selected=run_id)
            self._show_page(2)
            self.plan_status.setText("Araştırma görevleri eklendi. Kaynak ve grafik hazırlığını kontrol ederek Hazırla ve başlat seç.")
        self._start_plan_admission(project_id, plan, loaded, new_run=True, settings={})

    def detach_refinement(self):
        self._loaded_research = {}
        self.refinement_detach.setEnabled(False)
        self.preview_plan()
        self.plan_status.setText("Aday bağlantısı kaldırıldı; bu bağımsız bir plan. Geçmiş koşu ve sonuçlar değişmedi.")

    def compare_selected_results(self):
        from .comparison import build_comparison
        rows = self.selected_result_rows()
        if not 2 <= len(rows) <= 5:
            self.QtWidgets.QMessageBox.information(self.window, "Sonuç karşılaştırma", "Karşılaştırmak için 2–5 sonuç satırı seçin.")
            return
        comparison = build_comparison(self.store, rows)
        dialog = self.QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Sonuçları yan yana karşılaştır"); dialog.resize(960, 640)
        layout = self.QtWidgets.QVBoxLayout(dialog)
        warning = self.QtWidgets.QLabel(comparison["warning"])
        warning.setWordWrap(True)
        layout.addWidget(warning)
        table = self.QtWidgets.QTableWidget(len(comparison["lines"]), len(rows))
        table.setHorizontalHeaderLabels([f"Test {index + 1}" for index in range(len(rows))])
        labels = [label for label, _values in comparison["lines"]]
        table.setVerticalHeaderLabels(labels)
        from PySide6 import QtGui
        for line, (label, values) in enumerate(comparison["lines"]):
            table.verticalHeaderItem(line).setToolTip(label + ": seçili testlerin kayıtlı değeri. Eksik kanıt eşitlik veya başarı anlamına gelmez.")
            raw_values = comparison["raw_lines"].get(label)
            different = (len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in raw_values}) > 1
                         if raw_values is not None else len(set(values)) > 1)
            for column, value in enumerate(values):
                if label in {"Zaman dilimi", "Zaman dilimi (grafik)"} and value != "Kanıt yok":
                    value = self._timeframe_label(value)
                item = self.QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value + "\n\nKayıtlı ayrıntılar:\n" + json.dumps(raw_values[column],
                    ensure_ascii=False, indent=2) if raw_values is not None else value)
                if different:
                    item.setBackground(QtGui.QColor("#fff3d6"))
                table.setItem(line, column, item)
        table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(self.QtWidgets.QHeaderView.Stretch)
        table.verticalHeader().setSectionResizeMode(self.QtWidgets.QHeaderView.ResizeToContents)
        table.setWordWrap(True)
        layout.addWidget(table)
        close = self.QtWidgets.QPushButton("Kapat"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        scope = self._configure_readonly_dialog_help(dialog, layout, "comparison", (
            ("context", warning, "Karşılaştırma kapsamı", "Farklı koşulları ve eksik kanıtı açıklar.",
             "Kaynak, sağlayıcı, sembol, zaman dilimi, planlanan ve raporlanan dönem, para birimi, sermaye ve maliyetleri kontrol et. Aynı görünen boş alanlar karşılaştırılabilir kanıt değildir. Bu pencere yeni test çalıştırmaz veya en iyi ayar seçmez."),
            ("table", table, "Ayar ve metrik farkları", "Seçili 2–5 testin ayar ve metriklerini yan yana gösterir.",
             "Altın renk farklı kayıtlı değerleri belirtir; kazananı veya istatistiksel anlamlılığı göstermez. Kaynak ve ayar adları test sırasında saklanan koddan okunur, güncel proje kodundan uydurulmaz. TradingView uyarısı bilinmiyorsa yok kabul edilmez. Tablo salt okunurdur."),
        ), close)
        scope.register_columns("viewer.comparison.table", table, tuple(
            (f"Test {index + 1}", "Seçilen testin kayıtlı ayar ve metrikleri.",
             "Kayıt değişmez; eksik kanıt diğer testlerle eşitlik sayılmaz. Farklı koşul uyarılarını kontrol et.")
            for index in range(len(rows))))
        try:
            dialog.exec()
        finally:
            scope.finish_scope()
            dialog.deleteLater()

    def show_result_details(self, index):
        self.open_result_details_by_id(self.results_table.item(index.row(), 0).data(QtCore.Qt.UserRole))

    def open_result_details_by_id(self, task_id):
        row = self._result_by_id.get(task_id)
        if row is None:
            return
        metrics = row["metrics"]
        old_panel = self.result_detail_dock.widget()
        if old_panel is not None:
            self.help_registry.remove_tree(old_panel)
        panel = self.QtWidgets.QWidget(self.result_detail_dock)
        panel.setMinimumWidth(330)
        layout = self.QtWidgets.QVBoxLayout(panel)
        expand = self.QtWidgets.QPushButton(
            "Yan panele dön" if self.result_detail_dock.isFloating() else "Grafikleri büyük aç"
        )
        expand.clicked.connect(self.toggle_result_detail_size)
        self.result_detail_expand = expand
        layout.addWidget(expand)
        save_preset = self.QtWidgets.QPushButton("Bu testi preset olarak kaydet")
        save_preset.clicked.connect(lambda: self.save_local_preset(task_id))
        layout.addWidget(save_preset)
        scope = self.QtWidgets.QLabel(
            "Risk göstergeleri kapanmış işlemlerden hesaplandı; FTMO gün içi açık pozisyon equity ihlalinin kanıtı değildir."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        if (row.get("payload", {}).get("costs") or {}).get("assumptions"):
            cost_scope = (row.get("evidence") or {}).get("cost_verification_scope")
            detail = (
                "Sermaye, kontrat büyüklüğü, komisyon türü/sayısı ve slippage tick değeri "
                "TradingView Properties ile XLSX'te eşleşti; spread etkisi doğrulanamadı."
                if cost_scope == "strategy_properties_ui_and_xlsx_spread_unverified" else
                "Sermaye, kontrat büyüklüğü, komisyon türü/sayısı ve slippage tick değeri "
                "TradingView Properties'te eşleşti; XLSX ve spread etkisi bu sonuçta doğrulanmadı."
                if cost_scope == "strategy_properties_ui_spread_unverified" else
                "Sermaye, kontrat büyüklüğü, komisyon sayısı ve slippage tick değeri XLSX'te eşleşti; "
                "komisyon türü ve spread etkisi bu rapordan doğrulanamadı."
                if cost_scope == "strategy_properties_scalars_only" else
                "TradingView maliyet ayarlarının uygulandığı bu sonuçta doğrulanmadı."
            )
            cost_note = self.QtWidgets.QLabel("Maliyet kanıtı: " + detail)
            cost_note.setWordWrap(True)
            layout.addWidget(cost_note)
        tabs = self.QtWidgets.QTabWidget()
        tabs.tabBar().setUsesScrollButtons(True)
        payload = row.get("payload") or {}
        project = self.store.project(self.result_project.currentData())
        parsed = parse_strategy_inputs(project["pine_source"]) if project else []
        definitions = {f"in_{i}": item for i, item in enumerate(parsed)}
        inputs = payload.get("inputs") or {}
        preset_page = self.QtWidgets.QWidget()
        preset_layout = self.QtWidgets.QVBoxLayout(preset_page)
        preset_note = self.QtWidgets.QLabel(
            "Preset, bu testte kullanılan ayar paketidir. Denenen değerler test kaydından; "
            "varsayılanlar şu an kayıtlı Pine kodundan okunur. Farklı ayarlar aşağıda belirtilir; "
            "kaydı olmayan bir değer varsayılmaz.")
        preset_note.setWordWrap(True)
        preset_layout.addWidget(preset_note)
        self.result_preset_table = self.QtWidgets.QTableWidget(len(inputs), 4)
        self.result_preset_table.setHorizontalHeaderLabels(["Ayar", "Varsayılan", "Bu test", "Fark"])
        for column, width in enumerate((90, 65, 65, 65)):
            self.result_preset_table.setColumnWidth(column, width)
        self.result_preset_table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_preset_table.horizontalHeader().setStretchLastSection(True)
        for line, (key, value) in enumerate(inputs.items()):
            item = definitions.get(key)
            values = (item.title if item else "Tanımı bulunamayan ayar", item.default if item else "Bilinmiyor",
                      value, "Farklı" if item and value != item.default else "Aynı" if item else "Karşılaştırılamıyor")
            for column, rendered in enumerate(values):
                cell = self.QtWidgets.QTableWidgetItem(str(rendered))
                cell.setToolTip((item.tooltip or item.title) if item else "Teknik ayar kimliği: " + key)
                self.result_preset_table.setItem(line, column, cell)
        preset_layout.addWidget(self.result_preset_table)
        if not inputs:
            preset_layout.addWidget(self.QtWidgets.QLabel("Bu sonuçta ayar değerleri kaydedilmemiş."))
        preset_layout.addWidget(self._first_use_help("detail", "Bu ayrıntıları nasıl kullanacağım?",
            "Preset sekmesinde denenen ayarları karşılaştırın. Equity ve DD sekmesinde sermaye ve düşüşü, "
            "Saat/Gün/Session sekmelerinde kapanmış işlemlerin dağılımını inceleyin. "
            "Input hassasiyeti yalnız karşılaştırılabilir komşu testleri gösterir. "
            "Grafikleri büyük aç ile paneli büyütün; grafiklerin üzerine gelerek değerleri okuyun. "
            "Yeni değerleri denemek için Tarama ekranına dönüp Farklı değerleri dene seçin; bu panel sonucu değiştirmez."))
        preset_scroll = self.QtWidgets.QScrollArea()
        preset_scroll.setWidgetResizable(True)
        preset_scroll.setFrameShape(self.QtWidgets.QFrame.NoFrame)
        preset_scroll.setWidget(preset_page)
        tabs.addTab(preset_scroll, "Preset ve ayarlar")
        curve_page = self.QtWidgets.QWidget()
        curve_layout = self.QtWidgets.QVBoxLayout(curve_page)
        reported_curve = metrics.get("equity_curve") or []
        closed_curve = metrics.get("closed_trade_equity_curve") or []
        reconstructed = len(reported_curve) < 2 and len(closed_curve) >= 2
        if reconstructed:
            curve_note = self.QtWidgets.QLabel(
                "Yalnız kapanmış işlemlerden hesaplanır. Açık pozisyonu ve gün içi equity düşüşünü göstermez."
            )
            curve_note.setWordWrap(True)
            curve_layout.addWidget(curve_note)
        curve_chart = CurveChart(closed_curve if reconstructed else reported_curve, curve_page,
                                 closed_trade_only=reconstructed)
        curve_layout.addWidget(curve_chart)
        tabs.addTab(curve_page, "Kapanış eğrisi" if reconstructed else "Equity ve DD")

        for title, key in (("Saat", "hourly_pnl"), ("Haftanın günü", "weekday_pnl"),
                           ("Session", "session_pnl")):
            chart_page = self.QtWidgets.QWidget()
            chart_layout = self.QtWidgets.QVBoxLayout(chart_page)
            chart_layout.addWidget(MetricBarsChart(metrics.get(key), chart_page))
            tabs.addTab(chart_page, title)

        tabs.addTab(DailyPnlCalendar(metrics.get("daily_pnl"), panel), "Günlük takvim")

        profile_page = self.QtWidgets.QWidget()
        profile_layout = self.QtWidgets.QVBoxLayout(profile_page)
        sides = metrics.get("long_short") or {}
        side_net = {side: values.get("net_profit") for side, values in sides.items()
                    if isinstance(values, dict)}
        profile_layout.addWidget(MetricBarsChart(side_net, profile_page))
        profile_layout.addWidget(self.QtWidgets.QLabel("İşlem süreleri (adet)", objectName="subtitle"))
        profile_layout.addWidget(MetricBarsChart(metrics.get("duration_histogram"), profile_page))
        profile_layout.addWidget(self.QtWidgets.QLabel("Ardışık kazanç/kayıp serileri (adet)", objectName="subtitle"))
        profile_layout.addWidget(MetricBarsChart(metrics.get("streak_distribution"), profile_page))
        duration = metrics.get("duration_minutes") or {}
        profile_layout.addWidget(self.QtWidgets.QLabel(
            "İşlem süresi (dk) · ortalama: {average} · medyan: {median} · en uzun: {maximum}".format(
                average=duration.get("average", "—"), median=duration.get("median", "—"),
                maximum=duration.get("maximum", "—"))
        ))
        profile_layout.addWidget(self.QtWidgets.QLabel(
            f"En uzun kazanç serisi: {metrics.get('max_win_streak', '—')} · "
            f"En uzun kayıp serisi: {metrics.get('max_loss_streak', '—')}"
        ))
        profile_layout.addStretch()
        profile_scroll = self.QtWidgets.QScrollArea()
        profile_scroll.setWidgetResizable(True)
        profile_scroll.setWidget(profile_page)
        tabs.addTab(profile_scroll, "İşlem profili")

        sensitivity_page = self.QtWidgets.QWidget()
        sensitivity_layout = self.QtWidgets.QVBoxLayout(sensitivity_page)
        sensitivity = build_sensitivity(self.store, row, self.store.results(self.result_project.currentData()))
        sensitivity_note = self.QtWidgets.QLabel(sensitivity["warning"])
        sensitivity_note.setWordWrap(True); sensitivity_layout.addWidget(sensitivity_note)
        neighbors = sensitivity["neighbors"]
        sensitivity_table = self.QtWidgets.QTableWidget(len(neighbors), 8)
        sensitivity_table.setHorizontalHeaderLabels(
            ["Ayar", "Bu değer", "Komşu değer", "Komşu işlem", "Komşu PF", "Komşu DD %", "Sınıf", "TV uyarısı"]
        )
        sensitivity_table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        sensitivity_table.horizontalHeader().setStretchLastSection(True)
        for index, neighbor in enumerate(neighbors):
            other = neighbor["row"]
            frozen_definitions = {f"in_{position}": spec for position, spec in enumerate(parse_strategy_inputs(other["source_snapshot"]))}
            definition = frozen_definitions.get(neighbor["input_id"])
            values = (definition.title if definition else "Tanımı bulunamayan ayar", neighbor["base_value"], neighbor["other_value"],
                      other["metrics"].get("trades"), other["metrics"].get("profit_factor"),
                      other["metrics"].get("max_drawdown_pct"), other["classification"], other["warning_label"])
            for column, value in enumerate(values):
                sensitivity_table.setItem(index, column, self.QtWidgets.QTableWidgetItem(str(value)))
        sensitivity_layout.addWidget(sensitivity_table)
        exclusions = self.QtWidgets.QPlainTextEdit()
        exclusions.setReadOnly(True); exclusions.setMaximumHeight(120)
        exclusions.setPlainText("\n".join(f"Kayıt {entry['task_id']}: " + " ".join(entry["reasons"])
                                          for entry in sensitivity["excluded"]) or "Dışlanan kayıt yok.")
        sensitivity_layout.addWidget(exclusions)
        from .help_system import HelpSpec, TourSpec
        sensitivity_guide = self.QtWidgets.QPushButton("? Hassasiyet rehberi")
        sensitivity_layout.addWidget(sensitivity_guide)
        for key, target, title, text in (
            ("note", sensitivity_note, "Kanıt sınırı", sensitivity["warning"]),
            ("table", sensitivity_table, "Denenen komşular", "Aynı kanıtlı koşullarda yalnız tek ayarı farklı testler gösterilir; denenmeyen değerler uydurulmaz."),
            ("excluded", exclusions, "Dışlanan kayıtlar", "Eksik veya farklı kaynak, dönem, para birimi, sermaye ve maliyet kanıtı dışlama nedeni olarak gösterilir."),
            ("guide", sensitivity_guide, "Rehber", "Salt okunur hassasiyet rehberini açar; test veya kayıt oluşturmaz."),
        ):
            self.help_registry.register(HelpSpec("sensitivity." + key, 1, title, text, text, target))
        self.help_registry.register_columns("sensitivity.columns", sensitivity_table, tuple(
            (sensitivity_table.horizontalHeaderItem(column).text(), "Kanıtlı komşu testin saklanan değeri.",
             "Değer karşılaştırması gelecekte kâr veya nedensellik kanıtı değildir.") for column in range(8)))
        self.help_registry.register_tour(TourSpec("sensitivity", 1, (
            (sensitivity_note, "Koşulları kontrol et", "Karşılaştırma yalnız kanıtlı aynı bağlamda yapılır.", None),
            (sensitivity_table, "Gerçek testleri incele", "Her satır gerçekten denenmiş tek-ayar komşusudur. Bilinmeyen uyarı yok kabul edilmez.", None),
            (exclusions, "Eksik kanıtı gör", "Dışlanan testlerin nedenlerini kontrol et. Rehber yeni test üretmez.", None),
        )))
        sensitivity_guide.clicked.connect(lambda: self.help_registry.start_tour("sensitivity"))
        self.help_registry.bind_first_use(sensitivity_page, "sensitivity")
        if not neighbors:
            sensitivity_layout.addWidget(self.QtWidgets.QLabel(
                "Karşılaştırılabilir komşu sonuç yok. Tek bir iyi sonuç dayanıklılık kanıtı değildir."
            ))
        tabs.addTab(sensitivity_page, "Input hassasiyeti")

        detail_page = self.QtWidgets.QWidget()
        detail_layout = self.QtWidgets.QVBoxLayout(detail_page)
        splitter = self.QtWidgets.QSplitter()
        detail = self.QtWidgets.QTableWidget(0, 2)
        detail.setHorizontalHeaderLabels(["Ölçüm", "Değer"]); detail.horizontalHeader().setStretchLastSection(True)
        scalar = [(key, value) for key, value in metrics.items()
                  if key not in {"equity_curve", "daily_pnl", "hourly_pnl", "weekday_pnl", "session_pnl"}]
        detail.setRowCount(len(scalar))
        for line, (key, value) in enumerate(sorted(scalar)):
            detail.setItem(line, 0, self.QtWidgets.QTableWidgetItem(key))
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            detail.setItem(line, 1, self.QtWidgets.QTableWidgetItem(rendered))
        calendar = self.QtWidgets.QTableWidget(0, 2); calendar.setHorizontalHeaderLabels(["Gün", "P/L"])
        daily = metrics.get("daily_pnl", {}); calendar.setRowCount(len(daily))
        for line, (day, pnl) in enumerate(sorted(daily.items())):
            calendar.setItem(line, 0, self.QtWidgets.QTableWidgetItem(day))
            cell = self.QtWidgets.QTableWidgetItem(f"{pnl:,.2f}")
            cell.setForeground(QtGui.QColor("#477a62" if pnl >= 0 else "#b54c42")); calendar.setItem(line, 1, cell)
        calendar.setSortingEnabled(True)
        splitter.addWidget(detail); splitter.addWidget(calendar); detail_layout.addWidget(splitter, 1)
        tabs.addTab(detail_page, "Günler ve ölçümler")
        from .result_history_panel import ResultHistoryPanel
        history = ResultHistoryPanel(self.store, task_id)
        history.register_help(self.help_registry)
        tabs.addTab(history, "Geçmiş ve değerlendirme")
        layout.addWidget(tabs, 1)
        self.result_detail_dock.setWindowTitle(f"Preset ayrıntısı · {row['task_key'][:12]}")
        self.result_detail_dock.setWidget(panel)
        self._open_result_task_id = task_id
        self.result_detail_dock.show()
        if not self.result_detail_dock.isFloating():
            detail_width = 360 if self.window.width() < 1500 else 460
            self.window.resizeDocks([self.result_detail_dock], [detail_width], QtCore.Qt.Horizontal)

    def toggle_result_detail_size(self):
        expanded = not self.result_detail_dock.isFloating()
        self.result_detail_dock.setFloating(expanded)
        if expanded:
            self.result_detail_dock.resize(960, 680)
        else:
            detail_width = 360 if self.window.width() < 1500 else 460
            self.window.resizeDocks([self.result_detail_dock], [detail_width], QtCore.Qt.Horizontal)
        self.result_detail_expand.setText("Yan panele dön" if expanded else "Grafikleri büyük aç")

    def validate_selected_results(self):
        rows = self.selected_result_rows()
        if not rows:
            self.QtWidgets.QMessageBox.information(self.window, "Aşamalı doğrulama", "En az bir sonuç seçin.")
            return
        symbol, accepted = self._ask_text_with_help("provider_symbol")
        if not accepted:
            return
        inserted = 0
        project = self.store.project(self.result_project.currentData())
        definitions = {f"in_{index}": spec for index, spec in enumerate(
            parse_strategy_inputs(project["pine_source"]))}
        for row in rows:
            if row["verified"] and row["classification"] != "elenmiş":
                try:
                    inserted += enqueue_followups(self.store, row["task_id"], row["payload"], symbol,
                                                  input_specs=definitions)
                except ValueError as error:
                    self.QtWidgets.QMessageBox.warning(self.window, "Ayar doğrulanamadı", str(error))
                    return
        self.refresh_dashboard()
        self.dashboard_status.setText(f"{inserted} doğrulama görevi kuyruğa eklendi.")

    def export_current_results(self):
        project_id = self.result_project.currentData()
        if project_id is None:
            return
        Q = self.QtWidgets
        dialog = Q.QDialog(self.window)
        dialog.setWindowTitle("Sonuçları dışa aktar")
        layout = Q.QFormLayout(dialog)
        kind = Q.QComboBox()
        kind.addItems(["Tüm görevler (başarılı ve başarısız)", "Yalnız başarılı presetler"])
        scope = Q.QComboBox()
        scope.addItems(["Projedeki tüm uygun kayıtlar", "Ekranda görünen sonuçlar (teknik hatalar hariç)"])
        scope.addItem("Seçili sonuç satırları")
        format_choice = Q.QComboBox()
        format_choice.addItems(["CSV", "Excel (.xlsx)", "PDF"])
        note = Q.QLabel()
        note.setWordWrap(True)
        count_note = Q.QLabel()
        count_note.setObjectName("export_count_preview")
        count_note.setWordWrap(True)

        def refresh_options(*_args):
            pdf = format_choice.currentText() == "PDF"
            if pdf:
                kind.setCurrentIndex(1)
            kind.setEnabled(not pdf)
            successful = kind.currentIndex() == 1 or pdf
            limited = scope.currentIndex() in (1, 2)
            if limited:
                candidates = self.selected_result_rows() if scope.currentIndex() == 2 else self._result_rows
                count = sum(1 for row in candidates if
                            not successful or
                            (row["classification"] in SUCCESS_CLASSES and row["verified"]))
            elif successful:
                count = sum(1 for row in self.store.results(project_id, SUCCESS_CLASSES)
                            if row["verified"])
            else:
                count = sum(self.store.counts(project_id).values())
            count_note.setText(
                f"Şu anda seçilen kapsamda {count:,} kayıt var. "
                "Çalışan tarama sırasında sayı kaydetme anına kadar değişebilir."
            )
            note.setText(
                "PDF yalnız başarılı presetleri içerir; başarısız ve teknik hata kayıtları CSV/Excel ile alınır."
                if pdf else "Yalnız seçili sonuç satırları kaydedilecek; seçilmeyen ve teknik hata görevleri bu kapsamda yoktur."
                if scope.currentIndex() == 2 else "Ekran kapsamı yalnız görünen sonuç satırlarını içerir. Teknik hatalar dahil tüm görevler için proje kapsamını seçin."
            )

        format_choice.currentIndexChanged.connect(refresh_options)
        kind.currentIndexChanged.connect(refresh_options)
        scope.currentIndexChanged.connect(refresh_options)
        layout.addRow("Kayıtlar", kind)
        layout.addRow("Kapsam", scope)
        layout.addRow("Biçim", format_choice)
        layout.addRow("Kayıt sayısı", count_note)
        layout.addRow(note)
        buttons = Q.QDialogButtonBox(Q.QDialogButtonBox.Ok | Q.QDialogButtonBox.Cancel)
        buttons.button(Q.QDialogButtonBox.Ok).setText("Dosyayı kaydet")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        from .help_catalog import register_export_help
        help_scope = self.help_registry.child_scope(dialog)
        dialog.help_registry = help_scope
        register_export_help(help_scope, dict(kind=kind, scope=scope, format=format_choice,
                             note=note, count=count_note,
                             save=buttons.button(Q.QDialogButtonBox.Ok),
                             cancel=buttons.button(Q.QDialogButtonBox.Cancel)))
        guide = Q.QPushButton("Dışa aktarma rehberi (?)")
        guide.clicked.connect(lambda: help_scope.start_tour("export"))
        layout.addRow(guide)
        from .help_system import HelpSpec
        help_scope.register(HelpSpec("export.guide", 1, "Dışa aktarma rehberi",
                                     "Dosya türü ve kayıt kapsamı rehberini yeniden açar.",
                                     "Rehber dosya oluşturmaz veya kayıt kapsamını değiştirmez.", guide))
        QtCore.QTimer.singleShot(0, help_scope, lambda: help_scope.start_tour("export", automatic=True))
        refresh_options()
        try:
            accepted = dialog.exec() == Q.QDialog.Accepted
            selected_kind = kind.currentIndex()
            selected_scope = scope.currentIndex()
            selected_format = format_choice.currentText()
        finally:
            help_scope.finish_scope()
            dialog.deleteLater()
        if not accepted:
            return

        successful = selected_kind == 1 or selected_format == "PDF"
        visible_ids = ({row["task_id"] for row in self.selected_result_rows()} if selected_scope == 2 else
                       {row["task_id"] for row in self._result_rows} if selected_scope == 1 else None)
        if selected_format == "PDF":
            rows = self.store.results(project_id)
            if visible_ids is not None:
                rows = [row for row in rows if row["task_id"] in visible_ids]
            rows = [row for row in rows if row["classification"] in SUCCESS_CLASSES and row["verified"]]
            if not rows:
                Q.QMessageBox.information(self.window, "Dışa aktar", "Bu kapsamda başarılı preset yok.")
                return
            project = self.store.project(project_id)
            project["settings"] = self.store.settings(project_id) or {}
            destination, _ = Q.QFileDialog.getSaveFileName(
                self.window, "Başarılı presetleri PDF olarak kaydet",
                f"{project['name']}-basarili.pdf", "PDF (*.pdf)")
            if destination:
                count = export_project_pdf(project, rows, destination)
                Q.QMessageBox.information(self.window, "Dışa aktar", f"{count} başarılı preset kaydedildi.")
            return

        excel = selected_format.startswith("Excel")
        suffix = "xlsx" if excel else "csv"
        destination, selected_filter = Q.QFileDialog.getSaveFileName(
            self.window, "Tarama kayıtlarını kaydet", f"tv-scan-results.{suffix}",
            "Excel (*.xlsx)" if excel else CSV_FILTERS.replace("Excel (*.xlsx);;", ""))
        if destination:
            count = export_project_task_scope(
                self.store, project_id, destination, successful=successful,
                visible_ids=visible_ids, excel=excel, excel_tr="Türkçe Excel" in selected_filter,
            )
            if not count:
                Q.QMessageBox.information(self.window, "Dışa aktar", "Bu kapsamda kaydedilecek görev yok.")
                return
            message = f"{count} görev kaydedildi."
            if not excel and "Türkçe Excel" in selected_filter:
                message += " Excel sihirbazında UTF-8 ve noktalı virgül ayracını seçin; doğrudan açmak için XLSX kullanın."
            Q.QMessageBox.information(self.window, "Dışa aktar", message)

    def export_current_report(self):
        project_id = self.result_project.currentData()
        if project_id is None:
            return
        project = self.store.project(project_id)
        project["settings"] = self.store.settings(project_id) or {}
        path, _ = self.QtWidgets.QFileDialog.getSaveFileName(
            self.window, "PDF raporu", f"{project['name']}-tv-scan-report.pdf", "PDF (*.pdf)"
        )
        if path:
            rows = [row for row in self.store.results(project_id)
                    if row["classification"] in SUCCESS_CLASSES and row["verified"]]
            export_project_pdf(project, rows, path)

    def refresh_dashboard(self):
        Q = self.QtWidgets
        projects = self.store.projects()
        counts = self.store.total_counts()
        stats = self.store.dashboard_stats(run_id=getattr(self, "_active_run_id", None))
        has_tasks = any(int(project["task_count"] or 0) for project in projects)
        self.dashboard_metrics.setVisible(has_tasks)
        self.dashboard_operational.setVisible(has_tasks)
        self.dashboard_setup.setVisible(not has_tasks)
        if projects and not has_tasks:
            self.dashboard_setup_title.setText("Taramayı planla")
            self.dashboard_setup_text.setText(
                "Proje hazır. Hangi inputları tarayacağını seç, toplam görev sayısını gör ve çalışma sekmelerini hazırlamadan önce planı kontrol et."
            )
            self.dashboard_setup_action.setText("Tarama ayarlarını aç")
            self.dashboard_setup_page = 2
        elif not projects:
            self.dashboard_setup_title.setText("İlk taramanı kur")
            self.dashboard_setup_text.setText(
                "Pine stratejini ekle; ayarları ve görev sayısını taramadan önce birlikte göreceğiz."
            )
            self.dashboard_setup_action.setText("Yeni proje oluştur")
            self.dashboard_setup_page = 1
        self.metric_labels["projects"].setText(str(len(projects)))
        for key in ("pending", "running", "done", "failed", "manual_review"):
            self.metric_labels[key].setText(str(counts.get(key, 0)))
        rate = stats["tests_per_hour"]
        self.throughput_label.setText(f"Son 5 dk: {rate:,.1f} doğrulanmış test/saat" if rate else "Hız: yeterli doğrulanmış veri yok")
        eta = stats["eta_seconds"]
        self.eta_label.setText(f"ETA: {self._format_duration(eta)}" if eta is not None else "ETA: —")
        candidates = stats["candidates"]
        self.candidate_label.setText(
            f"Aday: {candidates.get('dayanıklı', 0) + candidates.get('hassas', 0)}"
        )
        try:
            snapshot = system_snapshot()
            used = snapshot.total_memory_bytes - snapshot.available_memory_bytes
            self.resource_label.setText(
                f"CPU %{snapshot.cpu_percent:.0f} · RAM {used / 2**30:.1f}/{snapshot.total_memory_bytes / 2**30:.1f} GB"
            )
        except RuntimeError:
            self.resource_label.setText("CPU/RAM ölçülemedi")
        previous = self._last_dashboard_counts
        current_candidates = candidates.get("dayanıklı", 0) + candidates.get("hassas", 0)
        if previous is not None:
            previous_candidates = previous.get("candidates", 0)
            if current_candidates > previous_candidates:
                self.notify("Yeni preset adayı", f"{current_candidates - previous_candidates} yeni aday doğrulandı.")
            previous_active = previous.get("pending", 0) + previous.get("running", 0)
            current_active = counts.get("pending", 0) + counts.get("running", 0)
            if previous_active > 0 and current_active == 0:
                self.notify("Tarama tamamlandı", f"Toplam {counts.get('done', 0)} görev tamamlandı.")
        self._last_dashboard_counts = {**counts, "candidates": current_candidates}
        self.project_table.setRowCount(len(projects))
        self.dashboard_empty.setVisible(not projects)
        self.project_table.setVisible(bool(projects))
        self.dashboard_projects_heading.setVisible(bool(projects))
        self.dashboard_empty.hide()
        self.dashboard_actions.setVisible(bool(projects))
        for widget in self.dashboard_project_actions:
            widget.setEnabled(bool(projects))
        for row, project in enumerate(projects):
            values = (project["id"], project["name"],
                      PROJECT_STATUS_LABELS.get(project["status"], project["status"]), project["priority"],
                      project["task_count"])
            for column, value in enumerate(values):
                self.project_table.setItem(row, column, Q.QTableWidgetItem(str(value)))
            total = project["task_count"]
            finished = project["done_count"] + project["issue_count"] + project["cancelled_count"]
            progress = ProjectProgressBar()
            progress.setRange(0, max(total, 1))
            progress.setValue(finished)
            progress.setFormat(f"%p% · {finished:,}/{total:,}")
            progress.setToolTip(
                f"Tamamlanan {project['done_count']:,} · Hata/inceleme {project['issue_count']:,} · "
                f"İptal {project['cancelled_count']:,} · Bekleyen {project['pending_count']:,} · "
                f"Çalışan {project['running_count']:,}. Görevleri görmek için tıklayın."
            )
            progress.setCursor(QtCore.Qt.PointingHandCursor)
            progress.clicked.connect(lambda pid=project["id"]: self.open_dashboard_tasks(None, pid))
            self.project_table.setCellWidget(row, 5, progress)
        events = self.store.events(8)
        self.dashboard_events_empty.setVisible(not events)
        self.dashboard_events_heading.setVisible(bool(events))
        self.dashboard_events.setVisible(bool(events))
        self.dashboard_events_empty.hide()
        self.dashboard_events.setRowCount(len(events))
        for row_index, event in enumerate(events):
            for column, value in enumerate((event["level"], event["worker_id"],
                                            event["task_id"], event["message"])):
                self.dashboard_events.setItem(
                    row_index, column, Q.QTableWidgetItem(str(value if value is not None else "—"))
                )

    @staticmethod
    def _format_duration(seconds):
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours} sa {minutes} dk" if hours else f"{minutes} dk"

    def _selected_project_id(self):
        row = self.project_table.currentRow()
        if row < 0:
            raise ValueError("Önce proje tablosundan bir satır seçin.")
        return int(self.project_table.item(row, 0).text())

    def update_selected_project(self):
        try:
            self.store.update_project(self._selected_project_id(), priority=self.project_priority.value(),
                                      status=self.project_state.currentData())
            self.dashboard_status.setText("Proje güncellendi."); self.refresh_dashboard()
        except ValueError as exc:
            self.dashboard_status.setText(str(exc))

    def cancel_selected_project(self):
        try:
            count = self.store.cancel_pending(self._selected_project_id())
            self.dashboard_status.setText(f"{count} bekleyen görev iptal edildi."); self.refresh_dashboard()
        except ValueError as exc:
            self.dashboard_status.setText(str(exc))

    def retry_selected_project(self):
        try:
            count = self.store.retry_tasks(self._selected_project_id())
            self.dashboard_status.setText(f"{count} görev yeniden sıraya alındı."); self.refresh_dashboard()
        except ValueError as exc:
            self.dashboard_status.setText(str(exc))

    def retry_result_project(self):
        project_id = self.result_project.currentData()
        if project_id is None:
            return
        count = self.store.retry_tasks(project_id)
        self.refresh_results(); self.refresh_dashboard()
        self.dashboard_status.setText(f"{count} görev yeniden sıraya alındı.")

    def _run_backup_job(self, operation, **options):
        from .backup_jobs import BackupJob
        from .backup_dialog import BackupProgressDialog
        # A modal event loop remains responsive; the file IO lives in QThread.
        if getattr(self, "_backup_dialog", None) is not None:
            return {"status": "error", "message": "Başka bir yedek işlemi sürüyor."}
        dialog = BackupProgressDialog(BackupJob(operation, **options), self.window, self.help_registry)
        self._backup_dialog = dialog
        dialog.finished.connect(self._plan_count_drained)
        try:
            dialog.start()
            dialog.exec()
            return dialog.outcome
        finally:
            self._backup_dialog = None
            dialog.deleteLater()

    def create_portable_backup(self, *, attachments=()):
        path, _ = self.QtWidgets.QFileDialog.getSaveFileName(
            self.window, "TV Scan Studio yedeği", "tv-scan-studio-backup.tvscan.zip", "TV Scan yedeği (*.tvscan.zip)"
        )
        if not path:
            return
        try:
            result = self._run_backup_job("create", store=self.store, destination=path, attachments=attachments)
            if result["status"] == "cancelled":
                self.dashboard_status.setText("Yedekleme iptal edildi; önceki yedek ve uygulama verileri korundu.")
                return
            if result["status"] == "error":
                raise RuntimeError(result["message"])
            manifest = result["manifest"]
            self.dashboard_status.setText(f"Yedek doğrulandı · {manifest['project_count']} proje · {len(manifest.get('attachments', []))} ek dosya. Yedek özel kod ve veriler içerebilir; güvenli sakla.")
        except Exception as exc:
            self.dashboard_status.setText(f"Yedekleme başarısız: {exc}")

    def restore_portable_backup(self):
        source, _ = self.QtWidgets.QFileDialog.getOpenFileName(
            self.window, "Geri yüklenecek yedeği seçin", "", "TV Scan yedeği (*.tvscan.zip *.zip)")
        if not source:
            return
        destination, _ = self.QtWidgets.QFileDialog.getSaveFileName(
            self.window, "Yeni veritabanı dosyası seçin (mevcut dosyanın üzerine yazılmaz)",
            "tv-scan-studio-restored.db", "SQLite veritabanı (*.db)")
        if not destination:
            return
        try:
            result = self._run_backup_job("restore", source=source, destination=destination)
            if result["status"] == "cancelled":
                self.dashboard_status.setText("Geri yükleme iptal edildi; yarım hedef dosyaları temizlendi, aktif veritabanı değiştirilmedi.")
                return
            if result["status"] == "error":
                raise RuntimeError(result["message"])
            manifest = result["manifest"]
            self.dashboard_status.setText(
                f"Yedek yeni dosyaya açıldı · {manifest['project_count']} proje · {destination}. "
                "Mevcut uygulama veritabanı değiştirilmedi; yeni dosyaya otomatik geçilmedi.")
            restored_files = manifest.get("restored_attachments", [])
            if restored_files:
                folder = Path(restored_files[0]).parent.parent
                self.dashboard_status.setText(self.dashboard_status.text() +
                    f" {len(restored_files)} ek dosya ayrı klasöre çıkarıldı: {folder}.")
                if manifest.get("restored_archives"):
                    self.dashboard_status.setText(self.dashboard_status.text() +
                        " Seçilen kayıtlı arşivlerin doğrulanmış kopyaları yeni veri alanında açılabilir; geçmiş kayıtlar yeni TradingView sonuçları veya görevler sayılmadı.")
                else:
                    self.dashboard_status.setText(self.dashboard_status.text() + " Araştırmalar otomatik içe aktarılmadı.")
        except Exception as exc:
            self.dashboard_status.setText(f"Geri yükleme başarısız: {exc}")

    def measure_resources(self):
        try:
            snapshot = system_snapshot(); recommendation = recommend_workers(snapshot)
            available_gb = snapshot.available_memory_bytes / (1024 ** 3)
            self.resource_status.setText(
                f"CPU %{snapshot.cpu_percent:.0f} · boş RAM {available_gb:.1f} GB · öneri {recommendation.recommended} worker"
            )
            self.resource_status.setText(self.resource_status.text() +
                " · Bu kaynak önerisidir; gerçek test hızı Sonuçlar ekranında ölçülür.")
            if snapshot.cpu_percent >= 90 or available_gb < 2:
                self.notify("Kaynak sınırına yaklaşıldı", self.resource_status.text())
        except RuntimeError as exc:
            self.resource_status.setText(str(exc))

    def notify(self, title, message):
        if self.notifications_enabled.isChecked() and self.tray.isVisible():
            self.tray.showMessage(title, message, self.QtWidgets.QSystemTrayIcon.Information, 6000)


def ui_smoke_test() -> int:
    """Build every packaged page with an isolated database and no TradingView worker."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    application = QtWidgets.QApplication.instance()
    created_application = application is None
    if application is None:
        application = QtWidgets.QApplication(["TV Scan Studio UI smoke"])
    application.setStyleSheet(STYLE)
    with TemporaryDirectory(prefix="tv-scan-studio-ui-smoke-") as directory:
        studio = StudioWindow(Store(Path(directory) / "studio.db"))
        try:
            studio.window.show()
            for index in range(studio.pages.count()):
                studio._show_page(index)
                application.processEvents(QtCore.QEventLoop.AllEvents, 50)
                if studio.pages.currentIndex() != index:
                    return 2
            if studio.pages.count() != 7:
                return 2
            from .historical_dialog import HistoricalDialog
            historical = HistoricalDialog(studio.store, studio.window)
            historical.show()
            application.processEvents(QtCore.QEventLoop.AllEvents, 50)
            if not historical.table.isVisible() or historical.export_button.isEnabled():
                return 2
            historical.close()
        finally:
            studio.worker_timer.stop()
            studio.tray.hide()
            studio.window.close()
            application.processEvents(QtCore.QEventLoop.AllEvents, 50)
    if created_application:
        application.quit()
    return 0


def main() -> int:
    if "--helper-self-test" in sys.argv:
        from .processes import run_hidden
        try:
            result = run_hidden(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                 "[Console]::Write('helper-ok')"],
                                capture_output=True, text=True, timeout=15, check=False)
            return 0 if result.returncode == 0 and result.stdout == "helper-ok" else 2
        except (OSError, __import__('subprocess').SubprocessError):
            return 2
    if "--ui-smoke-test" in sys.argv:
        return ui_smoke_test()
    if "--self-test" in sys.argv:
        from zoneinfo import ZoneInfo

        catalog = load_catalog()
        if ZoneInfo("America/New_York").key != "America/New_York":
            return 2
        if catalog.get("available", True) and len(catalog["records"]) != 7:
            return 2
        historical_count = sum(1 for _ in iter_historical_records())
        if historical_count not in (0, 33_075):
            return 2
        # Keep diagnostics independent of, and harmless to, the user's live database.
        with TemporaryDirectory(prefix="tv-scan-studio-self-test-") as directory:
            store = Store(Path(directory) / "studio.db")
            destination = Path(directory) / "portable-self-test.pdf"
            export_project_pdf(
                {"name": "Taşınabilir Türkçe Test", "pine_hash": "self-test", "settings": {}},
                [], destination,
            )
            if not store.path.is_file() or not destination.read_bytes().startswith(b"%PDF"):
                return 2
        return 0
    application = QtWidgets.QApplication(sys.argv)
    application.setWindowIcon(QtGui.QIcon(str(Path(__file__).parent / "assets" / "app-icon.ico")))
    application.setStyleSheet(STYLE)
    with desktop_instance() as acquired:
        if not acquired:
            QtWidgets.QMessageBox.information(
                None, "TV Scan Studio zaten açık",
                "TV Scan Studio zaten çalışıyor. Mevcut taramaları korumak için ikinci pencere açılmadı.",
            )
            return 0
        studio = StudioWindow(Store(data_path()))
        application.aboutToQuit.connect(studio.stop_workers)
        studio.window.show()
        return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
