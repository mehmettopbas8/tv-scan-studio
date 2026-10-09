"""TradingView CDP adapter built on the existing gnc-zihin motor."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TradingViewError(RuntimeError):
    pass


class SourceReadUnavailable(TradingViewError):
    """No authoritative source was available, without an unsafe UI outcome."""


def chart_resolution(timeframe: str) -> str:
    """Convert user-friendly minute/hour labels to TradingView chart resolutions.

    TradingView treats ``1M`` as one month, so ``1m`` must become ``1``.
    """
    value = str(timeframe).strip()
    minute = re.fullmatch(r"(\d+)m", value)
    if minute:
        return str(int(minute.group(1)))
    hour = re.fullmatch(r"(\d+)[hH]", value)
    if hour:
        return str(int(hour.group(1)) * 60)
    return {"1D": "D", "1W": "W"}.get(value, value)


class VerificationMismatch(TradingViewError):
    def __init__(self, message: str, snapshot: "StrategySnapshot | None"):
        super().__init__(message)
        self.snapshot = snapshot


@dataclass(frozen=True, slots=True)
class StrategySnapshot:
    symbol: str
    timeframe: str
    status_type: int | None
    inputs: dict[str, Any]
    metrics: dict[str, Any] | None
    period: dict[str, Any] | None
    trades: tuple[dict[str, Any], ...] = ()
    report_source: str = "chart"
    symbol_identity: dict[str, Any] | None = None
    report_fresh: bool | None = None
    warning_state: str = "unknown"
    warning_evidence: dict[str, Any] | None = None
    report_currency: str | None = None


@dataclass(frozen=True, slots=True)
class DeepReportUiState:
    date_label: str
    metrics: dict[str, float | int]
    update_pending: bool
    total_pnl: float | None = None


@dataclass(frozen=True, slots=True)
class DeepReportModelState:
    request_from_ms: int
    request_end_exclusive_ms: int
    selected_dates: dict[str, str]
    chart_timezone: str
    strategy_id: str
    inputs: dict[str, Any]
    symbol: str
    timeframe: str
    status_type: int
    update_pending: bool
    initial_loading: bool
    settings: dict[str, Any]
    trades: tuple[dict[str, Any], ...]
    performance: dict[str, Any]
    currency: str | None
    provenance: str = "visible_deep_manager"


@dataclass(frozen=True, slots=True)
class NormalReportModelState:
    """Closed trades from the UI-bound normal report, never synthetic open exits."""

    closed_trades: tuple[dict[str, Any], ...]
    closed_count: int
    open_count: int
    open_entry_commission: float
    net_profit: float
    commission_paid: float
    currency: str
    inputs: dict[str, Any]
    provenance: str = "visible_normal_report_model"
    report_digest: str = ""


@dataclass(frozen=True, slots=True)
class StrategyPropertiesUiState:
    initial_capital: float
    position_size: float
    order_size_type: str
    commission_value: float
    commission_type: str
    slippage_ticks: int


class TradingViewDriver(Protocol):
    def targets(self) -> list[str]: ...
    def snapshot(self, target_id: str, study_id: str) -> StrategySnapshot: ...
    def configure(self, target_id: str, study_id: str, symbol: str, timeframe: str, inputs: dict[str, Any]) -> None: ...


class GncZihinDriver:
    """Thin, target-explicit wrapper; importing it never starts TradingView."""

    date_range_ready = True
    deep_capture_ready = True

    def __init__(self, motor_path: str | Path | None = None):
        self.target_guard: Callable[[str], None] | None = None
        if motor_path is None or not str(motor_path).strip():
            from . import motor_bridge
            self._motor = motor_bridge
            return
        path = Path(motor_path)
        spec = importlib.util.spec_from_file_location("tv_scan_studio_ciz_paralel", path)
        if spec is None or spec.loader is None:
            raise TradingViewError(f"Motor yüklenemedi: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._motor = module

    def targets(self) -> list[str]:
        return list(self._motor.bul_hedefler())

    def layout_name(self, target_id: str) -> str:
        """Read the active TradingView layout label without changing the chart."""
        label = self._motor._eval(target_id, r'''(()=>[...document.querySelectorAll('[aria-label]')]
          .map(x=>x.getAttribute('aria-label')||'')
          .find(x=>x.includes('Active layout:'))||'')()''')
        if not isinstance(label, str) or "Active layout:" not in label:
            return ""
        return label.split("Active layout:", 1)[1].strip().splitlines()[0]

    def create_empty_layout(self, target_id: str, name: str) -> None:
        """Use Create layout with Open in new tab; do not detach or rename a chart."""
        if not re.fullmatch(r"TV Scan Worker [1-9]\d*", name):
            raise TradingViewError("Tarama grafiği adı doğrulanamadı.")
        self._motor._eval(target_id,
            "window.TradingViewApi._saveChartService.createEmptyChart(); true")
        expression = r'''(async()=>{
          const until=Date.now()+8000;let input;
          while(Date.now()<until){
            const fields=[...document.querySelectorAll('input[placeholder="My layout"]')]
              .filter(x=>x.offsetParent!==null);
            if(fields.length===1){input=fields[0];break;}
            await new Promise(r=>setTimeout(r,100));
          }
          if(!input)throw Error('Create layout is unavailable or requires account action');
          let dialog=input;
          for(let n=0;n<12&&dialog&&!dialog.innerText.includes('Create layout');n++)dialog=dialog.parentElement;
          if(!dialog||dialog.innerText.length>3000||!dialog.innerText.includes('Create layout'))throw Error('Unexpected layout dialog');
          const check=dialog.querySelector('input[type="checkbox"]');
          if(!check)throw Error('New tab option was not found');
          if(!check.checked)check.click();
          if(!check.checked)throw Error('Open in new tab was not enabled');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,NAME);
          input.dispatchEvent(new Event('input',{bubbles:true}));
          input.dispatchEvent(new Event('change',{bubbles:true}));
          await new Promise(r=>setTimeout(r,200));
          const buttons=[...dialog.querySelectorAll('button')].filter(x=>x.innerText==='Create');
          if(buttons.length!==1||buttons[0].disabled||input.value!==NAME)throw Error('Create layout action unavailable');
          buttons[0].click();return true;
        })()'''.replace("NAME", json.dumps(name))
        if self._motor._eval(target_id, expression, await_promise=True) is not True:
            raise TradingViewError("Yeni layout isteği doğrulanamadı.")

    def _find_saved_private_source(self, target_id: str, expected: str) -> tuple[str, str] | None:
        """Reconcile an ambiguous save by exact name, version and full source.

        Never rename/overwrite scripts, and never resolve ambiguous identities by
        picking the first result. A failed catalogue read must not permit a save.
        """
        rows = self._motor._eval(target_id,
            "TradingViewApi._pineEditorApi.listSavedScripts()", await_promise=True)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise TradingViewError("Özel script listesi doğrulanamadı; yeni kayıt oluşturulmadı.")
        candidates = [row for row in rows
                      if row.get("scriptName") == "TV Scan Source " + expected[:20]]
        if not candidates:
            return None
        if len(candidates) != 1:
            raise TradingViewError("Aynı adlı birden fazla özel test scripti var; kaynak seçimi gerekli.")
        row = candidates[0]
        pine_id, version = row.get("scriptIdPart"), row.get("version")
        if not isinstance(pine_id, str) or not pine_id.startswith("USER;") or not version:
            raise TradingViewError("Kayıtlı özel test scriptinin kimliği doğrulanamadı.")
        saved = self._motor._eval(target_id,
            "TradingViewApi._pineEditorApi.getSource(" + json.dumps(pine_id) + "," +
            json.dumps(str(version)) + ")", await_promise=True)
        if (not isinstance(saved, dict) or not isinstance(saved.get("source"), str)
                or str(saved.get("version")) != str(version)
                or pine_source_hash(saved["source"]) != expected):
            raise TradingViewError("Aynı adlı özel test scriptinin kaynağı farklı veya doğrulanamadı; mevcut kayıt değiştirilmedi.")
        return pine_id, str(version)

    def load_private_source(self, target_id: str, source: str, *, journal: dict,
                            persist: Callable[[dict], None], guard: Callable[[str], None]) -> dict:
        """Save a separate private script once, then attach only to an owned chart.

        Ambiguous save failures require review rather than silently creating a
        duplicate. Existing studies and existing private scripts are not edited.
        """
        expected = pine_source_hash(source)
        guard(target_id)
        existing = self.strategies(target_id)
        if existing:
            if len(existing) == 1 and self.saved_strategy_source_hash(target_id, existing[0]["id"]) == expected:
                return existing[0]
            raise TradingViewError("Tarama grafiğinde farklı bir strateji var; mevcut kaynak değiştirilmedi.")
        if journal.get("source_hash") not in (None, expected):
            raise TradingViewError("Hazırlık kaynağı değişmiş; önceki özel script korunuyor.")
        pine_id = journal.get("pine_id")
        version = journal.get("version")
        if not pine_id:
            recovered = self._find_saved_private_source(target_id, expected)
            if recovered:
                pine_id, version = recovered
                journal.update(source_hash=expected, pine_id=pine_id, version=version)
                persist(dict(journal))
        if not pine_id:
            if journal.get("save_requested"):
                raise TradingViewError("Önceki özel script kaydı tamamlanmış olabilir. Kayıt incelenmeden yeni bir kopya oluşturulmadı.")
            journal.update(source_hash=expected, save_requested=True)
            persist(dict(journal))
            guard(target_id)
            saved = self._motor._eval(target_id,
                "TradingViewApi._pineEditorApi.saveNewScript(" + json.dumps({
                    "source": source, "name": "TV Scan Source " + expected[:20]}) + ")",
                await_promise=True)
            meta = saved.get("metaInfo", {}) if isinstance(saved, dict) else {}
            pine_id, version = meta.get("scriptIdPart"), meta.get("pine", {}).get("version")
            if not saved or not saved.get("success") or not pine_id or not version:
                raise TradingViewError("Ayrı özel script kaydedilemedi. TradingView hesabını ve derleme hatalarını kontrol edin.")
            journal.update(pine_id=pine_id, version=str(version))
            persist(dict(journal))
        guard(target_id)
        expression = r'''(async()=>{
          const saved=await TradingViewApi._pineEditorApi.getSource(PINE_ID,VERSION);
          if(typeof saved?.source!=='string'||String(saved.version)!==VERSION)return null;
          return saved.source;
        })()'''.replace("PINE_ID", json.dumps(pine_id)).replace("VERSION", json.dumps(str(version)))
        saved_source = self._motor._eval(target_id, expression, await_promise=True)
        if not isinstance(saved_source, str) or pine_source_hash(saved_source) != expected:
            raise TradingViewError("Ayrı özel script kaynağı kayıtlı stratejiyle farklı; grafiğe eklenmedi.")
        guard(target_id)
        if self.strategies(target_id):
            raise TradingViewError("Hazırlık sırasında grafik değişti; strateji eklenmedi.")
        descriptor = {"type": "pine", "pineId": pine_id, "pineVersion": str(version)}
        self._motor._eval(target_id,
            "TradingViewApi._activeChartWidgetWV.value().createStudy(" + json.dumps(descriptor) + ")",
            await_promise=True)
        guard(target_id)
        applied = self.strategies(target_id)
        if (len(applied) != 1 or applied[0].get("pine_id") != pine_id
                or str(applied[0].get("pine_version")) != str(version)
                or self.saved_strategy_source_hash(target_id, applied[0]["id"]) != expected):
            raise TradingViewError("Yüklenen stratejinin tam kaynak kimliği doğrulanamadı; tarama başlatılmadı.")
        journal["study_id"] = applied[0]["id"]
        persist(dict(journal))
        return applied[0]

    def replay_active(self, target_id: str) -> bool:
        """Read-only Replay preflight; unknown UI state must not permit chart mutation."""
        state = self._motor._eval(target_id, r"""(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          if([...document.querySelectorAll('[data-name="replay-bottom-toolbar"],'+
              '[title="Exit Bar Replay"],[title="Replay mode"]')].some(visible))return true;
          if([...document.querySelectorAll('button[aria-label="Bar replay"]')]
              .some(visible))return false;
          return null;
        })()""")
        if not isinstance(state, bool):
            raise TradingViewError("TradingView Replay durumu okunamadı; worker korunuyor.")
        return state

    def chart_timezone(self, target_id: str) -> str:
        """Read the chart timezone ID through TradingView's chart timezone API."""
        value = self._motor._eval(target_id, r"""(()=>{
          const c=TradingViewApi._activeChartWidgetWV.value();
          return c?.getTimezoneApi?.().getTimezone?.().id||null;
        })()""")
        if not isinstance(value, str) or not value.strip():
            raise TradingViewError("TradingView chart saat dilimi okunamadı.")
        return value

    def deep_report_ui_state(self, target_id: str) -> DeepReportUiState:
        """Read only the visible Deep key stats, never the chart strategy report."""
        data = self._motor._eval(target_id, r"""(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const dateButtons=[...document.querySelectorAll('button[aria-label]')]
            .filter(e=>visible(e)&&/\d{4}.+\d{4}/.test(e.getAttribute('aria-label')||''));
          const titles=[...document.querySelectorAll('*')].filter(e=>visible(e)&&
            e.children.length===0&&(e.textContent||'').trim()==='Key stats'&&
            !e.closest('[data-name="widgetbar-pages-with-tabs"]'));
          if(dateButtons.length!==1||titles.length!==1)return {error:'deep_report_not_unique'};
          const area=titles[0].parentElement;
          const stat=label=>{
            const matches=[...area.querySelectorAll('*')].filter(e=>e.children.length===0&&
              (e.textContent||'').trim()===label);
            const values=matches.map(e=>(e.parentElement?.parentElement?.textContent||'').trim());
            return values.length>0&&values.every(value=>value===values[0])?values[0]:null;
          };
          const pending=[...document.querySelectorAll('button')].some(e=>visible(e)&&
            /Update report/i.test((e.textContent||'')+' '+(e.getAttribute('aria-label')||'')));
          return {dateLabel:dateButtons[0].getAttribute('aria-label'),
            deep:/deep\s*$/i.test((dateButtons[0].textContent||'').trim()),pending,
            totalPnl:stat('Total PnL'),maxDrawdown:stat('Max drawdown'),
            profitableTrades:stat('Profitable trades'),profitFactor:stat('Profit factor'),
            grossProfit:stat('Gross profit'),grossLoss:stat('Gross loss')};
        })()""")
        if not isinstance(data, dict) or data.get("error") or not data.get("deep"):
            raise TradingViewError("Deep Strategy Report görünür ve benzersiz değil.")
        if type(data.get("pending")) is not bool or not isinstance(data.get("dateLabel"), str):
            raise TradingViewError("Deep Strategy Report güncelleme/tarih durumu okunamadı.")
        raw = [data.get(key) for key in ("totalPnl", "maxDrawdown", "profitableTrades", "profitFactor",
                                        "grossProfit", "grossLoss")]
        if not all(isinstance(value, str) and value for value in raw):
            raise TradingViewError("Deep Strategy Report temel metrikleri okunamadı.")
        def number(value: str) -> float:
            match = re.search(r"[-+−]?\d[\d,]*(?:\.\d+)?", value)
            if not match:
                raise TradingViewError("Deep Strategy Report sayı biçimi okunamadı.")
            result = float(match.group().replace("−", "-").replace(",", ""))
            if not math.isfinite(result):
                raise TradingViewError("Deep Strategy Report sayısı sonlu değil.")
            return result
        total = re.search(r"(\d+)\s*/\s*(\d+)", raw[2])
        percentages = [re.findall(r"[-+−]?\d[\d,]*(?:\.\d+)?(?=\s*%)", value)
                       for value in (raw[1], raw[2])]
        if not total or not all(percentages):
            raise TradingViewError("Deep Strategy Report işlem/DD biçimi okunamadı.")
        gross_profit, gross_loss = number(raw[4]), number(raw[5])
        if gross_profit < 0 or gross_loss < 0:
            raise TradingViewError("Deep Strategy Report brüt kâr/zarar işareti geçersiz.")
        # Key-stat Total PnL includes the open position; XLSX Net profit and
        # closed-trade analytics do not. Read closed amounts independently.
        metrics = {"net_profit": round(gross_profit - gross_loss, 8), "max_drawdown_pct": number(percentages[0][0]),
                   "win_rate_pct": number(percentages[1][0]), "trades": int(total.group(2)),
                   "profit_factor": number(raw[3].split("Profit factor", 1)[-1])}
        return DeepReportUiState(data["dateLabel"], metrics, data["pending"], number(raw[0]))

    def normal_report_model_state(self, target_id: str, study_id: str,
                                  expected_inputs: dict[str, Any]) -> NormalReportModelState:
        """Bind the visible normal report to one active study and split open trades.

        The compact chart report lacks an open-trade flag. The UI-bound report
        carries explicit ``isOpen: true`` only for synthetic open rows.
        """
        if self.target_guard is None:
            raise TradingViewError("Normal rapor modeli için worker koruması gerekli.")
        script = r'''(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const leaves=[...document.querySelectorAll('*')].filter(e=>visible(e)&&e.children.length===0&&
            (e.textContent||'').trim()==='Key stats'&&!e.closest('[data-name="widgetbar-pages-with-tabs"]'));
          if(leaves.length!==1)return {error:'normal_key_stats_not_unique'};
          const keys=Object.keys(leaves[0]).filter(k=>k.startsWith('__reactFiber$'));
          if(keys.length!==1)return {error:'normal_fiber_not_unique'};
          let fiber=leaves[0][keys[0]];const reports=new Set(),apis=new Set();
          for(let i=0;fiber&&i<30;i++,fiber=fiber.return){
            let hook=fiber.memoizedState;
            for(let j=0;hook&&j<15;j++,hook=hook.next){
              const value=hook.memoizedState;
              if(value&&typeof value==='object'&&value.settings&&value.performance&&Array.isArray(value.trades))
                reports.add(value);
            }
            const value=fiber.memoizedProps?.value||fiber.memoizedProps?.api;
            if(value&&typeof value==='object'&&'_deepBacktestingManager' in value)apis.add(value);
          }
          if(reports.size!==1||apis.size!==1)return {error:'normal_model_not_unique'};
          const report=[...reports][0],api=[...apis][0],active=api._activeStrategy?._owner?._value;
          if(api._sourceStreamKey?._value!=='strategy-facade'||api._isDeepBacktesting!==false||
             active?.id!==STUDY_ID||api._activeStrategyStatus?._owner?._value?.type!==2||
             api._reportData?._owner?._value!==report||
             api._activeStrategyReportData?._owner?._value!==report)
            return {error:'normal_report_binding_mismatch'};
          const descriptors=api._activeStrategyInputsValues?._owner?._value;
          if(!descriptors||typeof descriptors!=='object'||Array.isArray(descriptors))
            return {error:'normal_inputs_missing'};
          const inputs=Object.entries(descriptors).filter(([id])=>/^in_\d+$/.test(id))
            .map(([id,item])=>({id,value:item?.value,studyId:item?.studyId}));
          return {bound:true,inputs,first_trade_index:report.firstTradeIndex,
            trades:report.trades,performance:{net_profit:report.performance?.all?.netProfit,
              closed_count:report.performance?.all?.totalTrades,
              open_count:report.performance?.all?.totalOpenTrades,
              commission_paid:report.performance?.all?.commissionPaid},currency:report.currency};
        })()'''.replace("STUDY_ID", json.dumps(study_id))

        def read() -> NormalReportModelState:
            self.target_guard(target_id)
            data = self._motor._eval(target_id, script)
            self.target_guard(target_id)
            if not isinstance(data, dict) or data.get("bound") is not True:
                raise TradingViewError(f"Normal rapor modeli bağlanamadı: {data.get('error') if isinstance(data, dict) else 'shape'}")
            descriptors = data.get("inputs")
            if not isinstance(descriptors, list) or not descriptors:
                raise TradingViewError("Normal rapor Pine inputları eksik.")
            inputs = {}
            for item in descriptors:
                if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                        or not re.fullmatch(r"in_\d+", item["id"])
                        or item["id"] in inputs or item.get("studyId") != study_id
                        or type(item.get("value")) not in {str, bool, int, float}):
                    raise TradingViewError("Normal rapor Pine input kimliği belirsiz.")
                if type(item["value"]) is float and not math.isfinite(item["value"]):
                    raise TradingViewError("Normal rapor Pine input değeri geçersiz.")
                inputs[item["id"]] = item["value"]
            if set(inputs) != set(expected_inputs) or any(
                    inputs[key] != value or type(inputs[key]) is not type(value)
                    for key, value in expected_inputs.items()):
                raise TradingViewError("Normal rapor Pine inputları görevle eşleşmiyor.")
            performance = data.get("performance")
            trades = data.get("trades")
            if (not isinstance(performance, dict) or not isinstance(trades, list)
                    or type(data.get("first_trade_index")) is not int
                    or data["first_trade_index"] != 0):
                raise TradingViewError("Normal rapor işlem dizini doğrulanamadı.")
            closed_count, open_count = performance.get("closed_count"), performance.get("open_count")
            if (type(closed_count) is not int or type(open_count) is not int
                    or closed_count < 0 or open_count < 0
                    or len(trades) != closed_count + open_count):
                raise TradingViewError("Normal rapor açık/kapanmış işlem sayısı eşleşmiyor.")
            def finite(value: Any) -> bool:
                return type(value) in {int, float} and math.isfinite(value)
            net, paid = performance.get("net_profit"), performance.get("commission_paid")
            if not finite(net) or not finite(paid) or paid < 0:
                raise TradingViewError("Normal rapor net kâr/komisyon değeri geçersiz.")
            closed: list[dict[str, Any]] = []
            opened = 0
            numbers: set[int] = set()
            commissions = 0.0
            open_commission = 0.0
            for trade in trades:
                if not isinstance(trade, dict):
                    raise TradingViewError("Normal rapor işlem biçimi geçersiz.")
                number = trade.get("tradeNumber")
                entry, exit_ = trade.get("entry"), trade.get("exit")
                profit_data = trade.get("profit")
                if not isinstance(profit_data, dict):
                    raise TradingViewError("Normal rapor işlem kârı biçimi geçersiz.")
                profit = profit_data.get("value")
                commission = trade.get("commission")
                if (type(number) is not int or number < 1 or number in numbers
                        or not isinstance(entry, dict) or not isinstance(exit_, dict)
                        or type(entry.get("time")) is not int or type(exit_.get("time")) is not int
                        or entry["time"] > exit_["time"]
                        or not finite(profit) or not finite(commission) or commission < 0):
                    raise TradingViewError("Normal rapor işlem/komisyon kaydı geçersiz.")
                numbers.add(number)
                commissions += commission
                if trade.get("isOpen") is True:
                    opened += 1
                    open_commission += commission
                elif "isOpen" in trade:
                    raise TradingViewError("Normal rapor açık işlem işareti belirsiz.")
                else:
                    side = {"le": "long", "se": "short"}.get(entry.get("type"))
                    if side is None or exit_.get("type") != ("lx" if side == "long" else "sx"):
                        raise TradingViewError("Normal rapor kapanmış işlem yönü belirsiz.")
                    closed.append({"e": {"tm": entry["time"], "tp": side, "c": str(entry.get("id") or "")},
                                   "x": {"tm": exit_["time"]}, "tp": {"v": float(profit)}})
            if (numbers != set(range(1, len(trades) + 1)) or len(closed) != closed_count
                    or opened != open_count or abs(commissions - paid) > 0.011
                    or abs(sum(item["tp"]["v"] for item in closed) - open_commission - net) > 0.011):
                raise TradingViewError("Normal rapor işlem/komisyon toplamı uzlaşmıyor.")
            from .report_currency import report_currency_code
            currency = report_currency_code(data.get("currency"))
            if currency is None:
                raise TradingViewError("Normal rapor para birimi doğrulanamadı.")
            try:
                digest = hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False,
                                                   ensure_ascii=False).encode()).hexdigest()
            except (TypeError, ValueError) as exc:
                raise TradingViewError("Normal rapor modeli sonlu ve kararlı değil.") from exc
            return NormalReportModelState(tuple(closed), closed_count, open_count,
                                          open_commission, float(net), float(paid), currency, inputs,
                                          report_digest=digest)

        first, second = read(), read()
        if first != second:
            raise TradingViewError("Normal rapor modeli iki okumada değişti.")
        return second

    def deep_report_model_state(self, target_id: str, study_id: str) -> DeepReportModelState:
        """Read the visible Deep manager, never normal study reportData.

        The observed React hook must reference the manager's actual Deep report.
        Selected civil dates, request UTC bounds and observed market bounds stay
        distinct. No private Pine source is returned. Two guarded reads must agree.
        """
        if self.target_guard is None:
            raise TradingViewError("Deep rapor modeli için worker koruması gerekli.")
        script = r'''(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const leaves=[...document.querySelectorAll('*')].filter(e=>visible(e)&&e.children.length===0&&
            (e.textContent||'').trim()==='Key stats'&&!e.closest('[data-name="widgetbar-pages-with-tabs"]'));
          if(leaves.length!==1)return {error:'deep_key_stats_not_unique'};
          const keys=Object.keys(leaves[0]).filter(k=>k.startsWith('__reactFiber$'));
          if(keys.length!==1)return {error:'deep_fiber_not_unique'};
          let fiber=leaves[0][keys[0]],report=null;const apis=new Set(),contexts=new Set();
          for(let i=0;fiber&&i<30;i++,fiber=fiber.return){
            let hook=fiber.memoizedState;
            for(let j=0;hook&&j<15;j++,hook=hook.next){
              const value=hook.memoizedState;
              if(value&&typeof value==='object'&&value.settings&&value.performance&&Array.isArray(value.trades)){
                if(report&&report!==value)return {error:'deep_hook_report_not_unique'};report=value;
              }
            }
            const value=fiber.memoizedProps?.value||fiber.memoizedProps?.api;
            if(value&&typeof value==='object'&&'_deepBacktestingManager' in value)apis.add(value);
            if(value&&typeof value==='object'&&'isDeepHistoryMode' in value)contexts.add(value);
          }
          if(!report||apis.size!==1||contexts.size!==1)return {error:'deep_model_not_unique'};
          const api=[...apis][0],ctx=[...contexts][0],manager=api._deepBacktestingManager;
          if(api._sourceStreamKey?._value!=='deep-backtesting'||api._isDeepBacktesting!==true||
             ctx.isDeepHistoryMode!==true||manager?._reportDataDeepBacktesting?._value!==report)
            return {error:'deep_report_reference_mismatch'};
          const active=api._activeStrategy?._owner?._value;
          const values=manager._activeStrategyInputs?._owner?._value?.inputs;
          if(!values||typeof values!=='object'||Array.isArray(values))return {error:'deep_inputs_missing'};
          const inputs={};
          for(const [key,value] of Object.entries(values))if(/^in_\d+$/.test(key)){
            if(!value||typeof value!=='object'||!Object.prototype.hasOwnProperty.call(value,'v'))
              return {error:'deep_input_shape_unknown'};
            inputs[key]=value.v;
          }
          const dates=ctx.dateRange;
          if(!(dates?.from instanceof Date)||!(dates?.to instanceof Date))return {error:'deep_dates_missing'};
          const civil=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
          const resolution=manager._resolution?._owner?._value;
          const rawSymbol=manager._symbolString?._owner?._value;
          if(typeof rawSymbol!=='string'||!rawSymbol.startsWith('={'))return {error:'deep_symbol_shape_unknown'};
          let symbol;try{symbol=JSON.parse(rawSymbol.slice(1)).symbol;}catch{return {error:'deep_symbol_invalid'};}
          return {bound:true,request_from_ms:manager._fromDate,request_end_exclusive_ms:manager._toDate,
            selected_dates:{from:civil(dates.from),to:civil(dates.to)},
            chart_timezone:manager._timezone?._owner?._value,strategy_id:active?.id,inputs,symbol,
            timeframe:resolution?._kind==='minutes'?String(resolution._multiplier):null,
            status_type:manager._statusDeepBacktesting?._value?.type,
            update_pending:ctx.manualUpdatePendingRef?.current,
            initial_loading:manager._isInitialLoadingReport?._value,
            settings:report.settings,trades:report.trades,performance:report.performance,currency:report.currency};
        })()'''

        def read() -> DeepReportModelState:
            self.target_guard(target_id)
            data = self._motor._eval(target_id, script)
            self.target_guard(target_id)
            if not isinstance(data, dict) or data.get("error") or data.get("bound") is not True:
                raise TradingViewError("Bağımsız Deep rapor modeli doğrulanamadı.")
            if (data.get("strategy_id") != study_id or type(data.get("status_type")) is not int
                    or data["status_type"] != 2 or data.get("update_pending") is not False
                    or data.get("initial_loading") is not False):
                raise TradingViewError("Deep rapor stratejisi veya hazır durumu eşleşmiyor.")
            dates = data.get("selected_dates")
            try:
                if not isinstance(dates, dict) or set(dates) != {"from", "to"}:
                    raise ValueError
                start, end = (date.fromisoformat(dates[key]) for key in ("from", "to"))
                if start.isoformat() != dates["from"] or end.isoformat() != dates["to"] or start > end:
                    raise ValueError
                end_exclusive = end + timedelta(days=1)
                zone = data.get("chart_timezone")
                if not isinstance(zone, str) or not zone:
                    raise ValueError
                ZoneInfo(zone)
            except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError) as exc:
                raise TradingViewError("Deep rapor tarihi veya saat dilimi geçersiz.") from exc
            bounds = (data.get("request_from_ms"), data.get("request_end_exclusive_ms"))
            expected_bounds = tuple(int(datetime.combine(d, datetime.min.time(), timezone.utc).timestamp()*1000)
                                    for d in (start, end_exclusive))
            if any(type(v) is not int for v in bounds) or bounds != expected_bounds:
                raise TradingViewError("Deep seçili günleri gerçek istek sınırlarıyla eşleşmiyor.")
            symbol, timeframe = data.get("symbol"), data.get("timeframe")
            if (not isinstance(symbol, str) or not re.fullmatch(r"[^\s:]+:[^\s:]+", symbol)
                    or not isinstance(timeframe, str) or not re.fullmatch(r"[1-9]\d*", timeframe)):
                raise TradingViewError("Deep sembolü veya zaman dilimi doğrulanamadı.")
            inputs = data.get("inputs")
            if not isinstance(inputs, dict) or not inputs or any(
                    not isinstance(k, str) or not re.fullmatch(r"in_\d+", k)
                    or type(v) not in {str, bool, int, float}
                    or (type(v) is int and abs(v) > 2**53 - 1)
                    or (type(v) is float and not math.isfinite(v)) for k, v in inputs.items()):
                raise TradingViewError("Deep Pine ayar değerleri doğrulanamadı.")
            settings, trades, performance = (data.get(k) for k in ("settings", "trades", "performance"))
            if (not isinstance(settings, dict) or not isinstance(trades, list)
                    or not isinstance(performance, dict) or not isinstance(performance.get("all"), dict)):
                raise TradingViewError("Deep rapor verisi eksik.")
            def json_values(value: Any) -> bool:
                if value is None or type(value) in {str, bool}:
                    return True
                if type(value) is int:
                    return abs(value) <= 2**53 - 1
                if type(value) is float:
                    return math.isfinite(value)
                if isinstance(value, list):
                    return all(json_values(v) for v in value)
                if isinstance(value, dict):
                    return all(isinstance(k, str) and json_values(v) for k, v in value.items())
                return False
            if not all(json_values(v) for v in (settings, trades, performance)) or any(not isinstance(t, dict) for t in trades):
                raise TradingViewError("Deep rapor verisinin türü geçersiz.")
            ranges = settings.get("dateRange")
            observed = ranges.get("backtest", {}) if isinstance(ranges, dict) else {}
            if (not isinstance(observed, dict) or any(type(observed.get(k)) is not int for k in ("from", "to"))
                    or not bounds[0] <= observed["from"] <= observed["to"] < bounds[1]):
                raise TradingViewError("Deep gözlenen dönem seçili istek dışında veya eksik.")
            from .report_currency import report_currency_code
            currency = data.get("currency")
            if currency is not None and report_currency_code(currency) is None:
                raise TradingViewError("Deep rapor para birimi doğrulanamadı.")
            return DeepReportModelState(*bounds, dates, zone, study_id, inputs, symbol, timeframe,
                                        2, False, False, settings, tuple(trades), performance, currency)
        first, second = read(), read()
        if first != second:
            raise TradingViewError("Bağımsız Deep rapor modeli okuma sırasında değişti.")
        return second

    def strategy_properties_ui_state(self, target_id: str) -> StrategyPropertiesUiState:
        """Read visible Strategy Properties without changing or saving any value."""
        if self.target_guard is None:
            raise TradingViewError("Strategy Properties okuması için worker koruması gerekli.")
        self.target_guard(target_id)
        opened = self._motor._eval(target_id, r"""(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          if([...document.querySelectorAll('[data-name="indicator-properties-dialog"][role="dialog"]')]
              .some(visible))return {error:'properties_dialog_already_open'};
          const dates=[...document.querySelectorAll('button[aria-label]')].filter(e=>visible(e)&&
            /\d{4}.+\d{4}/.test(e.getAttribute('aria-label')||''));
          if(dates.length!==1)return {error:'strategy_report_not_unique'};
          const settings=[...document.querySelectorAll('button[aria-label="Settings"]')].filter(e=>visible(e)&&
            Math.abs(e.getBoundingClientRect().y-dates[0].getBoundingClientRect().y)<8);
          if(settings.length!==1)return {error:'report_settings_not_unique'};
          settings[0].click();return true;
        })()""")
        if opened is not True:
            raise TradingViewError(f"Strategy Properties açılamadı: {opened!r}")
        try:
            time.sleep(0.15)
            self.target_guard(target_id)
            data = self._motor._eval(target_id, r"""(()=>{
              const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              const dialogs=[...document.querySelectorAll('[data-name="indicator-properties-dialog"][role="dialog"]')]
                .filter(visible);
              if(dialogs.length!==1)return {error:'properties_dialog_not_unique'};
              const dialog=dialogs[0];
              const tabs=[...dialog.querySelectorAll('[role="tab"]')].filter(e=>visible(e)&&
                (e.textContent||'').trim()==='Properties'&&e.className.includes('selected'));
              if(tabs.length!==1)return {error:'properties_tab_not_selected'};
              const one=selector=>{const nodes=[...dialog.querySelectorAll(selector)].filter(visible);
                return nodes.length===1?nodes[0]:null;};
              const capital=one('[data-qa-id="ui-lib-Input-input initial-capital-input"]');
              const size=one('[data-qa-id="ui-lib-Input-input order-size-input"]');
              const sizeType=one('[data-qa-id="order-size-type-input"]');
              const commission=one('[data-qa-id="ui-lib-Input-input commission-input"]');
              const commissionType=one('[data-qa-id="commission-type-input"]');
              const slippage=one('[data-qa-id="ui-lib-Input-input slippage-input"]');
              if([capital,size,sizeType,commission,commissionType,slippage].some(x=>!x))
                return {error:'properties_fields_not_unique'};
              return {capital:capital.value,size:size.value,
                sizeType:(sizeType.textContent||'').trim(),commission:commission.value,
                commissionType:(commissionType.textContent||'').trim(),slippage:slippage.value};
            })()""")
        finally:
            self.target_guard(target_id)
            closed = self._motor._eval(target_id, r"""(()=>{
              const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
              const dialogs=[...document.querySelectorAll('[data-name="indicator-properties-dialog"][role="dialog"]')]
                .filter(visible);
              if(dialogs.length!==1)return {error:'properties_dialog_cannot_close'};
              const close=[...dialogs[0].querySelectorAll('button[data-qa-id="close"]')].filter(visible);
              if(close.length!==1)return {error:'properties_close_not_unique'};
              close[0].click();return true;
            })()""")
            if closed is not True:
                raise TradingViewError(f"Strategy Properties kaydetmeden kapatılamadı: {closed!r}")
            for _attempt in range(10):
                self.target_guard(target_id)
                absent = self._motor._eval(target_id, r"""(()=>{
                  const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
                  return ![...document.querySelectorAll('[data-name="indicator-properties-dialog"][role="dialog"]')]
                    .some(visible);
                })()""")
                if absent is True:
                    break
                time.sleep(0.1)
            else:
                raise TradingViewError(
                    "Strategy Properties kapatma tıklandı ancak pencerenin kaybolduğu doğrulanamadı."
                )
        if not isinstance(data, dict) or data.get("error"):
            raise TradingViewError(f"Strategy Properties okunamadı: {data!r}")
        def scalar(key: str) -> float:
            raw = data.get(key)
            if not isinstance(raw, str) or not re.fullmatch(r"\d[\d,]*(?:\.\d+)?", raw):
                raise TradingViewError(f"Strategy Properties sayı biçimi okunamadı: {key}")
            return float(raw.replace(",", ""))
        slip = scalar("slippage")
        if not slip.is_integer():
            raise TradingViewError("Strategy Properties slippage tick değeri tam sayı değil.")
        if data.get("sizeType") != "Quantity" or data.get("commissionType") not in {
            "Percent", "Cash per contract", "Cash per order", "Per contract", "Per order"
        }:
            raise TradingViewError(
                "Strategy Properties emir/komisyon türü bilinmiyor: "
                f"{data.get('sizeType')!r}, {data.get('commissionType')!r}"
            )
        return StrategyPropertiesUiState(
            initial_capital=scalar("capital"), position_size=scalar("size"),
            order_size_type="contracts", commission_value=scalar("commission"),
            commission_type={"Percent": "percent", "Cash per contract": "cash_per_contract",
                             "Cash per order": "cash_per_order",
                             "Per contract": "cash_per_contract",
                             "Per order": "cash_per_order"}[data["commissionType"]],
            slippage_ticks=int(slip),
        )

    def strategies(self, target_id: str) -> list[dict[str, Any]]:
        result = self._motor._eval(target_id, r"""(()=>{
          const c=TradingViewApi._activeChartWidgetWV.value();
          return c._chartWidget.model().dataSources()
            .filter(x=>typeof x.reportData==='function')
            .map(x=>{const iv=c.getStudyById(x.id())?.getInputValues?.()||[];
              const definitions=x.metaInfo?.()?.inputs||[];
              const scriptIds=definitions.filter(v=>/^in_\d+$/.test(v.id)&&v.groupId!=='strategy_props').map(v=>v.id);
              const scriptSet=new Set(scriptIds);
              const propertyIds=iv.map(v=>v.id).filter(id=>/^in_\d+$/.test(id)&&!scriptSet.has(id));
              return {id:x.id?.(),name:x.name?.(),status:x._status?.value?.(),
                input_ids:scriptIds,property_input_ids:propertyIds,
                pine_digest:x.metaInfo?.()?.pine?.digest||null,
                pine_version:x.metaInfo?.()?.pine?.version||null,
                pine_id:iv.find(v=>v.id==='pineId')?.value||null};});
        })()""")
        return result if isinstance(result, list) else []

    def inventory(self) -> list[dict[str, Any]]:
        """Discover target strategies concurrently so one stale target cannot serialize timeouts."""
        targets = self.targets()

        def inspect(target_id: str) -> dict[str, Any]:
            try:
                return {"target_id": target_id, "strategies": self.strategies(target_id), "error": None}
            except Exception as exc:
                return {"target_id": target_id, "strategies": [], "error": str(exc)}

        with ThreadPoolExecutor(max_workers=min(16, max(1, len(targets)))) as pool:
            return list(pool.map(inspect, targets))

    def strategy_source_hash(self, target_id: str, study_id: str) -> str:
        """Hash saved source from the target's own open Pine editor.

        Editor hooks must identify the applied study's exact Pine ID/version.
        A closed editor, partial accessibility text, or another editor's source
        is not evidence. Unsaved draft text is deliberately not used.
        """
        data = self._motor._eval(target_id, r'''(()=>{
          const c=TradingViewApi._activeChartWidgetWV.value();
          const study=c._chartWidget.model().dataSources().find(x=>x.id()===STUDY_ID);
          if(!study||typeof study.reportData!=='function')return null;
          const pineId=c.getStudyById(STUDY_ID)?.getInputValues?.()
            ?.find(v=>v.id==='pineId')?.value;
          const version=study.metaInfo?.()?.pine?.version;
          const editors=[...document.querySelectorAll('.monaco-editor')]
            .filter(e=>e.offsetWidth>0&&e.offsetHeight>0
              &&getComputedStyle(e).visibility!=='hidden');
          if(editors.length!==1||!pineId||!version)return null;
          let e=editors[0],fiber=null;
          for(let i=0;e&&i<6;i++,e=e.parentElement){
            const k=Object.keys(e).find(k=>k.startsWith('__reactFiber'));
            if(k){fiber=e[k];break;}
          }
          const matches=[];
          for(let i=0;fiber&&i<8;i++,fiber=fiber.return){
            let hook=fiber.memoizedState;
            for(let j=0;hook&&j<50;j++,hook=hook.next){
              const v=hook.memoizedState;
              if(v&&typeof v.scriptSource==='string'&&v.scriptIdPart===pineId
                &&String(v.version)===String(version))matches.push(v.scriptSource);
            }
          }
          if(!matches.length||matches.some(s=>s!==matches[0]))return null;
          return {source:matches[0],pine_id:pineId,version:String(version)};
        })()'''.replace('STUDY_ID', json.dumps(study_id)))
        if (not isinstance(data, dict) or not isinstance(data.get("source"), str)
                or not data["source"] or not data.get("pine_id") or not data.get("version")):
            raise SourceReadUnavailable("Bağlı stratejinin tam Pine kaynağı okunamadı; kaynak eşleşmesi doğrulanmadı.")
        return pine_source_hash(data["source"])

    def saved_strategy_source_hash(self, target_id: str, study_id: str) -> str:
        """Read saved source for the exact applied ID/version without opening an editor.

        Recheck the applied build after the asynchronous source request. A
        switched strategy, missing digest or ambiguous study is not evidence.
        """
        data = self._motor._eval(target_id, r'''(async()=>{
          const identity=()=>{
            const c=TradingViewApi._activeChartWidgetWV.value();
            const matches=c._chartWidget.model().dataSources().filter(x=>
              x.id()===STUDY_ID&&typeof x.reportData==='function');
            if(matches.length!==1)return null;
            const meta=matches[0].metaInfo?.();
            const id=c.getStudyById(STUDY_ID)?.getInputValues?.()
              ?.find(v=>v.id==='pineId')?.value;
            if(!id||!meta?.pine?.version||!meta.pine.digest)return null;
            return {id,version:String(meta.pine.version),digest:meta.pine.digest};
          };
          const before=identity();if(!before)return null;
          const saved=await TradingViewApi._pineEditorApi.getSource(before.id,before.version);
          const after=identity();
          if(!after||JSON.stringify(before)!==JSON.stringify(after)||
             typeof saved?.source!=='string'||String(saved.version)!==before.version)return null;
          return {source:saved.source,pine_id:before.id,version:before.version};
        })()'''.replace('STUDY_ID', json.dumps(study_id)), await_promise=True)
        if (not isinstance(data, dict) or not isinstance(data.get("source"), str)
                or not data["source"] or not data.get("pine_id") or not data.get("version")):
            raise SourceReadUnavailable("Grafikteki stratejinin kayıtlı kaynağı doğrulanamadı.")
        return pine_source_hash(data["source"])

    def ensure_strategy_source_hash(self, target_id: str, study_id: str,
                                    *, guard: Callable[[str], None]) -> str:
        """Read a bound source, temporarily opening only a closed worker editor."""
        guard(target_id)
        try:
            return self.strategy_source_hash(target_id, study_id)
        except SourceReadUnavailable:
            pass
        guard(target_id)
        opened = self._motor._eval(target_id, r'''(()=>{
          const visible=e=>e.offsetWidth>0&&e.offsetHeight>0
            &&getComputedStyle(e).visibility!=='hidden';
          if([...document.querySelectorAll('.monaco-editor,[role="dialog"],.js-dialog')]
            .some(visible))return false;
          const buttons=[...document.querySelectorAll('button[aria-label="Pine"]')]
            .filter(visible);
          if(buttons.length!==1||buttons[0].disabled)return false;
          buttons[0].click();return true;
        })()''')
        if opened is not True:
            raise SourceReadUnavailable("Pine paneli güvenle açılamadı; mevcut editör korunuyor.")
        try:
            deadline = time.monotonic() + 5
            while True:
                guard(target_id)
                try:
                    return self.strategy_source_hash(target_id, study_id)
                except SourceReadUnavailable:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.15)
        finally:
            guard(target_id)
            closed = self._motor._eval(target_id, r'''(()=>{
              const visible=e=>e.offsetWidth>0&&e.offsetHeight>0
                &&getComputedStyle(e).visibility!=='hidden';
              const editors=[...document.querySelectorAll('.monaco-editor')].filter(visible);
              if(editors.length!==1)return false;
              const panel=editors[0].closest('[role="dialog"],.js-dialog');
              if(!panel)return false;
              const buttons=[...panel.querySelectorAll('button[aria-label="Close"]')].filter(visible);
              if(buttons.length!==1)return false;
              buttons[0].click();return true;
            })()''')
            if closed is not True:
                raise TradingViewError("Kaynak paneli kapatılamadı; worker bağlanmadı, Pine panelini kontrol edin.")
            for _attempt in range(5):
                guard(target_id)
                confirmed_closed = self._motor._eval(target_id, r'''(()=>
                  ![...document.querySelectorAll('.monaco-editor')].some(e=>
                    e.offsetWidth>0&&e.offsetHeight>0&&getComputedStyle(e).visibility!=='hidden'))()''')
                if confirmed_closed is True:
                    break
                time.sleep(.1)
            else:
                raise TradingViewError("Pine panelinin kapandığı doğrulanamadı; worker bağlanmadı.")

    def _eval(self, target_id: str, study_id: str, body: str) -> Any:
        prefix = (
            "const c=TradingViewApi._activeChartWidgetWV.value(),"
            f"s=c._chartWidget.model().dataSources().find(x=>x.id?.()==={json.dumps(study_id)});"
            "if(!s)return {error:'study_missing'};"
        )
        result = self._motor._eval(target_id, "(()=>{" + prefix + body + "})()")
        if isinstance(result, dict) and result.get("error"):
            if result["error"] == "study_missing":
                raise TradingViewError(f"Strateji bulunamadı: {study_id}")
            raise TradingViewError(f"TradingView arayüzü: {result['error']}")
        return result

    def snapshot(self, target_id: str, study_id: str) -> StrategySnapshot:
        from .report_warnings import WARNING_DOM_READ, classify_warning
        from .report_currency import report_currency_code
        data = self._eval(target_id, study_id, r"""
            const r=s.reportData(),p=r?.performance,a=p?.all;
            const refresh=globalThis.__tvScanReportRefresh?.get(s.id());
            const si=c.chartModel?.()?.mainSeries?.()?.symbolInfo?.();
            const scriptIds=new Set((s.metaInfo?.()?.inputs||[])
              .filter(v=>/^in_\d+$/.test(v.id)&&v.groupId!=='strategy_props').map(v=>v.id));
            return {status:s._status?.value?.(),symbol:c.symbol(),tf:String(c.resolution()),
              symbol_identity:si?{full_name:si.full_name,pro_name:si.pro_name,name:si.name,exchange:si.exchange}:null,
              inputs:c.getStudyById(s.id()).getInputValues().filter(v=>scriptIds.has(v.id)),
              metrics:a?{trades:a.totalTrades,
                observed_open_trade_count:a.totalOpenTrades??null,
                report_first_trade_index:r?.firstTradeIndex??null,
                profit_factor:a.profitFactor,
                win_rate_pct:a.percentProfitable*100,max_drawdown_pct:p.maxStrategyDrawDownPercent*100,
                net_profit:a.netProfit,net_profit_pct:a.netProfitPercent*100}:null,
              period:r?.settings||null,trades:Array.isArray(r?.trades)?r.trades:[],
              report_currency:r?.currency??null,
              warning_observed:__WARNING_DOM_READ__,
              report_fresh:!!(refresh&&refresh.study===s&&r&&r!==refresh.before&&!s.isRestarting())};
        """.replace("__WARNING_DOM_READ__", "(()=>{" + WARNING_DOM_READ + "})()"))
        status = data.get("status") or {}
        warning = classify_warning(data.get("warning_observed"), study_id)
        return StrategySnapshot(
            symbol=str(data.get("symbol", "")), timeframe=str(data.get("tf", "")),
            status_type=status.get("type") if isinstance(status, dict) else None,
            inputs={item["id"]: item.get("value") for item in data.get("inputs", [])
                    if re.fullmatch(r"in_\d+", str(item.get("id", "")))},
            metrics=data.get("metrics"), period=data.get("period"),
            trades=tuple(data.get("trades") or ()),
            report_source="chart",
            symbol_identity=data.get("symbol_identity"),
            report_fresh=data.get("report_fresh"),
            warning_state=warning["state"], warning_evidence=warning,
            report_currency=report_currency_code(data.get("report_currency")),
        )

    def report_warning_state(self, target_id: str, study_id: str) -> dict[str, Any]:
        """Read a uniquely bound tester banner without opening/closing any UI.

        Hidden/unsupported/ambiguous panels yield unknown, never absent. A DOM
        read failure is not a strategy execution failure and does not mutate it.
        """
        from .report_warnings import WARNING_DOM_READ, classify_warning
        try:
            observed = self._eval(target_id, study_id, WARNING_DOM_READ)
        except Exception:
            observed = None
        return classify_warning(observed, study_id)

    def refresh_chart_report(self, target_id: str, study_id: str) -> None:
        """Recalculate the owned study after all inputs/properties are applied.

        Input echo and Completed status can precede the asynchronous report.
        Track the actual report object, allowing genuinely identical results
        while rejecting the old report even if it stays stable for many reads.
        """
        if self.target_guard is None:
            raise TradingViewError("Rapor yenilemesi için bağımsız grafik koruması gerekli.")
        self.target_guard(target_id)
        result = self._eval(target_id, study_id, r'''
            if(typeof s.restart!=='function'||typeof s.isRestarting!=='function')
              return {error:'report_refresh_unsupported'};
            globalThis.__tvScanReportRefresh??=new Map();
            globalThis.__tvScanReportRefresh.set(s.id(),{study:s,before:s.reportData()});
            s.restart(true);
            return true;
        ''')
        if result is not True:
            raise TradingViewError("Yeni görev için rapor yenilemesi onaylanmadı.")
        self.target_guard(target_id)

    def configure(self, target_id: str, study_id: str, symbol: str, timeframe: str, inputs: dict[str, Any]) -> None:
        values = [{"id": key, "value": value} for key, value in inputs.items()]
        if self.target_guard is not None:
            self.target_guard(target_id)
        self._eval(target_id, study_id, f"c.setSymbol({json.dumps(symbol)},{{}});return true;")
        time.sleep(1.2)
        if self.target_guard is not None:
            self.target_guard(target_id)
        self._eval(target_id, study_id, f"c.setResolution({json.dumps(chart_resolution(timeframe))},{{}});return true;")
        time.sleep(0.8)
        if self.target_guard is not None:
            self.target_guard(target_id)
        self._eval(target_id, study_id, f"c.getStudyById(s.id()).setInputValues({json.dumps(values)});return true;")

    def configure_strategy_properties(self, target_id: str, study_id: str,
                                      assumptions: dict[str, Any]) -> None:
        """Apply only dynamically identified cost fields on an isolated worker."""
        from .cost_application import strategy_property_values
        if self.target_guard is None:
            raise TradingViewError("Maliyet ayarı için worker koruması gerekli.")
        self.target_guard(target_id)
        definitions = self._eval(target_id, study_id, "return s.metaInfo().inputs;")
        if not isinstance(definitions, list):
            raise TradingViewError("Strategy Properties tanımları okunamadı.")
        values = strategy_property_values(definitions, assumptions)
        self.target_guard(target_id)
        result = self._eval(target_id, study_id,
            f"c.getStudyById(s.id()).setInputValues({json.dumps(values)});return true;")
        if result is not True:
            raise TradingViewError("Strategy Properties uygulaması onaylanmadı.")
        self.target_guard(target_id)
        observed = self._eval(target_id, study_id,
            "return c.getStudyById(s.id()).getInputValues();")
        if not isinstance(observed, list) or any(
            not any(item.get("id") == v["id"] and not isinstance(item.get("value"), bool)
                    and item.get("value") == v["value"] for item in observed) for v in values):
            raise TradingViewError("Strategy Properties değerleri uygulanmadı.")

    def configure_date_range(self, target_id: str, study_id: str,
                             requested: dict[str, Any]) -> None:
        """Apply Strategy Report dates only on a guarded worker target.

        Live two-worker date/input/timeframe/cost tests cover this adapter. Every
        task still requires a fresh exported report and independent verification.
        """
        if not hasattr(self, "_configured_report_dates"):
            self._configured_report_dates = {}
        self._configured_report_dates.pop(target_id, None)
        start, end = requested.get("from"), requested.get("to")
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except (TypeError, ValueError) as exc:
            raise TradingViewError("Geçersiz TradingView tarih aralığı.") from exc
        if start_date.isoformat() != start or end_date.isoformat() != end or start_date > end_date:
            raise TradingViewError("Geçersiz TradingView tarih aralığı.")
        if self.target_guard is None:
            raise TradingViewError("Tarih ayarı için benzersiz worker layout koruması gerekli.")
        insert_text = getattr(self._motor, "insert_text", None)
        if not callable(insert_text):
            raise TradingViewError("Gerçek CDP tarih metin girişi sürücüde bulunamadı.")

        def step(body: str, expected: Any = True) -> None:
            self.target_guard(target_id)
            observed = self._eval(target_id, study_id, body)
            if type(observed) is not type(expected) or observed != expected:
                raise TradingViewError("TradingView tarih arayüzü beklenen adımı onaylamadı.")

        step(r"""
            const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
            const triggers=[...document.querySelectorAll('button[aria-label]')]
              .filter(e=>visible(e)&&/\d{4}.+\d{4}/.test(e.getAttribute('aria-label')||''));
            if(triggers.length!==1)return {error:'strategy_report_date_trigger_missing'};
            triggers[0].click();return true;
        """)
        time.sleep(0.2)
        step(r"""
            const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
            const menus=[...document.querySelectorAll('[role="menu"]')]
              .filter(e=>visible(e)&&e.textContent?.includes('Testing period'));
            if(menus.length!==1)return {error:'testing_period_menu_missing'};
            const leaves=[...menus[0].querySelectorAll('*')]
              .filter(e=>e.children.length===0&&e.textContent?.trim()==='Custom date range');
            if(leaves.length!==1)return {error:'custom_date_range_action_missing'};
            leaves[0].click();return true;
        """)
        time.sleep(0.2)
        for index, value in enumerate((start, end)):
            step(f"""
                const dialog=document.querySelector('[data-name="custom-date-range-dialog"][role="dialog"]');
                const fields=dialog?.querySelectorAll('input[placeholder="YYYY-MM-DD"]');
                if(!fields||fields.length!==2)return {{error:'date_dialog_fields_missing'}};
                const field=fields[{index}];field.focus();field.select();
                return document.activeElement===field;
            """)
            self.target_guard(target_id)
            insert_text(target_id, value)
            step(f"""
                const dialog=document.querySelector('[data-name="custom-date-range-dialog"][role="dialog"]');
                const fields=dialog?.querySelectorAll('input[placeholder="YYYY-MM-DD"]');
                if(!fields||fields.length!==2)return {{error:'date_dialog_fields_missing'}};
                fields[{index}].blur();return fields[{index}].value;
            """, value)
            time.sleep(0.2)
        step(f"""
            const dialog=document.querySelector('[data-name="custom-date-range-dialog"][role="dialog"]');
            const fields=dialog?.querySelectorAll('input[placeholder="YYYY-MM-DD"]');
            if(!fields||fields.length!==2||fields[0].value!=={json.dumps(start)}||
               fields[1].value!=={json.dumps(end)})return {{error:'date_values_not_retained'}};
            const submit=dialog.querySelector('button[data-name="submit-button"]');
            if(!submit||submit.disabled)return {{error:'date_submit_unavailable'}};
            submit.click();return true;
        """)
        self._configured_report_dates[target_id] = (start_date, end_date)

    def refresh_deep_report(self, target_id: str) -> bool:
        """Refresh pending reports, or observe an explicitly requested automatic report.

        An idle report is allowed only after this driver successfully submitted the
        dates. This is a readiness check, not result verification: capture still
        requires a fresh XLSX matching dates, metrics, properties and changed inputs.
        """
        if self.target_guard is None:
            raise TradingViewError("Deep güncelleme için worker koruması gerekli.")
        requested = getattr(self, "_configured_report_dates", {}).pop(target_id, None)
        before = None
        for _ in range(10):
            self.target_guard(target_id)
            before = self.deep_report_ui_state(target_id)
            if before.update_pending:
                break
            time.sleep(0.5)
        if not before.update_pending:
            try:
                observed_dates = tuple(datetime.strptime(part.strip(), "%b %d, %Y").date()
                                       for part in before.date_label.split(" — "))
            except ValueError:
                observed_dates = ()
            if requested is None or observed_dates != requested:
                raise TradingViewError("Yeni görev için Update report beklemiyor; tazelik kanıtlanamaz.")
            for _ in range(3):
                self.target_guard(target_id)
                after = self.deep_report_ui_state(target_id)
                if after != before or after.update_pending:
                    raise TradingViewError("Otomatik Deep rapor henüz kararlı değil.")
                time.sleep(0.5)
            return True
        self.target_guard(target_id)
        clicked = self._motor._eval(target_id, r"""(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const buttons=[...document.querySelectorAll('button')].filter(e=>visible(e)&&
            /Update report/i.test((e.textContent||'')+' '+(e.getAttribute('aria-label')||'')));
          if(buttons.length!==1||buttons[0].disabled)return {error:'update_report_not_unique'};
          buttons[0].click();return true;
        })()""")
        if clicked is not True:
            raise TradingViewError("Update report düğmesi onaylanmadı.")
        deadline = time.monotonic() + 75
        stable = 0
        last_ready = None
        while time.monotonic() < deadline:
            self.target_guard(target_id)
            try:
                after = self.deep_report_ui_state(target_id)
            except TradingViewError:
                stable = 0
                last_ready = None
                time.sleep(0.5)
                continue
            if not after.update_pending and after.date_label == before.date_label:
                # A retained date label is not a completed calculation: key
                # stats can still change after Update report disappears.
                stable = stable + 1 if after == last_ready else 1
                last_ready = after
                if stable >= 3:
                    return True
            else:
                stable = 0
                last_ready = None
            time.sleep(0.5)
        raise TradingViewError("Deep güncelleme zamanında tamamlanmadı.")

    def download_deep_xlsx(self, target_id: str) -> bool:
        """Use the visible report-tab export menu; file identity is checked by controller."""
        if self.target_guard is None:
            raise TradingViewError("Deep indirme için worker koruması gerekli.")
        self.target_guard(target_id)
        state = self.deep_report_ui_state(target_id)
        if state.update_pending:
            raise TradingViewError("Güncellemesi bekleyen Deep rapor indirilemez.")
        self.target_guard(target_id)
        opened = self._motor._eval(target_id, r"""(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const menus=[...document.querySelectorAll('button[title="Open context menu"]')]
            .filter(visible);
          if(menus.length<1||menus.length>2)return {error:'report_menu_not_unique'};
          const first=menus[0].getBoundingClientRect();
          if(menus.some(e=>{const r=e.getBoundingClientRect();return Math.abs(r.x-first.x)>1||
            Math.abs(r.y-first.y)>1||Math.abs(r.width-first.width)>1||
            Math.abs(r.height-first.height)>1;}))return {error:'report_menus_not_overlapping'};
          menus[0].click();return true;
        })()""")
        if opened is not True:
            raise TradingViewError("Deep dışa aktarım menüsü açılamadı.")
        self.target_guard(target_id)
        clicked = self._motor._eval(target_id, r"""(()=>{
          const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
          const items=[...document.querySelectorAll('[role="menuitem"][aria-label="Download data as XLSX"]')]
            .filter(visible);
          if(items.length!==1)return {error:'xlsx_action_not_unique'};
          items[0].click();return true;
        })()""")
        if clicked is not True:
            raise TradingViewError("Deep XLSX indirme eylemi onaylanmadı.")
        return True

    def screenshot(self, target_id: str, destination: str | Path) -> str:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._motor.screenshot(target_id, str(path))
        return str(path)


