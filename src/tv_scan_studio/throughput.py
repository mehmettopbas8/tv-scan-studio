"""Run-scoped verified throughput; parallel time is a union, not a sum."""
import time


def run_stats(connection, run_id, *, now=None):
    now = time.time() if now is None else now
    empty = {"run_id": run_id, "tests_per_hour": 0.0, "average_tests_per_hour": 0.0,
             "verified_count": 0, "window_verified_count": 0, "active_seconds": 0.0,
             "window_active_seconds": 0.0, "eta_seconds": None, "timing_uncertain": False}
    run = connection.execute("SELECT * FROM scan_runs WHERE id=? AND kind='scan'", (run_id,)).fetchone()
    if run is None:
        return empty
    # An unfinished claim only contributes while it is still the running attempt.
    # Recovered/interrupted attempts cannot prove when the process stopped.
    intervals = """
        SELECT c.created_at start,
          COALESCE((SELECT MIN(e.created_at) FROM attempt_history e
            WHERE e.task_id=c.task_id AND e.attempt_number=c.attempt_number
              AND e.event IN ('completed','failed','invalidated','interrupted')), ?) stop,
          EXISTS(SELECT 1 FROM attempt_history e WHERE e.task_id=c.task_id
            AND e.attempt_number=c.attempt_number AND e.event='interrupted') uncertain
        FROM attempt_history c JOIN run_tasks rt ON rt.task_id=c.task_id
        JOIN tasks t ON t.id=c.task_id
        WHERE rt.run_id=? AND c.event='claimed' AND c.created_at<=?
          AND (EXISTS(SELECT 1 FROM attempt_history e WHERE e.task_id=c.task_id
             AND e.attempt_number=c.attempt_number AND e.event<>'claimed')
            OR (t.status='running' AND t.attempts=c.attempt_number))
    """
    def elapsed(lower):
        row = connection.execute("WITH intervals AS (" + intervals + """), clipped AS (
            SELECT MAX(start,?) start,MIN(stop,?) stop,uncertain FROM intervals
            WHERE stop>? AND start<? AND stop>start
        ), merged AS (
            SELECT *,MAX(stop) OVER (ORDER BY start,stop ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) previous
            FROM clipped
        ) SELECT COALESCE(SUM(MAX(0,stop-MAX(start,COALESCE(previous,start)))),0) seconds,
            COALESCE(MAX(uncertain),0) uncertain FROM merged""",
            (now, run_id, now, lower, now, lower, now)).fetchone()
        return float(row["seconds"]), bool(row["uncertain"])
    # Count each current, verified task once, using immutable source and claim proof.
    verified = """
        SELECT h.created_at FROM result_history h JOIN run_tasks rt ON rt.task_id=h.task_id
        JOIN tasks t ON t.id=h.task_id JOIN results r ON r.task_id=h.task_id
        WHERE rt.run_id=? AND h.attempt_number=t.attempts AND t.status='done'
          AND r.verified=1 AND h.verified=1 AND h.source_provenance='claim_snapshot'
          AND h.source_snapshot=? AND h.created_at<=?
          AND h.id=(SELECT MAX(h2.id) FROM result_history h2 WHERE h2.task_id=h.task_id)
    """
    counts = connection.execute("SELECT COUNT(*) total,COALESCE(SUM(created_at>?),0) recent FROM (" + verified + ")",
                                (now - 300, run_id, run["source_snapshot"], now)).fetchone()
    total_seconds, uncertain = elapsed(0)
    recent_seconds, recent_uncertain = elapsed(now - 300)
    total = int(counts["total"])
    recent = int(counts["recent"])
    rate = recent * 3600 / recent_seconds if recent >= 5 and recent_seconds >= 60 and not recent_uncertain else 0.0
    average = total * 3600 / total_seconds if total >= 5 and total_seconds >= 60 and not uncertain else 0.0
    remaining = connection.execute("SELECT COUNT(*) FROM tasks t JOIN run_tasks rt ON rt.task_id=t.id "
        "WHERE rt.run_id=? AND t.status IN ('pending','running')", (run_id,)).fetchone()[0]
    # ETA is withheld for heterogeneous symbol/timeframe/period/cost workloads.
    contexts = connection.execute("SELECT COUNT(*) FROM (SELECT DISTINCT "
        "json_extract(t.payload,'$.symbol'),json_extract(t.payload,'$.timeframe'),"
        "json_extract(t.payload,'$.date_range'),json_extract(t.payload,'$.costs') "
        "FROM tasks t JOIN run_tasks rt ON rt.task_id=t.id WHERE rt.run_id=?)", (run_id,)).fetchone()[0]
    return {**empty, "tests_per_hour": rate, "average_tests_per_hour": average,
            "verified_count": total, "window_verified_count": recent,
            "active_seconds": total_seconds, "window_active_seconds": recent_seconds,
            "timing_uncertain": uncertain,
            "eta_seconds": remaining * 3600 / rate if rate and contexts == 1 else None}
