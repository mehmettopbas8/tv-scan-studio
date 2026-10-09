"""Conservative read-only Strategy Tester warning classification.

Missing text is not absence evidence. This adapter currently proves only a
visible warning on a unique, explicitly study-bound English report panel.
"""
import re


WARNING_DOM_READ = r'''
    try {
    const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)&&
      getComputedStyle(e).visibility!=='hidden';
    const name=s.name?.();
    const strategies=c._chartWidget.model().dataSources().filter(x=>typeof x.reportData==='function');
    const panels=[...document.querySelectorAll('[data-study-id]')].filter(e=>
      visible(e)&&e.getAttribute('data-study-id')===String(s.id())&&
      !e.closest('[data-name="widgetbar-pages-with-tabs"]')&&
      ['strategy-tester','strategy-report'].includes(e.getAttribute('data-name')));
    if(panels.length!==1||strategies.length!==1||strategies[0]!==s)
      return {bound:false,reason:'unique_study_bound_report_unavailable'};
    const panel=panels[0];
    const leaves=[...panel.querySelectorAll('*')].filter(e=>visible(e)&&e.children.length===0);
    const titleMatches=leaves.filter(e=>(e.textContent||'').trim()===name);
    const english=leaves.some(e=>(e.textContent||'').trim()==='Key stats');
    if(typeof name!=='string'||!name.trim()||titleMatches.length!==1||!english)
      return {bound:false,reason:'report_strategy_title_or_language_unavailable'};
    const banners=[...panel.querySelectorAll('[role="alert"], [data-name="strategy-warning"],'+
      '[data-name="look-ahead-warning"]')].filter(visible);
    return {bound:true,language:'en',study_id:String(s.id()),strategy_name:name,
      texts:banners.map(e=>(e.innerText||e.textContent||'').trim())};
    } catch (_) { return {bound:false,reason:'warning_readback_unavailable'}; }
'''


def classify_warning(observed, study_id):
    unknown = {"state": "unknown", "provenance": "strategy_report_dom",
               "text": None, "reason": "warning_readback_unavailable"}
    if not isinstance(observed, dict) or observed.get("bound") is not True:
        return {**unknown, "reason": (observed.get("reason") or unknown["reason"])
                if isinstance(observed, dict) else unknown["reason"]}
    if (observed.get("study_id") != str(study_id) or observed.get("language") != "en"
            or not isinstance(observed.get("strategy_name"), str)
            or not observed["strategy_name"].strip()):
        return {**unknown, "reason": "report_binding_or_language_unverified"}
    texts = observed.get("texts")
    if not isinstance(texts, list) or not all(isinstance(text, str) for text in texts):
        return unknown
    pattern = re.compile(r"\bthis strategy may use look[ -]ahead bias\b", re.IGNORECASE)
    matches = [text for text in texts if pattern.search(text)]
    if matches:
        return {"state": "present", "provenance": "strategy_report_dom",
                "text": matches[0], "reason": "visible_lookahead_warning"}
    return {**unknown, "reason": "absence_not_authoritatively_observable"}
