"""Cancellable local preview/archive IO; no network or widgets."""
import threading
from PySide6 import QtCore
from .support_package import SupportCancelled, file_item, create_support_zip


class SupportJob(QtCore.QThread):
    progress = QtCore.Signal(object)
    result = QtCore.Signal(object)

    def __init__(self, *, path=None, number=None, items=None, destination=None):
        super().__init__()
        self.path, self.number = path, number
        self.items = tuple(items) if items is not None else None
        self.destination = destination
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            options = {"cancel": self.cancel_event.is_set, "progress": self.progress.emit}
            if self.items is None:
                item = file_item(self.path, self.number, **options)
                self.result.emit({"status": "preview", "item": item})
            else:
                manifest = create_support_zip(self.items, self.destination, **options)
                self.result.emit({"status": "ready", "manifest": manifest, "destination": str(self.destination)})
        except SupportCancelled:
            self.result.emit({"status": "cancelled"})
        except Exception as error:
            self.result.emit({"status": "error", "message": str(error)})
