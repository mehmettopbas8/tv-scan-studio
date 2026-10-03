"""Painted Qt controls for the research-workbench interface."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


INK = QtGui.QColor("#28332e")
MUTED = QtGui.QColor("#68756d")
ACCENT = QtGui.QColor("#b9863f")
SUCCESS = QtGui.QColor("#477a62")
LINE = QtGui.QColor("#d8d0c2")


class SwitchToggle(QtWidgets.QCheckBox):
    """QCheckBox semantics with a track/thumb rather than platform chrome."""

    def sizeHint(self) -> QtCore.QSize:
        font = QtGui.QFontMetrics(self.font())
        return QtCore.QSize(54 + font.horizontalAdvance(self.text()) + 12,
                            max(32, font.height() + 12))

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        center_y = rect.center().y()
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush((SUCCESS if self.isChecked() else LINE) if self.isEnabled()
                         else QtGui.QColor("#d8d8d0"))
        painter.drawRoundedRect(QtCore.QRectF(3, center_y - 10, 38, 20), 10, 10)
        painter.setBrush(QtGui.QColor("#ffffff"))
        painter.drawEllipse(QtCore.QRectF(22 if self.isChecked() else 5, center_y - 8, 16, 16))
        painter.setPen(INK if self.isEnabled() else MUTED)
        text_rect = QtCore.QRect(53, 0, max(0, rect.width() - 57), rect.height())
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         painter.fontMetrics().elidedText(self.text(), QtCore.Qt.ElideRight,
                                                          text_rect.width()))
        if self.hasFocus():
            painter.setPen(QtGui.QPen(ACCENT, 1.5))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -2, -2), 7, 7)
        painter.end()


class DisclosureButton(QtWidgets.QPushButton):
    """Keyboard-operable section header with a drawn chevron."""

    def __init__(self, text: str, parent: QtWidgets.QWidget | None = None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setObjectName("disclosure")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(44)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        bounds = QtCore.QRectF(self.rect()).adjusted(1, 1, -2, -2)
        painter.setPen(QtGui.QPen(ACCENT if self.hasFocus() else LINE,
                                  1.5 if self.hasFocus() else 1))
        painter.setBrush(QtGui.QColor("#f2ecdf") if self.isChecked() else
                         QtGui.QColor("#f9f6ef") if self.underMouse() else
                         QtGui.QColor("#fffdf9"))
        painter.drawRoundedRect(bounds, 8, 8)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(ACCENT if self.isChecked() else QtGui.QColor("#aeb8ae"))
        painter.drawRoundedRect(QtCore.QRectF(1, 8, 3, bounds.height() - 16), 1.5, 1.5)
        painter.setPen(INK if self.isEnabled() else MUTED)
        has_icon = not self.icon().isNull()
        if has_icon:
            self.icon().paint(painter, QtCore.QRect(16, (self.height() - 18) // 2, 18, 18))
        text_x = 41 if has_icon else 17
        text_rect = QtCore.QRect(text_x, 0, max(0, self.width() - text_x - 38), self.height())
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         painter.fontMetrics().elidedText(self.text(), QtCore.Qt.ElideRight,
                                                          text_rect.width()))
        x, y = self.width() - 24, self.height() // 2
        chevron_pen = QtGui.QPen(ACCENT if self.isChecked() else MUTED, 2)
        chevron_pen.setCapStyle(QtCore.Qt.RoundCap)
        chevron_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(chevron_pen)
        path = QtGui.QPainterPath()
        if self.isChecked():
            path.moveTo(x - 5, y + 2); path.lineTo(x, y - 3); path.lineTo(x + 5, y + 2)
        else:
            path.moveTo(x - 5, y - 2); path.lineTo(x, y + 3); path.lineTo(x + 5, y - 2)
        painter.drawPath(path)
        painter.end()


class DecisionChoice(QtWidgets.QComboBox):
    """Compact three-way scan decision with custom paint and native popup semantics."""

    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(30)
        self.setAccessibleName("Input tarama kararı")

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        state = self.currentText()
        if state == "Tara":
            surface, accent = QtGui.QColor("#eee0c7"), ACCENT
        elif state == "Hariç tut":
            surface, accent = QtGui.QColor("#e8ece7"), MUTED
        else:
            surface, accent = QtGui.QColor("#f4f1e9"), LINE
        bounds = QtCore.QRectF(self.rect()).adjusted(1, 1, -2, -2)
        painter.setPen(QtGui.QPen(ACCENT if self.hasFocus() else accent, 1.5 if self.hasFocus() else 1))
        painter.setBrush(surface)
        painter.drawRoundedRect(bounds, 6, 6)
        painter.setPen(INK if self.isEnabled() else MUTED)
        text_rect = QtCore.QRect(9, 0, max(0, self.width() - 28), self.height())
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         painter.fontMetrics().elidedText(state, QtCore.Qt.ElideRight, text_rect.width()))
        x, y = self.width() - 14, self.height() // 2
        painter.setPen(QtGui.QPen(MUTED, 1.5))
        path = QtGui.QPainterPath()
        path.moveTo(x - 4, y - 2); path.lineTo(x, y + 2); path.lineTo(x + 4, y - 2)
        painter.drawPath(path)
        painter.end()
