"""Cancellable plan jobs. Admission writes atomically; neither job touches charts."""
import threading
from PySide6 import QtCore
from .planner import ScanPlan, PlanCancelled


class PlanAdmissionJob(QtCore.QThread):
    result = QtCore.Signal(object)
    progress = QtCore.Signal(object)

    def __init__(self, store, project_id, plan, *, settings=None, require_pending_subset=False, new_run=False, run_id=None):
        super().__init__()
        from copy import deepcopy
        self.store = store
        self.project_id = project_id
        self.plan = ScanPlan.from_dict(deepcopy(plan.to_dict()))
        self.settings = deepcopy(settings)
        self.require_pending_subset = require_pending_subset
        self.new_run = new_run
        self.run_id = run_id
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        from .planner import enqueue_plan
        try:
            inserted, run_id = enqueue_plan(self.store, self.project_id, self.plan,
                settings=self.settings, cancel_requested=self.cancel_event.is_set,
                require_pending_subset=self.require_pending_subset,
                new_run=self.new_run, run_id=self.run_id, return_run_id=True,
                progress=lambda processed, inserted: self.progress.emit(
                    {"project_id": self.project_id, "processed": processed, "inserted": inserted}))
            # Success means COMMIT completed; a late cancellation must not report rollback.
            self.result.emit({"project_id": self.project_id, "status": "ready", "inserted": inserted, "run_id": run_id})
        except PlanCancelled:
            self.result.emit({"project_id": self.project_id, "status": "cancelled"})
        except Exception as error:
            self.result.emit({"project_id": self.project_id, "status": "error", "message": str(error)})


class PlanCountJob(QtCore.QThread):
    result = QtCore.Signal(object)
    progress = QtCore.Signal(object)

    def __init__(self, plan, revision):
        super().__init__()
        # Do not share mutable input lists with UI editors.
        from copy import deepcopy
        self.plan = ScanPlan.from_dict(deepcopy(plan.to_dict()))
        self.revision = revision
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        try:
            eligible = self.plan.count_eligible(
                cancel_requested=self.cancel_event.is_set,
                progress=lambda examined, accepted: self.progress.emit(
                    {"revision": self.revision, "examined": examined, "accepted": accepted}))
            if self.cancel_event.is_set():
                raise PlanCancelled("Sayım iptal edildi.")
            before = self.plan.cartesian_count
            count = min(eligible, self.plan.sample_budget) if self.plan.method == "sample" else eligible
            self.result.emit({"revision": self.revision, "status": "ready", "before": before,
                              "skipped": before - eligible, "remaining": eligible, "tasks": count})
        except PlanCancelled:
            self.result.emit({"revision": self.revision, "status": "cancelled"})
        except Exception as error:
            self.result.emit({"revision": self.revision, "status": "error", "message": str(error)})


class PlanCountController(QtCore.QObject):
    drained = QtCore.Signal()
    result = QtCore.Signal(object)
    progress = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.revision = 0
        self.jobs = set()

    def start(self, plan):
        self.cancel()
        self.revision += 1
        job = PlanCountJob(plan, self.revision)
        self.jobs.add(job)
        job.result.connect(self.deliver)
        job.progress.connect(self.deliver_progress)
        job.finished.connect(lambda: self.retire(job))
        job.start()
        return self.revision

    def cancel(self):
        for job in self.jobs:
            job.cancel()

    @QtCore.Slot(object)
    def deliver(self, value):
        if value["revision"] == self.revision:
            self.result.emit(value)

    @QtCore.Slot(object)
    def deliver_progress(self, value):
        if value["revision"] == self.revision:
            self.progress.emit(value)

    def retire(self, job):
        self.jobs.discard(job)
        job.deleteLater()
        if not self.jobs:
            self.drained.emit()
