"""TradingView CDP adapter built on the existing gnc-zihin motor."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
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


@dataclass(frozen=True, slots=True)
class DeepReportUiState:
    date_label: str
    metrics: dict[str, float | int]
    update_pending: bool


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
            profitableTrades:stat('Profitable trades'),profitFactor:stat('Profit factor')};
        })()""")
        if not isinstance(data, dict) or data.get("error") or not data.get("deep"):
            raise TradingViewError("Deep Strategy Report görünür ve benzersiz değil.")
        if type(data.get("pending")) is not bool or not isinstance(data.get("dateLabel"), str):
            raise TradingViewError("Deep Strategy Report güncelleme/tarih durumu okunamadı.")
        raw = [data.get(key) for key in ("totalPnl", "maxDrawdown", "profitableTrades", "profitFactor")]
        if not all(isinstance(value, str) and value for value in raw):
            raise TradingViewError("Deep Strategy Report temel metrikleri okunamadı.")
        def number(value: str) -> float:
            match = re.search(r"[-+−]?\d[\d,]*(?:\.\d+)?", value)
            if not match:
                raise TradingViewError("Deep Strategy Report sayı biçimi okunamadı.")
            return float(match.group().replace("−", "-").replace(",", ""))
        total = re.search(r"(\d+)\s*/\s*(\d+)", raw[2])
        percentages = [re.findall(r"[-+−]?\d[\d,]*(?:\.\d+)?(?=\s*%)", value)
                       for value in (raw[1], raw[2])]
        if not total or not all(percentages):
            raise TradingViewError("Deep Strategy Report işlem/DD biçimi okunamadı.")
        metrics = {"net_profit": number(raw[0]), "max_drawdown_pct": number(percentages[0][0]),
                   "win_rate_pct": number(percentages[1][0]), "trades": int(total.group(2)),
                   "profit_factor": number(raw[3].split("Profit factor", 1)[-1])}
        return DeepReportUiState(data["dateLabel"], metrics, data["pending"])

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
                raise TradingViewError("Strategy Properties kaydetmeden kapatılamadı.")
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
        data = self._eval(target_id, study_id, r"""
            const r=s.reportData(),p=r?.performance,a=p?.all;
            const refresh=globalThis.__tvScanReportRefresh?.get(s.id());
            const si=c.chartModel?.()?.mainSeries?.()?.symbolInfo?.();
            const scriptIds=new Set((s.metaInfo?.()?.inputs||[])
              .filter(v=>/^in_\d+$/.test(v.id)&&v.groupId!=='strategy_props').map(v=>v.id));
            return {status:s._status?.value?.(),symbol:c.symbol(),tf:String(c.resolution()),
              symbol_identity:si?{full_name:si.full_name,pro_name:si.pro_name,name:si.name,exchange:si.exchange}:null,
              inputs:c.getStudyById(s.id()).getInputValues().filter(v=>scriptIds.has(v.id)),
              metrics:a?{trades:a.totalTrades,profit_factor:a.profitFactor,
                win_rate_pct:a.percentProfitable*100,max_drawdown_pct:p.maxStrategyDrawDownPercent*100,
                net_profit:a.netProfit,net_profit_pct:a.netProfitPercent*100}:null,
              period:r?.settings||null,trades:Array.isArray(r?.trades)?r.trades:[],
              report_fresh:!!(refresh&&refresh.study===s&&r&&r!==refresh.before&&!s.isRestarting())};
        """)
        status = data.get("status") or {}
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
        )

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
        while time.monotonic() < deadline:
            self.target_guard(target_id)
            try:
                after = self.deep_report_ui_state(target_id)
            except TradingViewError:
                stable = 0
                time.sleep(0.5)
                continue
            if not after.update_pending and after.date_label == before.date_label:
                stable += 1
                if stable >= 3:
                    return True
            else:
                stable = 0
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
        state = json.dumps([last.metrics, last.period, len(last.trades), last.trades[-1] if last.trades else None], sort_keys=True)
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
