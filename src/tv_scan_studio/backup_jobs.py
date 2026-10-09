"""Cancellable backup IO. No widget, chart, or active-store switch in workers."""
import threading
from PySide6 import QtCore

from .backup import BackupCancelled, create_backup, restore_backup


class BackupJob(QtCore.QThread):
    result = QtCore.Signal(object)
    progress = QtCore.Signal(object)

    def __init__(self, operation, *, store=None, source=None, destination, attachments=()):
        super().__init__()
        if operation not in {"create", "restore"}:
            raise ValueError("Unsupported backup operation")
        self.operation = operation
        self.store = store
        self.source = source
        self.destination = destination
        self.attachments = tuple(attachments)
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            options = dict(check_cancel=self.cancel_event.is_set, progress=self.progress.emit)
            if self.operation == "create":
                manifest = create_backup(self.store, self.destination, attachments=self.attachments, **options)
            else:
                manifest = restore_backup(self.source, self.destination, **options)
            # Published success wins over a cancellation arriving after publication.
            self.result.emit({"status": "ready", "operation": self.operation,
                              "manifest": manifest, "destination": str(self.destination)})
        except BackupCancelled:
            self.result.emit({"status": "cancelled", "operation": self.operation})
        except Exception as error:
            self.result.emit({"status": "error", "operation": self.operation, "message": str(error)})


class EvidenceJob(BackupJob):
    """Read-only explicit checksum check using the same safe thread retirement."""
    def __init__(self, store, reference):
        super().__init__('create', store=store, destination='')
        self.operation = 'evidence'
        self.reference = reference

    def run(self):
        from .restored_assets import resolve_restored_asset
        try:
            self.progress.emit({'stage': 'Kanıt dosyasının bütünlüğü kontrol ediliyor'})
            path = resolve_restored_asset(self.store, self.reference, check_cancel=self.cancel_event.is_set)
            if self.cancel_event.is_set():
                raise BackupCancelled()
            self.result.emit({'status': 'ready', 'path': str(path) if path else None,
                              'reference': self.reference})
        except BackupCancelled:
            self.result.emit({'status': 'cancelled'})
        except Exception as error:
            self.result.emit({'status': 'error', 'message': str(error)})
