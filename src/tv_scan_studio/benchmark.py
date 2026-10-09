"""Read-only benchmark capture. Local records are not live acceptance by themselves.

The caller must retain independent live evidence and review it before acceptance.
Nothing here starts TradingView, mutates a queue, or limits a workload.
"""
import hashlib
import json
import math
from pathlib import Path

from .throughput import run_stats

ANECDOTAL_REFERENCE = {"workers": 8, "tests_per_hour": 2100,
                       "provenance": "user_anecdote", "verified": False}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def serialize_record(record):
    """Return a portable local JSON record; caller chooses its save destination."""
    validate_record(record)
    return json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2)


def load_record(text):
    """Import capture without promoting file integrity to live authenticity."""
    record = json.loads(text)
    validate_record(record)
    return record


def validate_record(record):
    required = {"format", "run_id", "workers", "build_sha256", "context_hash", "source_hash",
                "workload_hash", "task_count", "verified_count", "active_seconds", "tests_per_hour",
                "attempt_count", "peak_concurrency", "retry_count", "failure_events", "provenance",
                "evidence", "captured_at", "eligible_for_review", "reasons", "acceptance", "record_hash"}
    if not isinstance(record, dict) or set(record) != required or record["format"] != 1:
        raise ValueError("Desteklenmeyen ölçüm kaydı.")
    if record["acceptance"] is not False:
        raise ValueError("İçe alınan kayıt canlı kabul iddiası taşıyamaz.")
    for key in ("run_id", "workers", "task_count", "verified_count", "attempt_count", "peak_concurrency",
                "retry_count", "failure_events"):
        if type(record[key]) is not int or record[key] < 0:
            raise ValueError("Ölçüm sayıları geçersiz.")
    if not 1 <= record["workers"] <= 16:
        raise ValueError("Ölçüm paralelliği geçersiz.")
    for key in ("active_seconds", "tests_per_hour", "captured_at"):
        value = record[key]
        if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
            raise ValueError("Ölçüm zamanı/hızı geçersiz.")
    if _hash({k: v for k, v in record.items() if k != "record_hash"}) != record["record_hash"]:
        raise ValueError("Ölçüm kaydı değiştirilmiş.")


