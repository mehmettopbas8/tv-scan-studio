"""Independent chart preparation. A saved layout is never proof of its source."""
import time
from dataclasses import dataclass
from enum import Enum

from .pine import parse_strategy_inputs, strategy_title
from .tradingview import strategy_structure_matches
from .windows import worker_layout_candidates


class PreparationState(str, Enum):
    CLOSED = "Kapalı"
    CONNECTING = "Bağlanıyor"
    READY = "Hazır"
    ACTION_REQUIRED = "İşlem gerekli"


@dataclass(frozen=True)
class PreparationResult:
    state: PreparationState
    message: str
    next_action: str = ""
    technical_detail: str = ""
    target_id: str | None = None
    chart_id: str | None = None
    strategy: dict | None = None


def prepare_empty_layout(driver, targets, *, journal, persist, read_targets,
                         timeout=30, clock=time.monotonic, sleep=time.sleep,
                         cancelled=lambda: False):
    """Create one empty saved layout through the regular, permission-checked UI.

    Persist intent before the external write. Retries discover the previously
    requested layout instead of creating more tabs after an ambiguous timeout.
    A returned target still needs source loading, validation and user consent.
    """
    names = {target["id"]: driver.layout_name(target["id"]) for target in targets}
    if not journal:
        number = 1
        while f"TV Scan Worker {number}" in names.values():
            number += 1
        if not targets:
            return PreparationResult(PreparationState.ACTION_REQUIRED,
                "TradingView'de açık bir grafik bulunamadı.", "TradingView'de bir grafik aç")
        journal = {"name": f"TV Scan Worker {number}",
                   "before_target_ids": [target["id"] for target in targets],
                   "requested": False}
        persist(dict(journal))
    if not journal.get("name") or not isinstance(journal.get("before_target_ids"), list):
        return PreparationResult(PreparationState.ACTION_REQUIRED,
            "Önceki grafik hazırlığı kaydı doğrulanamadı.", "Hazırlık kaydını incele")
    if not journal.get("requested"):
        if cancelled():
            return PreparationResult(PreparationState.ACTION_REQUIRED, "Hazırlık durduruldu.")
        if not targets:
            return PreparationResult(PreparationState.ACTION_REQUIRED,
                "TradingView'de açık bir grafik bulunamadı.", "TradingView'de bir grafik aç")
        journal["requested"] = True
        persist(dict(journal))  # An exception after clicking must not cause a second create.
        try:
            driver.create_empty_layout(targets[0]["id"], journal["name"])
        except Exception as exc:
            return PreparationResult(PreparationState.ACTION_REQUIRED,
                "Otomatik grafik oluşturma tamamlanamadı. Açılan hazırlık penceresini kontrol edin.",
                "TradingView hazırlık rehberini aç", str(exc))
    deadline = clock() + timeout
    while True:
        if cancelled():
            return PreparationResult(PreparationState.ACTION_REQUIRED, "Hazırlık durduruldu.")
        current = read_targets()
        current_names = {target["id"]: driver.layout_name(target["id"]) for target in current}
        safe = worker_layout_candidates(current, current_names)
        created = [target for target in current if
                   # Once saved, the persistent chart identity is authoritative.
                   # CDP target IDs can be reused after a Desktop restart.
                   (journal.get("chart_id") or target["id"] not in journal["before_target_ids"]) and
                   current_names[target["id"]] == journal["name"] and target["id"] in safe and
                   (not journal.get("chart_id") or safe[target["id"]] == journal["chart_id"])]
        if len(created) == 1:
            target_id = created[0]["id"]
            journal.update(target_id=target_id, chart_id=safe[target_id])
            persist(dict(journal))
            return PreparationResult(PreparationState.ACTION_REQUIRED,
                "Bağımsız tarama grafiği kaydedildi. Strateji kaynağı henüz yüklenmedi.",
                "Strateji kaynağını yükle ve doğrula", target_id=target_id,
                chart_id=safe[target_id])
        if len(created) > 1 or clock() >= deadline:
            return PreparationResult(PreparationState.ACTION_REQUIRED,
                "Yeni grafiğin bağımsız kayıt kimliği doğrulanamadı. Yeni bir grafik daha oluşturulmadı.",
                "TradingView'deki " + journal["name"] + " grafiğini kontrol et")
        sleep(.2)


def find_prepared_chart(driver, targets, project, *, preferred_chart_id=None, excluded_targets=()):
    names = {target["id"]: driver.layout_name(target["id"]) for target in targets}
    safe = worker_layout_candidates(targets, names)
    inventory = {item["target_id"]: item for item in driver.inventory()}
    candidates = []
    for target, chart_id in safe.items():
        if target in excluded_targets:
            continue
        # A recorded identity is ownership, not a ranking hint. An unfinished
        # owned chart must be resumed rather than replaced by another matching
        # layout (which may belong to a previous run or a personal session).
        if preferred_chart_id is not None and chart_id != preferred_chart_id:
            continue
        item = inventory.get(target, {})
        strategies = item.get("strategies", [])
        # Default preparation owns one unambiguous strategy/report. A matching
        # study inside a mixed layout is not a dedicated scan chart.
        if len(strategies) != 1:
            continue
        matches = [study for study in strategies
                   if strategy_structure_matches(study, strategy_title(project["pine_source"]),
                                                 len(parse_strategy_inputs(project["pine_source"])))]
        if len(matches) == 1:
            candidates.append((target, chart_id, matches[0]))
    if candidates:
        target, chart, study = candidates[0]
        return PreparationResult(PreparationState.ACTION_REQUIRED,
            "Ayrı tarama grafiği bulundu. Kaynak doğrulaması ve kullanım onayı gerekiyor.",
            "Grafiği doğrula", target_id=target, chart_id=chart, strategy=study)
    conflicts = [names.get(t["id"], "") for t in targets
                 if names.get(t["id"], "").startswith("TV Scan Worker ") and t["id"] not in safe]
    return PreparationResult(PreparationState.ACTION_REQUIRED,
        "Bu strateji için bağımsız ve eşleşen tarama grafiği bulunamadı.",
        "TradingView hazırlık rehberini aç",
        "Çakışan grafikler: " + ", ".join(conflicts) if conflicts else
        "Mevcut grafikler korunuyor; otomatik hazırlık ayrı bir grafik oluşturup kaynağı doğrulamalı.")
