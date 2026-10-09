"""Non-modal, anchored onboarding; never invokes business actions."""
from PySide6 import QtCore, QtWidgets


def unobstructed_tour_position(target, size, window_bounds, screen_bounds):
    """Keep the highlighted control usable, including in narrow dialogs."""
    gap = 8
    protected = target.adjusted(-3, -3, 3, 3)
    candidates = (
        QtCore.QPoint(target.left(), target.bottom() + gap),
        QtCore.QPoint(target.left(), target.top() - size.height() - gap),
        QtCore.QPoint(target.right() + gap, target.top()),
        QtCore.QPoint(target.left() - size.width() - gap, target.top()),
    )
    for bounds in (window_bounds, screen_bounds):
        inner = bounds.adjusted(gap, gap, -gap, -gap)
        positions = []
        for point in candidates:
            x = max(inner.left(), min(point.x(), inner.right() - size.width() + 1))
            y = max(inner.top(), min(point.y(), inner.bottom() - size.height() + 1))
            rect = QtCore.QRect(QtCore.QPoint(x, y), size)
            if inner.contains(rect):
                positions.append(rect)
                if not rect.intersects(protected):
                    return rect.topLeft()
        if bounds == screen_bounds and positions:
            return min(positions, key=lambda rect: (
                rect.intersected(protected).width() * rect.intersected(protected).height()
            )).topLeft()
    return screen_bounds.topLeft() + QtCore.QPoint(gap, gap)


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
        self.heading.setWordWrap(True)
        self.heading.setTextFormat(QtCore.Qt.PlainText)
        self.body = QtWidgets.QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(QtCore.Qt.PlainText)
        layout.addWidget(self.heading)
        self.body_scroll = QtWidgets.QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.body_scroll.setWidget(self.body)
        layout.addWidget(self.body_scroll)
        actions = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton("Geri")
        self.next = QtWidgets.QPushButton("Sonraki")
        self.skip = QtWidgets.QPushButton("Turu atla")
        self.back.clicked.connect(self.previous_step)
        self.next.clicked.connect(self.next_step)
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
        if self.ended:
            return
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
        self.next.setText("Anladım" if self.index == len(self.steps) - 1 else "Sonraki")
        self.adjustSize()
        self.update_anchor()
        self.show()

    def update_anchor(self):
        if self.ended:
            return
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
        self.setFixedWidth(min(360, max(240, bounds.width() - 16)))
        self.body_scroll.setMaximumHeight(max(48, min(280, bounds.height() - 160)))
        self.adjustSize()
        target_rect = QtCore.QRect(target.mapToGlobal(QtCore.QPoint(0, 0)), target.size())
        screen = target.screen()
        screen_bounds = screen.availableGeometry() if screen is not None else bounds
        self.move(unobstructed_tour_position(target_rect, self.size(), bounds, screen_bounds))

    def previous_step(self):
        self.advance(-1)

    def next_step(self):
        self.advance(1)

    def advance(self, amount):
        if self.ended:
            return
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
        self.setProperty("helpRetired", True)
        self.timer.stop()
        self.window.removeEventFilter(self)
        self.highlight.deleteLater()
        self.hide()
        callback = self.finished
        self.finished = None
        try:
            callback()
        finally:
            # A retired tool window must not retain its QObject parent or
            # targets. The Python ownership cycle can otherwise outlive the
            # parent wrapper and crash when a modal loop drains DeferredDelete.
            self.steps = ()
            self.window = None
            self.deleteLater()

    def eventFilter(self, watched, event):
        if not hasattr(self, "window"):
            return False
        if watched is self.window and event.type() == QtCore.QEvent.Close:
            self.finish()
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.finish()
        else:
            super().keyPressEvent(event)
