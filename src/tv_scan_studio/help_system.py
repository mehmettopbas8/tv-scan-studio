"""Central, read-only contextual help. Help never invokes application actions."""
from dataclasses import dataclass
from typing import Callable

from PySide6 import QtCore, QtWidgets


@dataclass(frozen=True)
class HelpSpec:
    feature_id: str
    version: int
    title: str
    tooltip: str
    detail: str
    target: QtWidgets.QWidget
    availability: Callable[[], str | None] | None = None
    next_step: str = ""

    def text(self, detailed=False):
        parts = [self.detail if detailed else self.tooltip]
        reason = self.availability() if self.availability else None
        if reason:
            parts.append("İşlem gerekli: " + reason)
        if detailed and self.next_step:
            parts.append("Sonraki adım: " + self.next_step)
        return "\n\n".join(parts)


@dataclass(frozen=True)
class TourSpec:
    feature_id: str
    version: int
    steps: tuple
    legacy_keys: tuple[str, ...] = ()
    auto_advance_indices: frozenset[int] = frozenset()


class HelpRegistry(QtCore.QObject):
    """Explicit registrations; missing help is reported, never fabricated."""
    def __init__(self, window, read_settings=None, save_settings=None, coordinator=None):
        super().__init__(window)
        self.window = window
        self.specs = {}
        self._targets = {}
        self._column_specs = {}
        self.dialog = None
        self.tours = {}
        self.coordinator = coordinator or self
        self._active_tour = None
        self._first_use = {}
        self._first_use_conditions = {}
        self.read_settings = read_settings or (lambda: {})
        self.save_settings = save_settings or (lambda _values: None)
        window.installEventFilter(self)
        if isinstance(window, QtWidgets.QDialog):
            window.finished.connect(lambda _result: self.finish_scope())

    @property
    def active_tour(self):
        return self.coordinator._active_tour

    @active_tour.setter
    def active_tour(self, value):
        self.coordinator._active_tour = value

    def child_scope(self, window):
        return HelpRegistry(window, self.read_settings, self.save_settings, self.coordinator)

    def finish_scope(self):
        if self.dialog:
            self.dialog.close()
        tour = self.active_tour
        if tour is not None and tour.window is self.window:
            tour.finish()

    def remove_tree(self, root):
        """Retire registrations before a dynamic page is deleted/replaced."""
        targets = {root, *root.findChildren(QtWidgets.QWidget)}
        tour = self.active_tour
        if tour is not None and any(step[0] in targets for step in tour.steps):
            tour.finish()
        for feature_id, spec in list(self.specs.items()):
            if spec.target in targets:
                del self.specs[feature_id]
                self._targets.pop(spec.target, None)
                self._first_use.pop(spec.target, None)
                self._first_use_conditions.pop(spec.target, None)
        self._column_specs = {key: value for key, value in self._column_specs.items() if key[0] not in targets}
        self.tours = {key: value for key, value in self.tours.items()
                      if not any(step[0] in targets for step in value.steps)}

    def register_tour(self, spec):
        if not spec.feature_id or spec.version < 1 or not spec.steps:
            raise ValueError("Tour requires a stable ID, version and steps")
        self.tours[spec.feature_id] = spec

    def bind_first_use(self, widget, feature_id, *, when=None):
        if feature_id not in self.tours:
            raise ValueError("Register the tour before binding first use")
        self._first_use[widget] = feature_id
        self._first_use_conditions[widget] = when
        widget.installEventFilter(self)

    def _first_use_if_visible(self, widget, feature_id):
        condition = self._first_use_conditions.get(widget)
        if (self._first_use.get(widget) == feature_id and widget.isVisible()
                and (condition is None or condition())):
            self.start_tour(feature_id, automatic=True)

    def start_tour(self, feature_id, *, automatic=False, finished=None):
        from .guided_tour import GuidedTour
        spec = self.tours[feature_id]
        # Completion belongs to the feature, not its copy revision. New copy
        # must not reset every user's completed tours.
        key = "help_tour_" + feature_id + "_completed"
        settings = self.read_settings()
        if automatic and (not self.window.isVisible() or settings.get(key)
                          or any(settings.get(alias) for alias in spec.legacy_keys)):
            return None
        if automatic and self.active_tour is not None:
            return None  # Never interrupt another first-use guide.
        if self.active_tour is not None:
            self.active_tour.finish()
        def complete():
            try:
                self.save_settings({key: True, **{alias: True for alias in spec.legacy_keys}})
            finally:
                # Persistence failure must not leave a retired tour active or
                # keep its deleted controls in the help catalogue.
                self.active_tour = None
                self.remove_tree(tour)
            if finished:
                finished()
        tour = GuidedTour(self.window, spec.steps, complete)
        tour.auto_advance_indices = set(spec.auto_advance_indices)
        self.active_tour = tour
        for name, button, short, detail in (
            ("back", tour.back, "Rehberin önceki adımına döner.", "Uygulama verisini veya ayarlarını değiştirmez; yalnız rehber adımını değiştirir."),
            ("next", tour.next, "Sonraki rehber adımına geçer; son adımda rehberi kapatır.", "Gerekli alan tamamlanana kadar kapalı olabilir. Bu düğme kayıt, tarama veya dosya işlemi yapmaz."),
            ("skip", tour.skip, "Rehberi kapatır ve bu özellik için atlandığını hatırlar.", "Özelliğin yardım düğmesinden rehberi yeniden açabilirsin. Atlamak iş işlemini onaylamak değildir."),
        ):
            self.register(HelpSpec(f"help.tour.{feature_id}.{name}", 1, button.text(), short, detail, button))
        return tour

    def register(self, spec):
        if not spec.feature_id or spec.version < 1 or not spec.tooltip.strip() or not spec.detail.strip():
            raise ValueError("Help requires a stable ID, version and meaningful text")
        if spec.feature_id in self.specs or spec.target in self._targets:
            raise ValueError("Duplicate help registration")
        self.specs[spec.feature_id] = spec
        self._targets[spec.target] = spec
        spec.target.setProperty("helpFeatureId", spec.feature_id)
        spec.target.setToolTip(spec.text())
        spec.target.installEventFilter(self)

    def register_columns(self, feature_id, table, explanations):
        if len(explanations) != table.columnCount():
            raise ValueError("Every table column needs an explanation")
        header = table.horizontalHeader()
        for index, (title, short, detail) in enumerate(explanations):
            spec = HelpSpec(f"{feature_id}.column.{index}", 1, title, short, detail, header)
            if spec.feature_id in self.specs or not short.strip() or not detail.strip():
                raise ValueError("Duplicate or incomplete column help")
            self.specs[spec.feature_id] = spec
            self._column_specs[header, index] = spec
            item = table.horizontalHeaderItem(index)
            if item:
                item.setToolTip(short)
        header.viewport().installEventFilter(self)

    def resolve(self, widget):
        while widget is not None:
            if widget in self._targets:
                return self._targets[widget]
            widget = widget.parentWidget()
        return None

    def show_help(self, feature_id):
        spec = self.specs[feature_id]
        if self.dialog is not None:
            self.dialog.close()
        dialog = QtWidgets.QDialog(self.window)
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.setWindowTitle(spec.title)
        dialog.resize(440, 240)
        layout = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QLabel(spec.text(detailed=True))
        text.setTextFormat(QtCore.Qt.PlainText)
        text.setWordWrap(True)
        layout.addWidget(text)
        if spec.target in self._first_use:
            guide = QtWidgets.QPushButton("Rehberi yeniden aç (?)")
            def reopen():
                dialog.close()
                self.start_tour(self._first_use[spec.target])
            guide.clicked.connect(reopen)
            layout.addWidget(guide)
        close = QtWidgets.QPushButton("Anladım")
        close.clicked.connect(dialog.close)
        layout.addWidget(close)
        self.dialog = dialog
        dialog.finished.connect(lambda _result: self._closed(dialog))
        dialog.show()

    def _closed(self, dialog):
        if self.dialog is dialog:
            self.dialog = None

    def missing_controls(self, root=None):
        root = root or self.window
        types = (QtWidgets.QAbstractButton, QtWidgets.QLineEdit,
                 QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                 QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox,
                 QtWidgets.QAbstractItemView)
        return [widget for widget in root.findChildren(QtWidgets.QWidget)
                if isinstance(widget, types) and not self._retired(widget) and self.resolve(widget) is None]

    @staticmethod
    def _retired(widget):
        # Finished guides remain QObject children until deferred deletion runs;
        # they are no longer user controls. Hidden *application* fields still
        # belong in the coverage audit and are deliberately not excluded.
        while widget is not None:
            if widget.property("helpRetired"):
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched, event):
        # Qt can deliver destruction events after Python attributes are cleared.
        if not hasattr(self, "window"):
            return False
        if event.type() == QtCore.QEvent.FocusIn and watched in self._first_use:
            feature_id = self._first_use[watched]
            QtCore.QTimer.singleShot(0, self, lambda: self._first_use_if_visible(watched, feature_id))
        if event.type() == QtCore.QEvent.ToolTip:
            parent = watched.parentWidget() if isinstance(watched, QtWidgets.QWidget) else None
            if isinstance(parent, QtWidgets.QHeaderView):
                spec = self._column_specs.get((parent, parent.logicalIndexAt(event.pos())))
                if spec:
                    QtWidgets.QToolTip.showText(event.globalPos(), spec.text(), watched)
                    return True
            spec = self.resolve(watched)
            if spec:
                QtWidgets.QToolTip.showText(event.globalPos(), spec.text(), watched)
                return True
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_F1:
            spec = self.resolve(watched) or self.resolve(QtWidgets.QApplication.focusWidget())
            if spec:
                self.show_help(spec.feature_id)
                return True
        if watched is self.window and event.type() == QtCore.QEvent.Close:
            self.finish_scope()
        return super().eventFilter(watched, event)
