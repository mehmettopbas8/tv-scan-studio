"""Regenerate the bundled catalog from the preserved 23 September evidence."""

from __future__ import annotations

import json
from pathlib import Path

from tv_scan_studio.research import build_catalog


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    catalog = build_catalog(
        root / "tmp/overnight_heavy_passes.json",
        root / "tmp/overnight_33075_final_summary.json",
        root / "tmp/overnight_heavy_final_summary.json",
        root / "5_Araclar/ICT_Uni_tv2mt5_baglantili.pine",
    )
    destination = Path(__file__).resolve().parents[1] / "src/tv_scan_studio/data/ftmo_session_20260923.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(catalog['records'])} preset -> {destination}")


if __name__ == "__main__":
    main()