def strategy_structure_matches(strategy: dict[str, Any], expected_title: str,
                               expected_input_count: int) -> bool:
    expected_ids = {f"in_{index}" for index in range(expected_input_count)}
    observed_ids = set(strategy.get("input_ids") or ())
    return str(strategy.get("name") or "").strip() == expected_title.strip() and expected_ids <= observed_ids


def pine_source_hash(source: str) -> str:
    """Normalize only editor line endings, preserving all code and whitespace."""
    canonical = source.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def confirmed_strategy_identity_matches(strategy: dict[str, Any], identity: dict[str, Any],
                                        *, pine_hash: str, expected_title: str,
                                        expected_input_count: int, expected_source: str | None = None) -> bool:
    """Require confirmed Pine identity, accepting a legacy list with TV strategy properties."""
    observed = strategy.get("input_ids")
    saved = identity.get("input_ids")
    properties = strategy.get("property_input_ids") or []
    saved_matches = observed == saved or bool(
        isinstance(observed, list) and isinstance(saved, list)
        and isinstance(properties, list) and properties
        and saved == observed + properties
    )
    automatic_evidence_valid = identity.get("source_verification") != "editor_saved_source_sha256" or bool(
        isinstance(identity.get("source_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", identity["source_sha256"])
        and identity.get("pine_digest") and identity.get("pine_version")
        and isinstance(expected_source, str)
        and identity["source_sha256"] == pine_source_hash(expected_source)
    )
    return bool(
        automatic_evidence_valid
        and strategy_structure_matches(strategy, expected_title, expected_input_count)
        and isinstance(observed, list) and isinstance(saved, list) and saved
        and all(isinstance(value, str) for value in observed)
        and len(observed) == len(set(observed))
        and saved_matches
        and identity.get("pine_id")
        and strategy.get("pine_id") == identity["pine_id"]
        and identity.get("pine_hash") == pine_hash
        and all(not identity.get(key) or strategy.get(key) == identity[key]
                for key in ("pine_digest", "pine_version"))
        and identity.get("user_source_confirmed") is True
    )


def symbol_matches(requested: str, observed: str,
                   identity: dict[str, Any] | None = None) -> bool:
    requested = requested.strip()
    observed = observed.strip()
    if ":" in requested:
        if observed == requested:
            return True
        # Resolve aliases only from the currently applied series, never by
        # stripping a provider suffix or comparing tickers across providers.
        provider, ticker = requested.split(":", 1)
        return bool(identity and identity.get("full_name") == observed
                    and identity.get("pro_name") == requested
                    and identity.get("name") == ticker
                    and identity.get("exchange") == provider
                    and observed.rsplit(":", 1)[-1] == ticker)
    return observed == requested or observed.rsplit(":", 1)[-1] == requested


def date_range_matches(expected: dict[str, Any], period: dict[str, Any] | None,
                       chart_timezone: str | None = None) -> bool:
    if not expected:
        return True
    backtest = ((period or {}).get("dateRange") or {}).get("backtest") or {}
    for key in ("from", "to"):
        exact = expected.get(f"{key}_ms")
        if exact is not None and backtest.get(key) != exact:
            return False
    for key in ("from", "to"):
        requested = expected.get(key)
        if not requested:
            continue
        observed = backtest.get(key)
        if (isinstance(observed, bool) or not isinstance(observed, (int, float))
                or not isinstance(chart_timezone, str) or not chart_timezone):
            return False
        try:
            observed_date = datetime.fromtimestamp(
                observed / 1000, ZoneInfo(chart_timezone),
            ).date().isoformat()
        except (ZoneInfoNotFoundError, OverflowError, OSError, ValueError):
            return False
        if observed_date != requested:
            return False
    return True


def wait_for_verified_result(
    driver: TradingViewDriver,
    target_id: str,
    study_id: str,
    expected: dict[str, Any],
    *,
    timeout: float = 75,
    poll_interval: float = 0.7,
    stable_reads: int = 3,
) -> StrategySnapshot:
    """Return only a stable result whose chart and inputs match the task."""
    deadline = time.monotonic() + timeout
    previous: str | None = None
    stable = 0
    last: StrategySnapshot | None = None
    while time.monotonic() < deadline:
        last = driver.snapshot(target_id, study_id)
        state = json.dumps([last.metrics, last.period, last.report_currency,
                            len(last.trades), last.trades[-1] if last.trades else None], sort_keys=True)
        requested_tf = chart_resolution(expected["timeframe"])
        requested_dates = expected.get("date_range") or {}
        zone_reader = getattr(driver, "chart_timezone", None)
        try:
            chart_zone = zone_reader(target_id) if requested_dates and callable(zone_reader) else None
        except Exception:
            chart_zone = None
        period_matches = date_range_matches(requested_dates, last.period, chart_zone)
        source_matches = not requested_dates or last.report_source == "deep_strategy_report"
        valid = (
            last.status_type == 2
            and last.metrics is not None
            and symbol_matches(expected["symbol"], last.symbol, last.symbol_identity)
            and last.timeframe == requested_tf
            and all(
                key in last.inputs and last.inputs[key] == value
                and (isinstance(last.inputs[key], bool) == isinstance(value, bool))
                for key, value in expected.get("inputs", {}).items()
            )
            and period_matches
            and source_matches
            and (not expected.get("require_fresh_report") or last.report_fresh is True)
        )
        stable = stable + 1 if valid and state == previous else (1 if valid else 0)
        previous = state
        if stable >= stable_reads:
            return last
        time.sleep(max(0.01, poll_interval))
    detail = {"symbol": last.symbol, "timeframe": last.timeframe,
              "status": last.status_type, "inputs": last.inputs,
              "report_source": last.report_source} if last else None
    raise VerificationMismatch(f"Sonuç doğrulanamadı; son durum: {detail}", last)
