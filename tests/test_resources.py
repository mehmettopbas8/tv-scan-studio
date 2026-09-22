from tv_scan_studio.resources import (
    ResourceSnapshot, benchmark_candidates, project_worker_throughput, recommend_workers,
)


def test_worker_recommendation_respects_cpu_memory_and_load():
    roomy = ResourceSnapshot(16, 32_000_000_000, 20_000_000_000, 20)
    assert recommend_workers(roomy).recommended == 8
    busy = ResourceSnapshot(16, 32_000_000_000, 20_000_000_000, 90)
    assert recommend_workers(busy).recommended == 4
    constrained = ResourceSnapshot(32, 16_000_000_000, 3_000_000_000, 10)
    assert recommend_workers(constrained).recommended == 1


def test_benchmark_uses_standard_candidate_counts():
    assert benchmark_candidates(lambda workers: workers * 100) == [
        {"workers": 2, "tests_per_hour": 200.0},
        {"workers": 4, "tests_per_hour": 400.0},
        {"workers": 8, "tests_per_hour": 800.0},
        {"workers": 16, "tests_per_hour": 1600.0},
    ]


def test_observed_duration_projects_standard_worker_throughput():
    rows = project_worker_throughput(30, 4)
    assert rows[1] == {"workers": 4, "tests_per_hour": 480.0, "within_safe_limit": True}
    assert rows[-1]["tests_per_hour"] == 480.0
    assert rows[-1]["within_safe_limit"] is False
