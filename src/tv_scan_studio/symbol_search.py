"""Public symbol catalogue lookup, independent of chart mutation or accounts."""
import html
import re
from urllib.parse import urlencode


def search_url(query):
    query = query.strip()
    if not query or len(query) > 120:
        raise ValueError("Aramak için 1–120 karakter yazın.")
    return "https://symbol-search.tradingview.com/symbol_search/v3/?" + urlencode({
        "text": query, "hl": "1", "exchange": "", "lang": "en",
        "search_type": "", "domain": "production"})


def catalogue_results(data):
    rows = data.get("symbols", []) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("Sembol arama yanıtı okunamadı.")
    results, seen = [], set()
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        clean = lambda value: html.unescape(re.sub(r"</?em>", "", str(value or "")))
        symbol = clean(row.get("symbol"))
        exchange = clean(row.get("exchange") or row.get("prefix"))
        if not symbol or not exchange or any(c.isspace() for c in symbol + exchange):
            continue
        code = f"{exchange}:{symbol}"
        if code not in seen:
            seen.add(code)
            results.append({"code": code, "name": clean(row.get("description")) or symbol,
                            "exchange": exchange, "type": clean(row.get("type"))})
    return results
