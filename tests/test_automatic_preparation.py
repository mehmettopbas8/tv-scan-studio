from types import SimpleNamespace

import pytest

from tv_scan_studio.preparation import prepare_empty_layout, PreparationState
from tv_scan_studio.tradingview import GncZihinDriver, SourceReadUnavailable, pine_source_hash


def target(id, chart):
    return {"id": id, "url": f"https://www.tradingview.com/chart/{chart}/"}


def test_preparation_job_reuses_private_journal_and_persists_verified_chart(tmp_path, monkeypatch):
    from tv_scan_studio import app
    from tv_scan_studio.storage import Store
    store = Store(tmp_path / "job.db")
    source = 'strategy("Example")'
    project_id = store.create_project("Example", source)
    private = {"pine_id": "USER;already-saved", "version": "1.0", "source_hash": pine_source_hash(source)}
    store.save_settings(project_id, {"private_source_preparation": private})
    before = [target("personal", "coding")]
    after = before + [target("new", "owned")]
    snapshots = iter([before, after, after, after])
    monkeypatch.setattr(app, "chart_targets", lambda: next(snapshots))
    calls = []
    def load(id, actual_source, *, journal, persist, guard):
        assert journal == private
        assert actual_source == source
        guard(id)
        persist(dict(journal, study_id="applied"))
        calls.append(id)
    driver = SimpleNamespace(
        layout_name=lambda id: "Coding" if id == "personal" else "TV Scan Worker 1",
        create_empty_layout=lambda *args: None, load_private_source=load)
    job = app.ChartPreparationJob(driver, store, {"id": project_id, "pine_source": source})
    completed = []
    job.completed.connect(completed.append)
    job.run()
    assert completed == [{"project_id": project_id, "success": True}]
    assert calls == ["new"]
    assert store.settings(project_id)["prepared_chart_id"] == "owned"
    assert store.settings(project_id)["private_source_preparation"]["study_id"] == "applied"


def test_preparation_job_cancel_does_not_create_or_load(tmp_path, monkeypatch):
    from tv_scan_studio import app
    from tv_scan_studio.storage import Store
    store = Store(tmp_path / "cancel.db")
    source = 'strategy("Example")'
    project_id = store.create_project("Example", source)
    monkeypatch.setattr(app, "chart_targets", lambda: [target("personal", "coding")])
    driver = SimpleNamespace(layout_name=lambda id: "Coding",
        create_empty_layout=lambda *args: pytest.fail("Cancelled before external write"),
        load_private_source=lambda *args, **kwargs: pytest.fail("Cancelled before source load"))
    job = app.ChartPreparationJob(driver, store, {"id": project_id, "pine_source": source})
    completed = []
    job.completed.connect(completed.append)
    job.cancelled.set()
    job.run()
    assert completed[0]["success"] is False
    assert "durduruldu" in completed[0]["error"]
    assert not store.settings(project_id).get("prepared_chart_id")


def test_preparation_job_retries_source_failure_without_creating_second_chart(tmp_path, monkeypatch):
    from tv_scan_studio import app
    from tv_scan_studio.storage import Store
    store = Store(tmp_path / "retry.db")
    source = 'strategy("Example")'
    project_id = store.create_project("Example", source)
    current = [target("personal", "coding")]
    creates, loads = [], []
    monkeypatch.setattr(app, "chart_targets", lambda: list(current))
    def create(*args):
        creates.append(args)
        current.append(target("new", "owned"))
    def load(id, actual_source, *, journal, persist, guard):
        guard(id)
        loads.append(id)
        if len(loads) == 1:
            persist({"pine_id": "USER;already-saved", "version": "1.0",
                     "source_hash": pine_source_hash(actual_source)})
            raise RuntimeError("Interrupted after private source save")
        assert journal["pine_id"] == "USER;already-saved"
    driver = SimpleNamespace(
        layout_name=lambda id: "Coding" if id == "personal" else "TV Scan Worker 1",
        create_empty_layout=create, load_private_source=load)
    completed = []
    for _ in range(2):
        job = app.ChartPreparationJob(driver, store, {"id": project_id, "pine_source": source})
        job.completed.connect(completed.append)
        job.run()
    assert completed[0]["success"] is False
    assert completed[1]["success"] is True
    assert len(creates) == 1 and loads == ["new", "new"]
    assert store.settings(project_id)["prepared_chart_id"] == "owned"


