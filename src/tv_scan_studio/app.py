"""TV Scan Studio desktop application."""

from __future__ import annotations

import os
import sys
import json
import itertools
import math
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6 import QtCore, QtGui, QtWidgets

from .pine import parse_strategy_inputs, strategy_title
from .planner import ScanPlan, enqueue_plan
from .export import (export_results_csv, export_task_csv, export_task_xlsx,
                     export_project_task_scope)
from .backup import create_backup, verify_backup
from .resources import project_worker_throughput, recommend_workers, system_snapshot
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
from .sensitivity import one_input_neighbors, possible_no_effect_inputs
from .session_variants import SESSION_IDS, observed_session_variants
from .validation import enqueue_followups
from .ui_controls import DecisionChoice, DisclosureButton, SwitchToggle


STYLE = """
QWidget { background:#f8f5ef; color:#28332e; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#f8f5ef; }
QLabel { background:transparent; }
#rail { background:#ebe7dc; border-right:1px solid #d8d0c2; }
#brand { color:#28332e; font-family:Georgia; font-size:21px; font-weight:700; padding:18px 14px; }
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
#title { font-family:Georgia; font-size:27px; font-weight:700; color:#28332e; }
#subtitle { color:#68756d; font-size:14px; }
#sectionTitle { color:#28332e; font-family:Georgia; font-size:18px; font-weight:600; padding:6px 0; }
#metric { background:#fffdf9; border:1px solid #e7e3d9; border-radius:8px; padding:16px; }
#metricLabel { color:#68756d; font-size:12px; }
#metricValue { border:0; background:transparent; color:#28332e; font-size:24px; font-weight:700; text-align:left; padding:0; }
#metricValue:hover { color:#8b6330; }
#status { color:#6b4c22; padding:8px 0; }
#filterChip { background:#ece0c8; color:#3a322a; border:1px solid #ddc9a3; border-radius:6px; padding:5px 9px; }
QProgressBar { background:#ebe7dc; border:1px solid #d8d0c2; border-radius:5px; color:#28332e; text-align:center; min-height:21px; }
QProgressBar::chunk { background:#b9863f; border-radius:4px; }
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


class StudioWindow:
    def __init__(self, store: Store):
        self.QtWidgets = QtWidgets
        self.store = store
        self.store.recover_interrupted()
        self.supervisor = None
        self.driver = None
        self.window = QtWidgets.QMainWindow()
        self.window.setWindowTitle("TV Scan Studio")
        self.window.resize(1240, 780)
        self._last_dashboard_counts = None
        self._notified_worker_errors = set()
        self._notified_worker_restarts = set()
        self._safe_worker_targets = set()  # Only explicitly claimed independent layouts in this session.
        self._safe_worker_layouts = {}  # Explicitly claimed, unique saved layouts: target -> chart ID.
        self.tray = QtWidgets.QSystemTrayIcon(
            self.window.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon), self.window
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

    def _rail(self):
        Q = self.QtWidgets
        rail = Q.QFrame(objectName="rail")
        rail.setFixedWidth(224)
        box = Q.QVBoxLayout(rail)
        box.setContentsMargins(0, 0, 0, 16)
        box.addWidget(Q.QLabel("TV Scan Studio", objectName="brand"))
        box.addWidget(Q.QLabel("Yerel strateji laboratuvarı", objectName="tagline"))
        group = Q.QButtonGroup(rail)
        group.setExclusive(True)
        self.nav_group = group
        for index, label in enumerate(("Tarama masası", "Yeni proje", "Tarama ayarları", "Worker dağıtımı", "Sonuçlar ve hatalar", "Araştırma presetleri", "Ayarlar")):
            button = Q.QPushButton(label)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked=False, i=index: self._show_page(i))
            group.addButton(button, index)
            box.addWidget(button)
        box.addStretch()
        privacy = Q.QLabel("Veriler yalnızca bu bilgisayarda tutulur", objectName="tagline")
        privacy.setWordWrap(True)
        box.addWidget(privacy)
        return rail

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
        backup = Q.QPushButton("Yedek oluştur"); backup.clicked.connect(self.create_portable_backup)
        operational.addWidget(backup)
        box.addWidget(self.dashboard_operational)
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
        layout.addWidget(self.QtWidgets.QLabel(
            f"Toplam {total:,} görev · son {len(rows)} kayıt gösteriliyor. Tüm kayıtlar CSV/Excel olarak dışa aktarılabilir."
        ))
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
        form.addRow("Tek CDP portu", port); form.addRow("Yerel veritabanı", database)
        form.addRow("Bildirimler", self.notifications_enabled)
        box.addLayout(form)
        advanced_toggle = DisclosureButton("Gelişmiş bağlantı ayarları")
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
        box.addWidget(save); self.settings_status = Q.QLabel("Telemetri ve bulut bağlantısı kapalıdır.", objectName="status")
        box.addWidget(self.settings_status); box.addStretch()
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
        box.addWidget(self._page_header("Tarama ayarları", "Kombinasyonları hesaplayın ve tekrar üretilebilir görevler oluşturun."))
        self.scan_flow_status = Q.QLabel("Proje: eksik · Strateji: eksik · Plan: eksik · Sekmeler: onay gerekli", objectName="status")
        self.scan_flow_status.setWordWrap(True)
        box.addWidget(self.scan_flow_status)
        context_form = Q.QFormLayout()
        scope_form = Q.QFormLayout()
        self.plan_project = Q.QComboBox()
        self.plan_project.setMaximumWidth(360)
        self.plan_project.setMaxVisibleItems(8)
        self.plan_project.currentIndexChanged.connect(self.load_plan_inputs)
        self.plan_project.activated.connect(lambda _index: self._remember_project(self.plan_project.currentData()))
        find_project = Q.QPushButton("Proje ara")
        find_project.clicked.connect(self.open_project_picker)
        self.study_id = Q.QLineEdit()  # Internal binding; users select a named strategy below.
        self.strategy_picker = Q.QComboBox(); self.strategy_picker.setMaximumWidth(560)
        self.strategy_picker.addItem("Önce projeyi seçin", None)
        self.strategy_picker.currentIndexChanged.connect(self.select_plan_strategy)
        find_strategy = Q.QPushButton("Açık stratejiyi bul")
        find_strategy.clicked.connect(self.discover_plan_strategies)
        self.symbols = Q.QLineEdit(); self.symbols.setPlaceholderText("OANDA:EURUSD, OANDA:GBPUSD")
        self.symbol_profile = Q.QComboBox(); self.symbol_profile.addItem("Özel")
        self.symbol_profile.addItems(FTMO_SYMBOL_PROFILES.keys())
        self.symbol_profile.currentTextChanged.connect(self.apply_symbol_profile)
        self.timeframes = Q.QLineEdit(); self.timeframes.setPlaceholderText("15, 1H")
        self.analysis_timezone = Q.QComboBox()
        self.analysis_timezone.addItems(["UTC", "America/New_York", "Europe/Istanbul"])
        self.analysis_timezone.setCurrentText("America/New_York")
        self.date_from = Q.QLineEdit(); self.date_from.setPlaceholderText("2025-01-01")
        self.date_to = Q.QLineEdit(); self.date_to.setPlaceholderText("2025-12-31")
        for date_field in (self.date_from, self.date_to):
            date_field.setToolTip(
                "Özel tarih seçimi plan önizlemesi içindir; TradingView'de otomatik uygulama henüz açık değil."
            )
        project_row = Q.QHBoxLayout()
        project_row.addWidget(self.plan_project)
        project_row.addWidget(find_project)
        project_row.addStretch()
        context_form.addRow("Proje", project_row)
        strategy_row = Q.QHBoxLayout(); strategy_row.addWidget(self.strategy_picker); strategy_row.addWidget(find_strategy); strategy_row.addStretch()
        context_form.addRow("TradingView stratejisi", strategy_row)
        symbol_row = Q.QHBoxLayout(); symbol_row.addWidget(self.symbol_profile); symbol_row.addWidget(self.symbols, 1)
        scope_form.addRow("Sembol profili", symbol_row); scope_form.addRow("Timeframe'ler", self.timeframes)
        scope_form.addRow("İşlem analizi saat dilimi", self.analysis_timezone)
        dates = Q.QHBoxLayout(); dates.addWidget(self.date_from); dates.addWidget(self.date_to)
        scope_form.addRow("Tarih aralığı", dates)
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
        box.addWidget(Q.QLabel("Hangi ayarları tarayalım? Varsayılanlar sabit kalır; Tara seçince önerilen değerler kullanılır.", objectName="subtitle"))
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
        self.plan_inputs.setColumnWidth(1, 220)
        self.plan_inputs.setColumnWidth(2, 80); self.plan_inputs.setColumnWidth(3, 125)
        self.plan_inputs.setColumnWidth(4, 200)
        self.plan_inputs.itemDoubleClicked.connect(self.edit_scan_values)
        self.plan_inputs.itemSelectionChanged.connect(self.refresh_input_detail)
        self.plan_inputs.setMinimumHeight(260)
        self.plan_inputs.hide()
        input_workspace = Q.QWidget()
        input_workspace_layout = Q.QHBoxLayout(input_workspace)
        input_workspace_layout.setContentsMargins(0, 0, 0, 0)
        input_workspace_layout.addWidget(self.plan_inputs, 1)
        self.input_detail_panel = Q.QFrame()
        self.input_detail_panel.setFixedWidth(270)
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
        apply_range.clicked.connect(self.apply_input_numeric_range)
        numeric_form.addRow(apply_range)
        detail_layout.addWidget(self.input_numeric_range)
        detail_edit = Q.QPushButton("Önerilen aralığı değiştir")
        self.input_detail_edit = detail_edit
        detail_edit.clicked.connect(self.edit_selected_scan_values)
        detail_layout.addWidget(detail_edit)
        detail_layout.addStretch()
        input_workspace_layout.addWidget(self.input_detail_panel)
        self.input_workspace = input_workspace
        input_workspace.hide()
        box.addWidget(input_workspace, 1)
        scope_title = Q.QLabel("Test koşulları", objectName="sectionTitle")
        scope_frame = Q.QFrame()
        self.scope_frame = scope_frame
        scope_box = Q.QVBoxLayout(scope_frame)
        scope_box.setContentsMargins(8, 3, 8, 6)
        scope_box.setSpacing(8)
        scope_box.addLayout(scope_form)
        scope_box.addWidget(self.criteria_toggle)
        scope_box.addWidget(criteria_frame)
        scope_box.addWidget(advanced_cost_toggle)
        scope_box.addWidget(advanced_cost)
        scope_box.addWidget(self.session_variants_check)
        box.addWidget(scope_title)
        box.addWidget(scope_frame)
        action_bar = Q.QFrame()
        action_layout = Q.QVBoxLayout(action_bar)
        action_layout.setContentsMargins(12, 8, 12, 8)
        action_layout.setSpacing(5)
        actions = Q.QHBoxLayout()
        self.edit_input_button = Q.QPushButton("Seçili aralığı değiştir")
        self.edit_input_button.clicked.connect(self.edit_selected_scan_values)
        preview = Q.QPushButton("Hesapla", objectName="primary"); preview.clicked.connect(self.preview_plan)
        enqueue = Q.QPushButton("Görevleri kuyruğa ekle", objectName="primary"); enqueue.clicked.connect(self.enqueue_current_plan)
        self.enqueue_plan_button = enqueue
        enqueue.setEnabled(False)
        actions.addWidget(self.edit_input_button); actions.addWidget(preview)
        actions.addWidget(enqueue); actions.addStretch()
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
        box.addWidget(self._page_header("Sonuçlar ve hatalar", "Doğrulanmış presetler ve müdahale gerektiren olaylar."))
        controls = Q.QHBoxLayout()
        self.result_project = Q.QComboBox(); self.result_project.setMaximumWidth(260)
        self.result_project.currentIndexChanged.connect(self.refresh_results)
        self.result_filter = Q.QComboBox(); self.result_filter.addItems(["Başarılı", "Tümü", "dayanıklı", "hassas", "elenmiş", "geçersiz"])
        self.result_filter.setMaximumWidth(160)
        self.result_filter.currentIndexChanged.connect(self.refresh_results)
        filter_button = DisclosureButton("Filtrele")
        filter_button.setIcon(funnel_icon())
        filter_button.setCheckable(True)
        filter_button.toggled.connect(lambda checked: self.result_filter_panel.setVisible(checked))
        self.saved_result_filter = Q.QComboBox()
        self.saved_result_filter.setMaximumWidth(180)
        self.saved_result_filter.addItem("Kayıtlı filtre seç", None)
        self.saved_result_filter.currentIndexChanged.connect(self.apply_saved_result_filter)
        save_filter = Q.QPushButton("Filtreyi kaydet")
        save_filter.clicked.connect(self.save_result_filter)
        export = Q.QPushButton("Dışa aktar", objectName="primary"); export.clicked.connect(self.export_current_results)
        self.result_export_button = export
        self.result_compare = Q.QPushButton("Seçilenleri karşılaştır")
        self.result_compare.clicked.connect(self.compare_selected_results)
        self.result_validate = Q.QPushButton("Aşamalı doğrula")
        self.result_validate.clicked.connect(self.validate_selected_results)
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
        box.addWidget(self.events_table, 1)
        scroll = Q.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(Q.QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _research_page(self):
        Q = self.QtWidgets
        self._research_catalog = load_catalog()
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
        prepare.clicked.connect(self.prepare_research_provider_tasks)
        export_pdf = Q.QPushButton("Araştırma PDF'i")
        export_pdf.clicked.connect(self.export_research_report)
        export_success = Q.QPushButton("7 başarılıyı CSV/Excel indir")
        export_success.clicked.connect(self.export_successful_research_records)
        export_raw = Q.QPushButton("33.075 ham kaydı indir")
        export_raw.clicked.connect(self.export_historical_records)
        for control in (prepare, export_pdf, export_success, export_raw):
            control.setEnabled(research_available)
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
            "ftmo-session-33075-ham-kayit.csv", "CSV (*.csv);;Excel (*.xlsx)"
        )
        if not path:
            return
        excel = "Excel" in selected_filter or Path(path).suffix.lower() == ".xlsx"
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
            count = writer(iter_historical_records(), destination, input_ids)
            if count != 33_075:
                raise RuntimeError(f"Beklenen 33.075 kayıt yerine {count} kayıt yazıldı.")
            self.research_status.setText(f"{count:,} gerçek ham tarama kaydı {Path(destination).name} dosyasına kaydedildi.")
        except Exception as exc:
            self.research_status.setStyleSheet("color:#b54c42")
            self.research_status.setText(f"Ham kayıtlar dışa aktarılamadı: {exc}")

    def export_successful_research_records(self):
        Q = self.QtWidgets
        path, selected_filter = Q.QFileDialog.getSaveFileName(
            self.window, "Ağır maliyeti geçen 7 preset", "ftmo-7-basarili.csv",
            "CSV (*.csv);;Excel (*.xlsx)")
        if not path:
            return
        excel = "Excel" in selected_filter or Path(path).suffix.lower() == ".xlsx"
        destination = str(Path(path).with_suffix(".xlsx" if excel else ".csv"))
        records = iter(iter_successful_research_records(self._visible_research_catalog))
        first = next(records)
        writer = export_task_xlsx if excel else export_task_csv
        try:
            count = writer(itertools.chain((first,), records), destination,
                           first["payload"]["inputs"])
            self.research_status.setText(f"{count} ağır maliyet preseti kaydedildi; sağlayıcı/forward kanıtı ayrıca gösterilir.")
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
        open_tv = Q.QPushButton("9222 ile aç"); open_tv.clicked.connect(self.open_tradingview); tv_row.addWidget(open_tv)
        form.addRow("TradingView Desktop", tv_row)
        motor_advanced = DisclosureButton("Gelişmiş motor yolu")
        self.motor_path.setVisible(False)
        motor_advanced.toggled.connect(self.motor_path.setVisible)
        form.addRow(motor_advanced, self.motor_path)
        form.addRow("Atanacak proje", self.worker_project)
        box.addLayout(form)
        resource_row = Q.QHBoxLayout()
        self.resource_status = Q.QLabel("Kaynak ölçümü yapılmadı", objectName="status")
        measure = Q.QPushButton("Kaynakları ölç"); measure.clicked.connect(self.measure_resources)
        resource_row.addWidget(measure); resource_row.addWidget(self.resource_status); resource_row.addStretch()
        box.addLayout(resource_row)
        note = Q.QLabel("TradingView bağlantısı 9222 üzerinde açık olmalı. Yeni sekmeler yalnız bu oturumda açılır; mevcut grafikler değiştirilmez.")
        note.setWordWrap(True); note.setObjectName("subtitle"); box.addWidget(note)
        tab_row = Q.QHBoxLayout()
        self.new_tab_count = Q.QSpinBox(); self.new_tab_count.setRange(1, 16); self.new_tab_count.setValue(2); self.new_tab_count.setPrefix("Yeni sekme ")
        open_tabs = Q.QPushButton("9222 içinde yeni sekme aç"); open_tabs.clicked.connect(self.create_worker_tabs)
        claim_tabs = Q.QPushButton("Hazır worker layoutlarını bağla"); claim_tabs.clicked.connect(self.claim_worker_layouts)
        bind = Q.QPushButton("Seçili kaynağı projeye bağla"); bind.clicked.connect(self.bind_selected_strategy)
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
        start = Q.QPushButton("Taramayı başlat", objectName="primary"); start.clicked.connect(self.start_workers)
        self.start_workers_button = start
        start.setEnabled(False)
        stop = Q.QPushButton("Durdur"); stop.clicked.connect(self.stop_workers)
        actions.addWidget(discover); actions.addWidget(start); actions.addWidget(stop); actions.addStretch()
        self.worker_status = Q.QLabel("Bağlantı kontrol edilmedi", objectName="status"); actions.addWidget(self.worker_status)
        box.addLayout(actions)
        return page

    def find_tradingview(self):
        found = find_tradingview_executables()
        if found:
            self.tv_executable.setText(str(found[0]))
            self.worker_status.setText(f"TradingView bulundu · CDP {'hazır' if cdp_healthy() else 'kapalı'}")
        else:
            path, _ = self.QtWidgets.QFileDialog.getOpenFileName(self.window, "TradingView.exe seç", "", "Uygulama (*.exe)")
            if path: self.tv_executable.setText(path)

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
            QtCore.QTimer.singleShot(1200, self.discover_targets)
        except TabCreationError as exc:
            self.worker_status.setStyleSheet(f"color:{STATUS_ERROR}")
            count = len(exc.created_targets)
            self.worker_status.setText(
                f"{exc} {count} sekme doğrulanmış olabilir; yeniden açmadan önce listeyi yenileyin. "
                "Her worker için ayrı 'TV Scan Worker 1/2' layoutu oluşturun.")
            QtCore.QTimer.singleShot(1200, self.discover_targets)
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
        box.addWidget(self._page_header("Yeni tarama projesi", "Pine strategy kodunu analiz edin; inputlar kaydetmeden önce görünür."))
        self.project_name = Q.QLineEdit()
        self.project_name.setPlaceholderText("Proje adı")
        box.addWidget(self.project_name)
        self.pine_source = Q.QPlainTextEdit()
        self.pine_source.setPlaceholderText('//@version=6\nstrategy("Stratejim")\nlength = input.int(20, "Length")')
        self.pine_source.setMinimumHeight(230)
        box.addWidget(self.pine_source)
        controls = Q.QHBoxLayout()
        analyze = Q.QPushButton("Inputları analiz et", objectName="primary")
        analyze.clicked.connect(self.analyze_source)
        save = Q.QPushButton("Projeyi kaydet", objectName="primary")
        save.clicked.connect(self.save_project)
        controls.addWidget(analyze)
        controls.addWidget(save)
        controls.addStretch()
        box.addLayout(controls)
        self.project_status = Q.QLabel("Pine kodu bekleniyor", objectName="status")
        box.addWidget(self.project_status)
        self.input_table = Q.QTableWidget(0, 9)
        self.input_table.setHorizontalHeaderLabels(["Değişken", "Başlık", "Tür", "Varsayılan", "Seçenekler", "Min/Max/Adım", "Grup", "Tooltip", "Durum"])
        self.input_table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.input_table, 1)
        return page

    def _show_page(self, index):
        nav_button = self.nav_group.button(index)
        if nav_button is not None:
            nav_button.setChecked(True)
        if index != 4:
            self.result_detail_dock.hide()
        self.pages.setCurrentIndex(index)
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

    def save_project(self):
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
        project_id = self.store.create_project(name, source)
        self.project_status.setStyleSheet(f"color:{STATUS_SUCCESS}")
        self.project_status.setText(f"Proje kaydedildi · #{project_id}")
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
                for project in projects: project_combo.addItem(project["name"], project["id"])
                remembered = previous.get(target)
                index = project_combo.findData(remembered[0] if remembered else default_project)
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
                "Bu sekmedeki tam Pine kaynağı otomatik doğrulanamadı. "
                "Bu çalışma sekmesindeki stratejinin projeye yapıştırdığınız kodla aynı "
                "olduğunu TradingView'de kontrol ettiniz mi?"
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

    def start_workers(self):
        try:
            if self.driver is None: raise ValueError("Önce çalışma sekmelerini bulun.")
            if self.supervisor and self.supervisor.running:
                raise ValueError("Workerlar zaten çalışıyor; ikinci kez başlatılamaz.")
            if not cdp_healthy(9222):
                raise ValueError("9222 bağlantısı hazır değil; worker başlatılmadı.")
            assignments = []
            for row in range(self.worker_table.rowCount()):
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
            answer = self.QtWidgets.QMessageBox.question(
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
                supervisor.start(assignments)
            except Exception:
                if hasattr(self.driver, "target_guard"):
                    self.driver.target_guard = None
                raise
            self.supervisor = supervisor
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
            raise ValueError("Worker layoutu değişti veya başka sekmeyle çakışıyor; görev uygulanmadı.")
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
        if self.supervisor and self.supervisor.running:
            self.supervisor.stop()
            if hasattr(self, "worker_status"): self.worker_status.setText("Workerlar durduruldu")

    def refresh_worker_states(self):
        if not self.supervisor: return
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
        if self.pages.currentIndex() == 5:
            self.refresh_research_evidence()

    def load_plan_inputs(self):
        project_id = self.plan_project.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        self._loaded_plan_project_id = project_id if project else None
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
            self.auto_excluded_notice.hide()
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
        saved_plan = self.store.settings(project_id) or {}
        self.symbols.setText(", ".join(saved_plan.get("symbols", [])))
        self.timeframes.setText(", ".join(saved_plan.get("timeframes", [])))
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
        dependencies = input_dependencies(project["pine_source"])
        previous_results = self.store.results(project_id)
        prior_values = historical_values_by_input(previous_results)
        possible_no_effect = possible_no_effect_inputs(previous_results)
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
            stored_ui = (saved_plan.get("input_ui") or {}).get(f"in_{row}") or {}
            if stored_ui.get("decision") in {"Sabit bırak", "Tara", "Hariç tut"}:
                choice.setCurrentText(stored_ui["decision"])
            if isinstance(stored_ui.get("values"), list):
                values.setData(QtCore.Qt.UserRole, stored_ui["values"])
                values.setText(" · ".join(map(str, stored_ui["values"])))
            if isinstance(stored_ui.get("range"), dict):
                values.setData(QtCore.Qt.UserRole + 1, stored_ui["range"])
            values.setToolTip("Tara seçip 'Seçili aralığı değiştir' düğmesiyle bu öneriyi düzenleyebilirsiniz.")
            self.plan_inputs.setItem(row, 4, values)
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
        self.input_numeric_range.setVisible(numeric)
        self.input_detail_edit.setVisible(not numeric)
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
            if dialog.exec() != Q.QDialog.Accepted:
                return
            values = [list_widget.item(i).data(QtCore.Qt.UserRole)
                      for i in range(list_widget.count()) if list_widget.item(i).checkState() == QtCore.Qt.Checked]
        else:
            text, accepted = Q.QInputDialog.getText(
                self.window, f"{item.title} değerleri", "Değerleri virgülle ayırın:",
                text=", ".join(map(str, values))
            )
            if not accepted:
                return
            values = [value.strip() for value in text.split(",") if value.strip()]
        if not values:
            self.plan_status.setText(f"{item.title}: en az bir değer seçin.")
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
        name, accepted = self.QtWidgets.QInputDialog.getText(self.window, "Maliyet şablonu", "Şablon adı:")
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
                values[key] = suggested
        split = lambda text: tuple(value.strip() for value in text.split(",") if value.strip())
        variants = []
        if self.session_variants_check.isChecked():
            symbols = split(self.symbols.text())
            timeframes = split(self.timeframes.text())
            if len(symbols) != 1 or len(timeframes) != 1:
                raise ValueError("Birlikte session önerisi için tek sembol ve tek zaman dilimi seçin.")
            project = self.store.project(self.plan_project.currentData())
            variants = observed_session_variants(
                self._research_catalog, pine_hash=project["pine_hash"],
                symbol=symbols[0], timeframe=timeframes[0],
            )
            if not variants:
                raise ValueError("Bu Pine sürümü/sembol/zaman dilimi için gözlenmiş session paketi yok.")
            if any(key in SESSION_IDS and len(selected) > 1 for key, selected in values.items()):
                raise ValueError("Session paketleri açıkken session inputlarını ayrıca Tara yapmayın.")
            for key in SESSION_IDS:
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
            timeframes=split(self.timeframes.text()), input_values=values, date_range=date_range,
            criteria=success_criteria,
            costs={"assumptions": assumptions, "tradingview_inputs": tradingview_inputs,
                   "input_mapping": input_mapping},
            timeout=self.default_timeout.value(), poll_interval=self.default_poll.value(),
            stable_reads=self.default_stable.value(), variants=variants,
        )

    def preview_plan(self, *_args):
        try:
            plan = self._current_plan()
            count = plan.task_count
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
                f"{factors['variants']} ayar paketi × {input_product} input birleşimi = {count:,} görev"
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
            observed = self.store.observed_seconds_per_test(self.plan_project.currentData())
            duration = f" · tahmini {self._format_duration(count * observed)}" if observed else " · süre için geçmiş veri yok"
            selected = self.strategy_picker.currentData()
            selected_strategy = bool(self.study_id.text().strip())
            source_confirmed = bool(isinstance(selected, dict) and selected.get("source_confirmed"))
            dates_blocked = bool(plan.date_range) and not (
                GncZihinDriver.date_range_ready and GncZihinDriver.deep_capture_ready)
            if hasattr(self, "enqueue_plan_button"):
                self.enqueue_plan_button.setEnabled(count > 0 and selected_strategy and not dates_blocked)
            self.plan_status.setStyleSheet("color:#6b4c22")
            ready = (
                " · strateji kaynağı onaylı" if source_confirmed else
                " · strateji bulundu, kaynak onayı worker ekranında gerekli" if selected_strategy else
                " · kuyruğa eklemek için açık stratejiyi seçin"
            )
            if dates_blocked:
                ready = (
                    " · özel tarih henüz TradingView'e otomatik uygulanamıyor; "
                    "tarihli görev kuyruğa alınamaz"
                )
            self.plan_status.setText(f"{count:,} görev · tahmini {disk_text}{duration}{warning}{ready}")
            self.scan_flow_status.setText(
                f"Proje: hazır · Strateji: {'kaynak onaylı' if source_confirmed else 'yapısal eşleşme' if selected_strategy else 'eksik'} · "
                f"Plan: {count:,} kombinasyon hazır · Sekmeler: başlatmadan önce kullanıcı onayı"
            )
        except (ValueError, json.JSONDecodeError) as exc:
            if hasattr(self, "enqueue_plan_button"):
                self.enqueue_plan_button.setEnabled(False)
            self.plan_status.setStyleSheet("color:#b54c42"); self.plan_status.setText(str(exc))
            self.plan_factors.clear()
            self.scan_flow_status.setText("Proje/strateji/plan: eksik bilgiyi tamamlayın · Sekmeler: onay gerekli")

    def enqueue_current_plan(self):
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
            inserted = enqueue_plan(self.store, project_id, plan)
            self.store.save_settings(project_id, {"input_ui": {
                self.plan_inputs.item(row, 0).text(): {
                    "decision": self.plan_inputs.cellWidget(row, 3).currentText(),
                    "values": self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole) or [],
                    "range": self.plan_inputs.item(row, 4).data(QtCore.Qt.UserRole + 1) or {},
                } for row in range(self.plan_inputs.rowCount())
            }})
            self.plan_status.setStyleSheet(f"color:{STATUS_SUCCESS}")
            self.plan_status.setText(f"{inserted:,} yeni görev kuyruğa eklendi · toplam {plan.task_count:,}")
            self.refresh_dashboard()
        except (ValueError, json.JSONDecodeError) as exc:
            self.plan_status.setStyleSheet(f"color:{STATUS_ERROR}"); self.plan_status.setText(str(exc))

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

    def refresh_results(self, *_args):
        project_id = self.result_project.currentData()
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
        for row_index, row in enumerate(rows):
            payload, metrics = row["payload"], row["metrics"]
            values = (row["task_key"][:12], payload.get("symbol"), payload.get("timeframe"),
                      row["classification"], metrics.get("trades"), metrics.get("profit_factor"),
                      metrics.get("win_rate_pct"), metrics.get("max_drawdown_pct"),
                      metrics.get("net_profit"), "Doğrulandı" if row["verified"] else "İncele")
            for column, value in enumerate(values):
                cell = self.QtWidgets.QTableWidgetItem()
                cell.setData(QtCore.Qt.DisplayRole, value if value is not None else "—")
                cell.setData(QtCore.Qt.UserRole, row["task_id"])
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
        self.result_events_empty.setVisible(not events)
        self.events_table.setVisible(bool(events))
        self.events_table.setRowCount(len(events))
        for row_index, event in enumerate(events):
            for column, value in enumerate((event["level"], event["worker_id"], event["task_id"], event["message"], event["screenshot_path"])):
                self.events_table.setItem(row_index, column, self.QtWidgets.QTableWidgetItem(str(value if value is not None else "—")))

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
        name, accepted = self.QtWidgets.QInputDialog.getText(self.window, "Filtreyi kaydet", "Filtre adı:")
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
        self.result_compare.setEnabled(count >= 2)
        self.result_validate.setEnabled(count >= 1)

    def compare_selected_results(self):
        rows = self.selected_result_rows()
        if len(rows) < 2:
            self.QtWidgets.QMessageBox.information(self.window, "Preset karşılaştırma", "En az iki sonuç satırı seçin.")
            return
        metric_names = sorted({name for row in rows for name in row["metrics"]})
        dialog = self.QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Preset karşılaştırma"); dialog.resize(900, 560)
        layout = self.QtWidgets.QVBoxLayout(dialog)
        def comparison_period(row):
            dates = row["payload"].get("date_range") or {}
            return json.dumps(dates, ensure_ascii=False, sort_keys=True)

        def comparison_costs(row):
            return json.dumps(row["payload"].get("costs") or {}, ensure_ascii=False, sort_keys=True)

        periods = {comparison_period(row) for row in rows}
        costs = {comparison_costs(row) for row in rows}
        warning_text = (
            "Dikkat: test dönemleri veya maliyet varsayımları farklı; PF/DD doğrudan adil karşılaştırma değildir."
            if len(periods) > 1 or len(costs) > 1 else
            "Aynı dönem ve maliyet varsayımlarıyla karşılaştırılıyor."
        )
        if any(not row.get("verified") for row in rows):
            warning_text += " Doğrulanmamış kayıtlar var; metrikleri karar için kullanmayın."
        warning = self.QtWidgets.QLabel(warning_text)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        table = self.QtWidgets.QTableWidget(len(metric_names) + 6, len(rows))
        table.setHorizontalHeaderLabels([row["task_key"][:12] for row in rows])
        labels = ["Sembol", "Timeframe", "Dönem", "Maliyet", "Kanıt", "Sınıf", *metric_names]
        table.setVerticalHeaderLabels(labels)
        for column, row in enumerate(rows):
            values = [row["payload"].get("symbol"), row["payload"].get("timeframe"),
                      comparison_period(row), comparison_costs(row),
                      "Doğrulandı" if row.get("verified") else "Doğrulanmadı", row["classification"]]
            values.extend(row["metrics"].get(name, "—") for name in metric_names)
            for line, value in enumerate(values):
                table.setItem(line, column, self.QtWidgets.QTableWidgetItem(str(value)))
        table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True); layout.addWidget(table)
        close = self.QtWidgets.QPushButton("Kapat"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        dialog.exec()

    def show_result_details(self, index):
        self.open_result_details_by_id(self.results_table.item(index.row(), 0).data(QtCore.Qt.UserRole))

    def open_result_details_by_id(self, task_id):
        row = self._result_by_id.get(task_id)
        if row is None:
            return
        metrics = row["metrics"]
        panel = self.QtWidgets.QWidget(self.result_detail_dock)
        panel.setMinimumWidth(330)
        layout = self.QtWidgets.QVBoxLayout(panel)
        expand = self.QtWidgets.QPushButton(
            "Yan panele dön" if self.result_detail_dock.isFloating() else "Grafikleri büyük aç"
        )
        expand.clicked.connect(self.toggle_result_detail_size)
        self.result_detail_expand = expand
        layout.addWidget(expand)
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
        sensitivity_layout.addWidget(self.QtWidgets.QLabel(
            "Yalnız aynı sembol, dönem, zaman dilimi ve maliyette tek inputu farklı kayıtlar gösterilir. "
            "Komşu yoksa dayanıklılık kanıtlanmış sayılmaz."
        ))
        neighbors = one_input_neighbors(row, self.store.results(self.result_project.currentData()))
        sensitivity_table = self.QtWidgets.QTableWidget(len(neighbors), 7)
        sensitivity_table.setHorizontalHeaderLabels(
            ["Input", "Bu değer", "Komşu değer", "Komşu işlem", "Komşu PF", "Komşu DD %", "Sınıf"]
        )
        sensitivity_table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        sensitivity_table.horizontalHeader().setStretchLastSection(True)
        for index, neighbor in enumerate(neighbors):
            other = neighbor["row"]
            values = (neighbor["input_id"], neighbor["base_value"], neighbor["other_value"],
                      other["metrics"].get("trades"), other["metrics"].get("profit_factor"),
                      other["metrics"].get("max_drawdown_pct"), other["classification"])
            for column, value in enumerate(values):
                sensitivity_table.setItem(index, column, self.QtWidgets.QTableWidgetItem(str(value)))
        sensitivity_layout.addWidget(sensitivity_table)
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
        symbol, accepted = self.QtWidgets.QInputDialog.getText(
            self.window, "Alternatif sağlayıcı", "Alternatif TradingView sembolü (örn. FX:EURUSD):"
        )
        if not accepted:
            return
        inserted = 0
        for row in rows:
            if row["verified"] and row["classification"] != "elenmiş":
                inserted += enqueue_followups(self.store, row["task_id"], row["payload"], symbol)
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
            visible = scope.currentIndex() == 1
            if visible:
                candidates = self._result_rows
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
                if pdf else "Ekran kapsamı yalnız görünen sonuç satırlarını içerir. Teknik hatalar dahil tüm görevler için proje kapsamını seçin."
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
        refresh_options()
        if dialog.exec() != Q.QDialog.Accepted:
            return

        successful = kind.currentIndex() == 1 or format_choice.currentText() == "PDF"
        visible_ids = {row["task_id"] for row in self._result_rows} if scope.currentIndex() == 1 else None
        if format_choice.currentText() == "PDF":
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

        excel = format_choice.currentText().startswith("Excel")
        suffix = "xlsx" if excel else "csv"
        destination, _ = Q.QFileDialog.getSaveFileName(
            self.window, "Tarama kayıtlarını kaydet", f"tv-scan-results.{suffix}",
            "Excel (*.xlsx)" if excel else "CSV (*.csv)")
        if destination:
            count = export_project_task_scope(
                self.store, project_id, destination, successful=successful,
                visible_ids=visible_ids, excel=excel,
            )
            if not count:
                Q.QMessageBox.information(self.window, "Dışa aktar", "Bu kapsamda kaydedilecek görev yok.")
                return
            Q.QMessageBox.information(self.window, "Dışa aktar", f"{count} görev kaydedildi.")

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
        stats = self.store.dashboard_stats()
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
        self.throughput_label.setText(f"Hız: {rate:,.1f} test/saat" if rate else "Hız: yeterli veri yok")
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

    def create_portable_backup(self):
        path, _ = self.QtWidgets.QFileDialog.getSaveFileName(
            self.window, "TV Scan Studio yedeği", "tv-scan-studio-backup.tvscan.zip", "TV Scan yedeği (*.tvscan.zip)"
        )
        if not path:
            return
        try:
            create_backup(self.store, path); manifest = verify_backup(path)
            self.dashboard_status.setText(f"Yedek doğrulandı · {manifest['project_count']} proje")
        except Exception as exc:
            self.dashboard_status.setText(f"Yedekleme başarısız: {exc}")

    def measure_resources(self):
        try:
            snapshot = system_snapshot(); recommendation = recommend_workers(snapshot)
            available_gb = snapshot.available_memory_bytes / (1024 ** 3)
            self.resource_status.setText(
                f"CPU %{snapshot.cpu_percent:.0f} · boş RAM {available_gb:.1f} GB · öneri {recommendation.recommended} worker"
            )
            observed = self.store.observed_seconds_per_test(self.worker_project.currentData())
            if observed:
                projections = project_worker_throughput(observed, recommendation.recommended)
                summary = " · ".join(
                    f"{row['workers']}w≈{row['tests_per_hour']:.0f}/sa{'*' if not row['within_safe_limit'] else ''}"
                    for row in projections
                )
                self.resource_status.setText(self.resource_status.text() + " · " + summary + " (*limit üstü)")
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
                application.processEvents()
                if studio.pages.currentIndex() != index:
                    return 2
            if studio.pages.count() != 7:
                return 2
        finally:
            studio.worker_timer.stop()
            studio.tray.hide()
            studio.window.close()
            application.processEvents()
    if created_application:
        application.quit()
    return 0


def main() -> int:
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
