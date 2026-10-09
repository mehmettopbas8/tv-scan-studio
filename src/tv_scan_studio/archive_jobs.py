"""Background archive import/read; no GUI, task queue or settings mutations."""
import threading
from pathlib import Path
from PySide6 import QtCore

from .historical import iter_legacy_scan_records
from .research_archives import ArchiveCancelled, archive_catalog, import_archive, open_managed_archive, verify_managed_archive


class ArchiveLoadJob(QtCore.QThread):
    result = QtCore.Signal(object)
    progress = QtCore.Signal(object)

    def __init__(self, source, root):
        super().__init__()
        self.source = source
        self.root = root
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def check(self):
        if self.cancel_event.is_set():
            raise ArchiveCancelled("Arşiv yüklemesi iptal edildi.")

    def run(self):
        try:
            source, root = Path(self.source), Path(self.root)
            if source.parent.parent.resolve() == root.resolve():
                imported = open_managed_archive(source, root, cancel_requested=self.cancel_event.is_set)
            else:
                imported = import_archive(self.source, self.root,
                    cancel_requested=self.cancel_event.is_set, progress=self.progress.emit)
            self.progress.emit({"stage": "Görüntülenecek kayıtlar hazırlanıyor", "records": 0})
            rows = []
            for row in iter_legacy_scan_records(imported["path"], check_cancel=self.check):
                rows.append(row)
                if len(rows) % 256 == 0:
                    self.progress.emit({"stage": "Görüntülenecek kayıtlar hazırlanıyor", "records": len(rows)})
            self.check()
            # Detect a managed file changing while display rows were being read.
            manifest = verify_managed_archive(imported["path"].parent, cancel_requested=self.cancel_event.is_set)
            if len(rows) != manifest["record_count"] or any(row["evidence"]["archive_sha256"] != manifest["sha256"] for row in rows):
                raise ValueError("Arşiv görüntü hazırlanırken değişti; tekrar aç.")
            self.result.emit({"status": "ready", "imported": imported, "rows": rows})
        except ArchiveCancelled:
            self.result.emit({"status": "cancelled"})
        except Exception as error:
            self.result.emit({"status": "error", "message": str(error)})


class ArchiveCatalogJob(ArchiveLoadJob):
    def run(self):
        try:
            entries = archive_catalog(self.root, cancel_requested=self.cancel_event.is_set)
            self.check()
            self.result.emit({"status": "catalog_ready", "entries": entries})
        except ArchiveCancelled:
            self.result.emit({"status": "cancelled"})
        except Exception as error:
            self.result.emit({"status": "error", "message": str(error)})