def test_create_persists_intent_before_write_and_does_not_claim_ready():
    before = [target("personal", "coding")]
    after = before + [target("new", "independent")]
    persisted, calls = [], []
    def create(id, name):
        assert persisted[-1]["requested"] is True
        calls.append((id, name))
    driver = SimpleNamespace(layout_name=lambda id: "Coding" if id == "personal" else "TV Scan Worker 1",
                             create_empty_layout=create)
    result = prepare_empty_layout(driver, before, journal={}, persist=persisted.append,
                                  read_targets=lambda: after, timeout=0)
    assert calls == [("personal", "TV Scan Worker 1")]
    assert result.target_id == "new" and result.chart_id == "independent"
    assert result.state == PreparationState.ACTION_REQUIRED and result.strategy is None
    assert persisted[-1]["chart_id"] == "independent"


def test_ambiguous_timeout_retry_never_creates_another_layout():
    calls = []
    driver = SimpleNamespace(layout_name=lambda id: "Coding", create_empty_layout=lambda *args: calls.append(args))
    journal = {"name": "TV Scan Worker 1", "before_target_ids": ["personal"], "requested": True}
    result = prepare_empty_layout(driver, [target("personal", "coding")], journal=journal,
                                  persist=lambda value: None, read_targets=lambda: [], timeout=0)
    assert not calls and result.target_id is None


def test_saved_identity_cannot_be_replaced_by_same_named_other_chart():
    driver = SimpleNamespace(layout_name=lambda id: "TV Scan Worker 1")
    journal = {"name": "TV Scan Worker 1", "before_target_ids": [], "requested": True, "chart_id": "owned"}
    result = prepare_empty_layout(driver, [], journal=journal, persist=lambda value: None,
                                  read_targets=lambda: [target("other", "different")], timeout=0)
    assert result.target_id is None


def test_saved_chart_recovers_even_when_restart_reuses_previous_target_id():
    driver = SimpleNamespace(layout_name=lambda id: "TV Scan Worker 1",
        create_empty_layout=lambda *args: pytest.fail("Saved layout must not be recreated"))
    journal = {"name": "TV Scan Worker 1", "before_target_ids": ["reused"],
               "requested": True, "chart_id": "owned"}
    persisted = []
    result = prepare_empty_layout(driver, [], journal=journal, persist=persisted.append,
        read_targets=lambda: [target("reused", "owned")], timeout=0)
    assert result.target_id == "reused" and result.chart_id == "owned"
    assert result.state == PreparationState.ACTION_REQUIRED
    assert persisted[-1]["target_id"] == "reused"


def test_unknown_chart_does_not_adopt_reused_preparation_target_id():
    driver = SimpleNamespace(layout_name=lambda id: "TV Scan Worker 1")
    journal = {"name": "TV Scan Worker 1", "before_target_ids": ["reused"],
               "requested": True}
    result = prepare_empty_layout(driver, [], journal=journal, persist=lambda value: None,
        read_targets=lambda: [target("reused", "unknown")], timeout=0)
    assert result.target_id is None


def test_duplicate_layout_is_not_adopted():
    driver = SimpleNamespace(layout_name=lambda id: "TV Scan Worker 1")
    journal = {"name": "TV Scan Worker 1", "before_target_ids": [], "requested": True}
    result = prepare_empty_layout(driver, [], journal=journal, persist=lambda value: None,
        read_targets=lambda: [target("a", "same"), target("b", "same")], timeout=0)
    assert result.target_id is None


def test_unrequested_journal_without_open_chart_does_not_mark_requested():
    journal = {"name": "TV Scan Worker 1", "before_target_ids": [], "requested": False}
    result = prepare_empty_layout(SimpleNamespace(), [], journal=journal,
                                  persist=lambda value: pytest.fail("No external intent expected"),
                                  read_targets=lambda: [], timeout=0)
    assert result.target_id is None and not journal["requested"]


