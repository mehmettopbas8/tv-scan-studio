"""Opt-in, source-matched session bundles from preserved research evidence."""

from __future__ import annotations

import json
from typing import Any


SESSION_IDS = frozenset({"in_49", "in_50", "in_58", "in_62", "in_66",
                         "in_72", "in_76", "in_80", "in_84", "in_88"}
                        | {f"in_{index}" for index in range(95, 110)})


def observed_session_variants(catalog: dict[str, Any], *, pine_hash: str,
                              symbol: str, timeframe: str) -> list[dict[str, Any]]:
    """Do not transfer input IDs across changed Pine sources or test contexts."""
    if pine_hash != catalog.get("mapping_source_sha256"):
        return []
    seen = set()
    variants = []
    for record in catalog["records"]:
        if record["symbol"] != symbol or str(record["chart_tf"]) != str(timeframe):
            continue
        variant = {key: value for key, value in record["params"].items() if key in SESSION_IDS}
        marker = json.dumps(variant, sort_keys=True)
        if variant and marker not in seen:
            seen.add(marker)
            variants.append(variant)
    return variants