def artifact_digest(path):
    """Hash an explicitly selected local evidence file, never discover private files."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Kanıt normal bir dosya olmalıdır.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    if not size:
        raise ValueError("Boş dosya canlı ölçüm kanıtı değildir.")
    return {"sha256": digest.hexdigest(), "size": size}


def capture_run(connection, run_id, *, workers, build_sha256, context,
                provenance, evidence_paths, now):
    """Freeze observed current DB evidence within caller's read transaction.

    context must describe the identical machine, TradingView version/account
    tier and measurement protocol using non-secret labels. Payload/source are
    fingerprinted, not exported. Provenance is an assertion, not authentication.
    """
    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("Paralellik 1–16 olmalıdır.")
    if not isinstance(build_sha256, str) or len(build_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in build_sha256):
        raise ValueError("Ölçülen EXE'nin SHA-256 kimliği gerekir.")
    required = {"machine", "tradingview_version", "account_tier", "protocol"}
    if not isinstance(context, dict) or set(context) != required or any(
            not isinstance(v, str) or not v.strip() for v in context.values()):
        raise ValueError("Makine, TradingView, hesap seviyesi ve protokol bağlamı gerekir.")
    if not isinstance(now, (int, float)) or not math.isfinite(now):
        raise ValueError("Ölçüm zamanı sonlu olmalıdır.")
    run = connection.execute("SELECT * FROM scan_runs WHERE id=? AND kind='scan'", (run_id,)).fetchone()
    if not run:
        raise ValueError("Kaynak anlık görüntüsü olan tarama koşusu gerekir.")
    tasks = connection.execute("SELECT t.*,rt.test_key FROM tasks t JOIN run_tasks rt ON rt.task_id=t.id "
                               "WHERE rt.run_id=? ORDER BY rt.test_key", (run_id,)).fetchall()
    attempts = connection.execute("SELECT a.* FROM attempt_history a JOIN run_tasks rt ON rt.task_id=a.task_id "
                                  "WHERE rt.run_id=? ORDER BY a.id", (run_id,)).fetchall()
    stats = run_stats(connection, run_id, now=now)
    reasons = []
    if provenance != "real_tradingview":
        reasons.append("Canlı TradingView ölçümü değil; sentetik/yerel veriler kabul dışı.")
    artifacts = [artifact_digest(p) for p in evidence_paths]
    if not artifacts:
        reasons.append("Bağımsız canlı ölçüm kanıtı yok.")
    if not tasks or any(t["status"] not in {"done", "failed", "cancelled", "manual_review"} for t in tasks):
        reasons.append("Koşu tamamlanmamış.")
    if len(tasks) != stats["verified_count"]:
        reasons.append("İş yükünün tamamı güncel kaynakla doğrulanmış değil.")
    if stats["timing_uncertain"] or not stats["average_tests_per_hour"]:
        reasons.append("En az 5 doğrulanmış test ve 60 saniye kesin aktif süre gerekir.")
    claims = [a for a in attempts if a["event"] == "claimed"]
    observed_workers = {a["worker_id"] for a in claims}
    if len(observed_workers) != workers:
        reasons.append("İstenen paralellikle gözlenen çalışan kimlikleri uyuşmuyor.")
    endpoints = []
    terminals = {}
    for attempt in attempts:
        if attempt["event"] in {"completed", "failed", "invalidated", "interrupted"}:
            key = (attempt["task_id"], attempt["attempt_number"])
            terminals[key] = min(terminals.get(key, attempt["created_at"]), attempt["created_at"])
    for claim in claims:
        stop = terminals.get((claim["task_id"], claim["attempt_number"]))
        start = claim["created_at"]
        if stop is None or not math.isfinite(start) or not math.isfinite(stop) or not start < stop <= now:
            reasons.append("Deneme başlangıç/bitiş kanıtı eksik veya geçersiz.")
            continue
        endpoints.extend(((start, 1), (stop, -1)))
    active = peak = 0
    for _, delta in sorted(endpoints):
        active += delta
        peak = max(peak, active)
    if peak != workers:
        reasons.append("İstenen eşzamanlı paralellik ölçümde gerçekleşmemiş.")
    # Exclude mutable runtime bindings/evaluation, retain real full workload identity.
    excluded = {"criteria", "validation", "study_id", "timeout", "poll_interval", "stable_reads"}
    workload = [{k: v for k, v in json.loads(t["payload"]).items() if k not in excluded} for t in tasks]
    workload.sort(key=lambda p: json.dumps(p, sort_keys=True))
    record = {"format": 1, "run_id": run_id, "workers": workers,
              "build_sha256": build_sha256, "context_hash": _hash(context),
              "source_hash": hashlib.sha256(run["source_snapshot"].encode()).hexdigest(),
              "workload_hash": _hash(workload), "task_count": len(tasks),
              "verified_count": stats["verified_count"], "active_seconds": stats["active_seconds"],
              "tests_per_hour": stats["average_tests_per_hour"],
              "attempt_count": len(claims),
              "peak_concurrency": peak,
              "retry_count": sum(a["attempt_number"] > 1 for a in claims),
              "failure_events": sum(a["event"] == "failed" for a in attempts),
              "provenance": provenance, "evidence": artifacts, "captured_at": now,
              "eligible_for_review": not reasons, "reasons": reasons,
              "acceptance": False}
    record["record_hash"] = _hash(record)
    return record


def compare_records(baseline, candidate, *, reviewed_hashes=(), regression_fraction=0.1):
    """Compare exactly one old/new capture at 1/2/8 workers, never guessed rates.

    reviewed_hashes must come from separate review of live evidence, not a unit
    test or this capture routine. Significant loss stays open for explanation.
    """
    if not 0 <= regression_fraction < 1:
        raise ValueError("Hız kaybı eşiği 0 dahil, 1 hariç aralıkta olmalıdır.")
    groups = []
    for records in (baseline, candidate):
        records = list(records)
        if len(records) != 3 or {r["workers"] for r in records} != {1, 2, 8}:
            raise ValueError("Her sürüm için tam 1/2/8 çalışan ölçümü gerekir.")
        for record in records:
            validate_record(record)
            if not record["eligible_for_review"] or record["provenance"] != "real_tradingview":
                raise ValueError("Eksik veya sentetik ölçüm karşılaştırılamaz.")
            if (not record["evidence"] or record["verified_count"] != record["task_count"]
                    or record["verified_count"] < 5 or record["active_seconds"] < 60
                    or record["peak_concurrency"] != record["workers"]
                    or not math.isclose(record["tests_per_hour"],
                                        record["verified_count"] * 3600 / record["active_seconds"])):
                raise ValueError("Ölçümün hız veya tamamlanma kanıtı tutarsız.")
        if len({r["build_sha256"] for r in records}) != 1:
            raise ValueError("Aynı sürüm grubunda EXE kimliği değişmiş.")
        groups.append({r["workers"]: r for r in records})
    if groups[0][1]["build_sha256"] == groups[1][1]["build_sha256"]:
        raise ValueError("Başlangıç ve yeni EXE ayrı kimlikler taşımalıdır.")
    fingerprints = {(r["context_hash"], r["source_hash"], r["workload_hash"], r["task_count"])
                    for group in groups for r in group.values()}
    if len(fingerprints) != 1:
        raise ValueError("Makine, kaynak veya kontrollü iş yükü karşılaştırılabilir değil.")
    rows = []
    for workers in (1, 2, 8):
        old, new = (g[workers] for g in groups)
        ratio = new["tests_per_hour"] / old["tests_per_hour"]
        rows.append({"workers": workers, "baseline": old["tests_per_hour"],
                     "candidate": new["tests_per_hour"], "ratio": ratio,
                     "regression_requires_explanation": ratio < 1 - regression_fraction})
    reviewed = all(r["record_hash"] in reviewed_hashes for g in groups for r in g.values())
    return {"rows": rows, "live_evidence_reviewed": reviewed,
            "performance_gate": "passed" if reviewed and not any(
                r["regression_requires_explanation"] for r in rows) else "open",
            "anecdotal_reference": dict(ANECDOTAL_REFERENCE)}


class BaselineObserver:
    """External read-only witness for an old DB without immutable run tables.

    Start before claiming any task. Poll while the old EXE runs; every attempt
    must actually be observed running and then terminal. Missed transitions
    fail closed. This never creates legacy history or upgrades old results.
    DB timestamps remain old-application observations, requiring native review.
    """

    def __init__(self, connection, project_id, task_ids):
        if not task_ids or len(set(task_ids)) != len(task_ids):
            raise ValueError("Farklı ve açık görev kimlikleri gerekir.")
        self.project_id = project_id
        self.task_ids = tuple(task_ids)
        self.source = self._source(connection)
        self.initial = self._tasks(connection)
        if any(t["status"] != "pending" or t["attempts"] != 0 for t in self.initial):
            raise ValueError("Gözlem bütün görevler ilk denemeden önce beklerken başlamalıdır.")
        self.payloads = {t["id"]: json.loads(t["payload"]) for t in self.initial}
        self.intervals = {}
        self.previous = {t["id"]: ("pending", 0) for t in self.initial}
        self.finished = {}
        self.last_poll = None

    def _source(self, connection):
        row = connection.execute("SELECT pine_source FROM projects WHERE id=?", (self.project_id,)).fetchone()
        if row is None:
            raise ValueError("Strateji bulunamadı.")
        return row[0]

    def _tasks(self, connection):
        rows = [dict(connection.execute("SELECT * FROM tasks WHERE id=? AND project_id=?",
                (task_id, self.project_id)).fetchone() or {}) for task_id in self.task_ids]
        if any(not row for row in rows):
            raise ValueError("Gözlenen görev eksik veya başka stratejiye ait.")
        return rows

    def poll(self, connection, *, observed_at):
        if type(observed_at) not in {int, float} or not math.isfinite(observed_at) or (
                self.last_poll is not None and observed_at <= self.last_poll):
            raise ValueError("Gözlem zamanı kesin ve ileri gitmelidir.")
        if self._source(connection) != self.source:
            raise ValueError("Gözlem sırasında Pine kaynağı değişti.")
        for task in self._tasks(connection):
            task_id, status, attempt = task["id"], task["status"], task["attempts"]
            if type(attempt) is not int or attempt < 0 or status not in {
                    "pending", "running", "done", "failed", "cancelled", "manual_review"}:
                raise ValueError("Görev durumu/deneme sayısı geçersiz.")
            if json.loads(task["payload"]) != self.payloads[task_id]:
                raise ValueError("Gözlem sırasında iş yükü değişti.")
            old_status, old_attempt = self.previous[task_id]
            if task_id in self.finished and (status != "done" or attempt != old_attempt):
                raise ValueError("Doğrulanmış görev yeniden başlatılamaz/değiştirilemez.")
            if attempt < old_attempt:
                raise ValueError("Deneme sayısı geriye gidemez.")
            if attempt > old_attempt and (attempt != old_attempt + 1 or old_status != "pending"):
                raise ValueError("Yeni deneme önceki deneme bittiğinde beklemeden başlayamaz.")
            if old_status in {"failed", "cancelled", "manual_review"} and status != old_status:
                raise ValueError("Sonlanan görev bu ölçüm içinde yeniden açılamaz.")
            key = (task_id, attempt)
            if status == "running":
                start = task.get("started_at")
                if (attempt < 1 or attempt > old_attempt + 1 or type(start) not in {int, float}
                        or not math.isfinite(start) or start > observed_at
                        or type(task.get("worker_id")) is not int or task["worker_id"] < 1):
                    raise ValueError("Deneme başlangıç kanıtı geçersiz veya atlandı.")
                current = {"task_id": task_id, "attempt": attempt, "worker": task["worker_id"], "start": start}
                if key in self.intervals and any(self.intervals[key][k] != v for k, v in current.items()):
                    raise ValueError("Deneme kimliği/zamanı gözlem sırasında değişti.")
                self.intervals.setdefault(key, current)
            elif status != "pending" or attempt:
                if key not in self.intervals:
                    raise ValueError("Çalışırken gözlenmeyen deneme sonradan üretilemez.")
                stop = task.get("finished_at")
                interval = self.intervals[key]
                if type(stop) not in {int, float} or not math.isfinite(stop) or not interval["start"] < stop <= observed_at:
                    raise ValueError("Deneme bitiş kanıtı eksik/geçersiz.")
                if "stop" in interval and (interval["stop"] != stop or interval["outcome"] != status):
                    raise ValueError("Biten denemenin kanıtı değişti.")
                interval.update(stop=stop, outcome=status)
                if status == "done":
                    result = connection.execute("SELECT * FROM results WHERE task_id=?", (task_id,)).fetchone()
                    proof = connection.execute("SELECT evidence FROM verification_evidence WHERE task_id=?", (task_id,)).fetchone()
                    if not result or not result["verified"] or not proof:
                        raise ValueError("Doğrulanmış sonuç/grafik kanıtı eksik.")
                    evidence = json.loads(proof[0])
                    payload = self.payloads[task_id]
                    if (evidence.get("symbol") != payload.get("symbol") or evidence.get("timeframe") != payload.get("timeframe")
                            or evidence.get("inputs") != payload.get("inputs")):
                        raise ValueError("Sonuç uygulanan iş yüküyle eşleşmiyor.")
                    frozen = {"result_hash": _hash(dict(result)), "evidence_hash": _hash(evidence)}
                    if task_id in self.finished and self.finished[task_id] != frozen:
                        raise ValueError("Sonuç gözlem sırasında değişti.")
                    self.finished[task_id] = frozen
            self.previous[task_id] = (status, attempt)
        self.last_poll = observed_at

    def manifest(self):
        """Portable versioned observer proof, with no Pine code/private raw rows."""
        if len(self.finished) != len(self.task_ids) or any("stop" not in item for item in self.intervals.values()):
            raise ValueError("Gözlenen iş yükü henüz bütünüyle doğrulanmadı.")
        excluded = {"criteria", "validation", "study_id", "timeout", "poll_interval", "stable_reads"}
        workload = [{k: v for k, v in payload.items() if k not in excluded} for payload in self.payloads.values()]
        workload.sort(key=lambda p: json.dumps(p, sort_keys=True))
        result = {"observer_format": 1, "kind": "external_old_exe_observer",
                  "source_hash": hashlib.sha256(self.source.encode()).hexdigest(),
                  "workload_hash": _hash(workload), "task_count": len(self.task_ids),
                  "intervals": sorted(self.intervals.values(), key=lambda x: (x["task_id"], x["attempt"])),
                  "results": self.finished, "last_poll": self.last_poll,
                  "clock_provenance": "old_exe_db_timestamps_observed_during_execution"}
        result["manifest_hash"] = _hash(result)
        return result


def import_baseline_observation(manifest, *, workers, build_sha256, context, evidence_paths):
    """Convert external observer schema into existing format-1 capture contract.

    Integrity is not authentication. Independent live review is still mandatory.
    """
    fields = {"observer_format", "kind", "source_hash", "workload_hash", "task_count", "intervals",
              "results", "last_poll", "clock_provenance", "manifest_hash"}
    if (not isinstance(manifest, dict) or set(manifest) != fields or type(manifest.get("observer_format")) is not int
            or manifest.get("observer_format") != 1
            or manifest.get("kind") != "external_old_exe_observer"
            or manifest.get("clock_provenance") != "old_exe_db_timestamps_observed_during_execution"
            or manifest.get("manifest_hash") != _hash({k: v for k, v in manifest.items() if k != "manifest_hash"})):
        raise ValueError("Eski sürüm gözlem manifesti doğrulanamadı.")
    for key in ("source_hash", "workload_hash", "manifest_hash"):
        value = manifest[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Kaynak/iş yükü SHA-256 kimliği gerekli.")
    if (type(workers) is not int or not 1 <= workers <= 16 or not isinstance(build_sha256, str)
            or len(build_sha256) != 64 or any(c not in "0123456789abcdef" for c in build_sha256)
            or not isinstance(context, dict) or set(context) != {"machine", "tradingview_version", "account_tier", "protocol"}
            or any(not isinstance(v, str) or not v.strip() for v in context.values())):
        raise ValueError("Sürüm/paralellik/bağlam kimliği eksik.")
    intervals = manifest["intervals"]
    if (type(manifest.get("task_count")) is not int or manifest["task_count"] < 1
            or type(manifest.get("last_poll")) not in {int, float}
            or not math.isfinite(manifest["last_poll"]) or manifest["last_poll"] < 0
            or not isinstance(manifest.get("results"), dict)
            or not isinstance(intervals, list) or not intervals
            or any(not isinstance(item, dict) or "stop" not in item for item in intervals)):
        raise ValueError("Bütün denemelerin zaman kanıtı gerekir.")
    for proof in manifest["results"].values():
        if not isinstance(proof, dict) or set(proof) != {"result_hash", "evidence_hash"} or any(
                not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                for value in proof.values()):
            raise ValueError("Sonuç/grafik kanıtının SHA-256 kimliği gerekli.")
    keys = set()
    for item in intervals:
        if set(item) != {"task_id", "attempt", "worker", "start", "stop", "outcome"}:
            raise ValueError("Gözlem aralığı alanları eksik/farklı.")
        key = (item["task_id"], item["attempt"])
        if (key in keys or any(type(item[k]) is not int or item[k] < 1 for k in ("task_id", "attempt", "worker"))
                or any(type(item[k]) not in {int, float} or not math.isfinite(item[k]) for k in ("start", "stop"))
                or not 0 <= item["start"] < item["stop"] <= manifest["last_poll"]
                or item["outcome"] not in {"done", "failed", "pending", "cancelled", "manual_review"}):
            raise ValueError("Gözlem aralığı/kimliği geçersiz.")
        keys.add(key)
    if {str(item["task_id"]) for item in intervals} != {str(key) for key in manifest["results"]}:
        raise ValueError("Sonuçların deneme kimlikleri eşleşmiyor.")
    if manifest["task_count"] != len(manifest["results"]):
        raise ValueError("Sonuç sayısı gözlenen görevlerle eşleşmiyor.")
    for task_id in {item["task_id"] for item in intervals}:
        attempts = sorted((item for item in intervals if item["task_id"] == task_id), key=lambda item: item["attempt"])
        if ([item["attempt"] for item in attempts] != list(range(1, len(attempts) + 1))
                or attempts[-1]["outcome"] != "done"
                or any(item["outcome"] != "pending" for item in attempts[:-1])
                or any(a["stop"] > b["start"] for a, b in zip(attempts, attempts[1:]))):
            raise ValueError("Deneme sırası, yeniden deneme veya son durum çelişkili.")
    events = sorted((point, delta) for item in intervals for point, delta in
                    ((item["start"], 1), (item["stop"], -1)))
    active = peak = 0
    elapsed = 0.0
    last = events[0][0]
    for point, delta in events:
        if active:
            elapsed += point - last
        active += delta
        peak = max(peak, active)
        last = point
    count = manifest["task_count"]
    artifacts = [artifact_digest(path) for path in evidence_paths]
    reasons = []
    if (count != len(manifest["results"]) or count < 5 or elapsed < 60 or peak != workers
            or len({item["worker"] for item in intervals}) != workers or not artifacts):
        reasons.append("Tam iş yükü, paralellik, süre veya canlı kanıt yetersiz.")
    record = {"format": 1, "run_id": 0, "workers": workers, "build_sha256": build_sha256,
              "context_hash": _hash(context), "source_hash": manifest["source_hash"],
              "workload_hash": manifest["workload_hash"], "task_count": count,
              "verified_count": len(manifest["results"]), "active_seconds": elapsed,
              "tests_per_hour": count * 3600 / elapsed if elapsed else 0,
              "attempt_count": len(intervals), "peak_concurrency": peak,
              "retry_count": sum(item["attempt"] > 1 for item in intervals),
              "failure_events": sum(item["outcome"] != "done" for item in intervals),
              "provenance": "real_tradingview", "evidence": artifacts,
              "captured_at": manifest["last_poll"], "eligible_for_review": not reasons,
              "reasons": reasons, "acceptance": False}
    record["record_hash"] = _hash(record)
    validate_record(record)
    return record