def test_saved_source_reader_uses_exact_applied_build_and_async_api():
    calls = []
    source = 'strategy("Example")'
    def evaluate(target_id, expression, **kwargs):
        calls.append((target_id, expression, kwargs))
        return {"source": source, "pine_id": "USER;owned", "version": "1.0"}
    driver = GncZihinDriver()
    driver._motor = SimpleNamespace(_eval=evaluate)
    assert driver.saved_strategy_source_hash("owned-target", "study") == pine_source_hash(source)
    assert calls[0][2] == {"await_promise": True}
    assert "JSON.stringify(before)!==JSON.stringify(after)" in calls[0][1]
    assert "getSource(before.id,before.version)" in calls[0][1]


@pytest.mark.parametrize("response", [None, {}, {"source": "", "pine_id": "id", "version": "1.0"}])
def test_saved_source_unavailable_is_not_a_match(response):
    driver = GncZihinDriver()
    driver._motor = SimpleNamespace(_eval=lambda *args, **kwargs: response)
    with pytest.raises(SourceReadUnavailable):
        driver.saved_strategy_source_hash("target", "study")


def test_private_source_retry_does_not_save_again_after_ambiguous_failure():
    driver = GncZihinDriver()
    driver.strategies = lambda target: []
    def read_only(target, expression, **kwargs):
        assert "listSavedScripts" in expression
        return []
    driver._motor = SimpleNamespace(_eval=read_only)
    journal = {"source_hash": pine_source_hash("source"), "save_requested": True}
    with pytest.raises(RuntimeError, match="kopya"):
        driver.load_private_source("owned", "source", journal=journal,
            persist=lambda value: None, guard=lambda target: None)


def test_private_source_reuses_only_exact_existing_strategy():
    driver = GncZihinDriver()
    study = {"id": "owned-study", "pine_id": "USER;owned"}
    driver.strategies = lambda target: [study]
    driver.saved_strategy_source_hash = lambda *args: pine_source_hash("source")
    assert driver.load_private_source("owned", "source", journal={},
        persist=lambda value: pytest.fail("No new save"), guard=lambda target: None) == study
    driver.saved_strategy_source_hash = lambda *args: pine_source_hash("different")
    with pytest.raises(RuntimeError, match="farklı"):
        driver.load_private_source("owned", "source", journal={},
            persist=lambda value: pytest.fail("No new save"), guard=lambda target: None)


def test_private_source_persists_save_intent_even_when_network_fails():
    driver = GncZihinDriver()
    driver.strategies = lambda target: []
    def fail(*args, **kwargs):
        if "listSavedScripts" in args[1]:
            return []
        assert journal["save_requested"]
        assert saved[-1]["save_requested"]
        raise RuntimeError("network")
    driver._motor = SimpleNamespace(_eval=fail)
    journal, saved = {}, []
    with pytest.raises(RuntimeError, match="network"):
        driver.load_private_source("owned", "source", journal=journal,
            persist=saved.append, guard=lambda target: None)
    assert journal["source_hash"] == pine_source_hash("source")


def test_private_source_happy_path_persists_identity_before_attach():
    source = 'strategy("Private example")'
    driver = GncZihinDriver()
    study = {"id": "applied", "pine_id": "USER;private", "pine_version": "1.0"}
    inventories = iter([[], [], [study]])
    driver.strategies = lambda target: next(inventories)
    driver.saved_strategy_source_hash = lambda *args: pine_source_hash(source)
    journal, saved, calls, guards = {}, [], [], []
    def evaluate(target, expression, **kwargs):
        assert target == "owned" and kwargs == {"await_promise": True}
        calls.append(expression)
        if "listSavedScripts" in expression:
            return []
        if "saveNewScript" in expression:
            assert saved[-1]["save_requested"] is True
            return {"success": True, "metaInfo": {"scriptIdPart": "USER;private", "pine": {"version": "1.0"}}}
        if "getSource" in expression:
            assert saved[-1]["pine_id"] == "USER;private"
            return source
        assert "createStudy" in expression
        assert '"pineId": "USER;private"' in expression
        assert '"pineVersion": "1.0"' in expression
        return "applied"
    driver._motor = SimpleNamespace(_eval=evaluate)
    assert driver.load_private_source("owned", source, journal=journal,
        persist=saved.append, guard=guards.append) == study
    assert len(calls) == 4 and len(guards) == 5
    assert saved[-1]["study_id"] == "applied"


