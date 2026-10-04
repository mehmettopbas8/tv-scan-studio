"""Non-modal, anchored onboarding; never invokes business actions."""
from PySide6 import QtCore, QtWidgets


class GuidedTour(QtWidgets.QFrame):
    def __init__(self, window, steps, finished):
        super().__init__(window, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.window = window
        self.steps = steps
        self.finished = finished
        self.index = 0
        self.ended = False
        self.auto_advance_indices = set()
        self.was_ready = None
        window.installEventFilter(self)
        self.setFixedWidth(360)
        self.setStyleSheet("QFrame {background:white; color:#292d32; border:2px solid #b58738; border-radius:8px;} QLabel {border:0; padding:4px;} QPushButton {padding:7px;}")
        layout = QtWidgets.QVBoxLayout(self)
        self.heading = QtWidgets.QLabel()
        self.body = QtWidgets.QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(QtCore.Qt.PlainText)
        layout.addWidget(self.heading)
        layout.addWidget(self.body)
        actions = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton("Geri")
        self.next = QtWidgets.QPushButton("İleri")
        self.skip = QtWidgets.QPushButton("Turu atla")
        self.back.clicked.connect(lambda: self.advance(-1))
        self.next.clicked.connect(lambda: self.advance(1))
        self.skip.clicked.connect(self.finish)
        for button in (self.back, self.next, self.skip):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.highlight = QtWidgets.QFrame(window)
        self.highlight.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.highlight.setStyleSheet("background:transparent; border:3px solid #b58738; border-radius:4px;")
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.update_anchor)
        self.timer.start()
        self.render()

    def render(self):
        self.was_ready = None
        target, title, text, ready = self.steps[self.index]
        ancestor = target.parentWidget()
        while ancestor:
            if isinstance(ancestor, QtWidgets.QScrollArea):
                ancestor.ensureWidgetVisible(target, 20, 20)
            ancestor = ancestor.parentWidget()
        self.heading.setText(f"{self.index + 1}/{len(self.steps)} · {title}")
        self.body.setText(text)
        self.back.setEnabled(self.index > 0)
        self.next.setText("Anladım, bitir" if self.index == len(self.steps) - 1 else "İleri")
        self.adjustSize()
        self.update_anchor()
        self.show()

    def update_anchor(self):
        target, _, _, ready = self.steps[self.index]
        if not self.window.isVisible():
            self.hide()
            self.highlight.hide()
            return
        if not target.isVisible():
            self.hide()
            self.highlight.hide()
            return
        is_ready = ready is None or ready()
        if self.index in self.auto_advance_indices and self.was_ready is False and is_ready:
            self.next.setEnabled(True)
            self.advance(1)
            return
        self.was_ready = is_ready
        self.next.setEnabled(is_ready)
        point = target.mapTo(self.window, QtCore.QPoint(0, 0))
        self.highlight.setGeometry(QtCore.QRect(point, target.size()).adjusted(-3, -3, 3, 3))
        self.highlight.show()
        self.highlight.raise_()
        origin = self.window.mapToGlobal(QtCore.QPoint(0, 0))
        bounds = QtCore.QRect(origin, self.window.size())
        anchor = target.mapToGlobal(QtCore.QPoint(0, target.height() + 8))
        x = max(bounds.left() + 8, min(anchor.x(), bounds.right() - self.width() - 8))
        y = anchor.y()
        if y + self.height() > bounds.bottom() - 8:
            y = target.mapToGlobal(QtCore.QPoint(0, 0)).y() - self.height() - 8
        y = max(bounds.top() + 8, min(y, bounds.bottom() - self.height() - 8))
        self.move(x, y)

    def advance(self, amount):
        if amount > 0 and not self.next.isEnabled():
            return
        if self.index + amount >= len(self.steps):
            self.finish()
        else:
            self.index = max(0, self.index + amount)
            self.render()

    def finish(self):
        if self.ended:
            return
        self.ended = True
        self.timer.stop()
        self.window.removeEventFilter(self)
        self.highlight.deleteLater()
        self.hide()
        self.finished()
        self.deleteLater()

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QtCore.QEvent.Close:
            self.finish()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.finish()
        else:
            super().keyPressEvent(event)