@pytest.mark.parametrize("response", [None, "different source"])
def test_private_source_readback_mismatch_never_attaches(response):
    driver = GncZihinDriver()
    driver.strategies = lambda target: []
    def evaluate(target, expression, **kwargs):
        assert "getSource" in expression
        assert "saveNewScript" not in expression and "createStudy" not in expression
        return response
    driver._motor = SimpleNamespace(_eval=evaluate)
    with pytest.raises(RuntimeError, match="grafiğe eklenmedi"):
        driver.load_private_source("owned", "source",
            journal={"source_hash": pine_source_hash("source"), "pine_id": "USER;private", "version": "1.0"},
            persist=lambda value: pytest.fail("No external write"), guard=lambda target: None)


@pytest.mark.parametrize("actual_id,actual_version,actual_source", [
    ("USER;other", "1.0", "source"),
    ("USER;private", "2.0", "source"),
    ("USER;private", "1.0", "other source")])
def test_private_source_wrong_applied_identity_is_not_ready(actual_id, actual_version, actual_source):
    driver = GncZihinDriver()
    study = {"id": "applied", "pine_id": actual_id, "pine_version": actual_version}
    inventories = iter([[], [], [study]])
    driver.strategies = lambda target: next(inventories)
    driver.saved_strategy_source_hash = lambda *args: pine_source_hash(actual_source)
    driver._motor = SimpleNamespace(_eval=lambda target, expression, **kwargs:
        "source" if "getSource" in expression else "applied")
    journal = {"source_hash": pine_source_hash("source"), "pine_id": "USER;private", "version": "1.0"}
    with pytest.raises(RuntimeError, match="tarama başlatılmadı"):
        driver.load_private_source("owned", "source", journal=journal,
            persist=lambda value: pytest.fail("Unverified study must not be persisted"), guard=lambda target: None)
    assert "study_id" not in journal


def test_cancel_after_private_save_retains_identity_for_safe_retry():
    driver = GncZihinDriver()
    driver.strategies = lambda target: []
    journal, saved = {}, []
    def evaluate(target, expression, **kwargs):
        if "listSavedScripts" in expression:
            return []
        assert "saveNewScript" in expression
        return {"success": True, "metaInfo": {"scriptIdPart": "USER;private", "pine": {"version": "1.0"}}}
    driver._motor = SimpleNamespace(_eval=evaluate)
    def guard(target):
        if journal.get("pine_id"):
            raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        driver.load_private_source("owned", "source", journal=journal, persist=saved.append, guard=guard)
    assert saved[-1]["pine_id"] == "USER;private"
    assert saved[-1]["version"] == "1.0"
    assert "study_id" not in journal


def test_create_exception_preserves_ambiguous_intent_and_retry_only_discovers():
    before = [target("personal", "coding")]
    persisted, creates = [], []
    def create(*args):
        creates.append(args)
        raise RuntimeError("Connection lost after click")
    driver = SimpleNamespace(layout_name=lambda id: "Coding" if id == "personal" else "TV Scan Worker 1",
        create_empty_layout=create)
    first = prepare_empty_layout(driver, before, journal={}, persist=persisted.append,
        read_targets=lambda: before, timeout=0)
    assert first.target_id is None and persisted[-1]["requested"] is True
    second = prepare_empty_layout(driver, before, journal=persisted[-1], persist=persisted.append,
        read_targets=lambda: before + [target("new", "owned")], timeout=0)
    assert second.chart_id == "owned"
    assert len(creates) == 1
