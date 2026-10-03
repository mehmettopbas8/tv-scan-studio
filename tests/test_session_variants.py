from pathlib import Path

import pytest

from tv_scan_studio.research import load_catalog
from tv_scan_studio.session_variants import SESSION_IDS, observed_session_variants


pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "src/tv_scan_studio/data/ftmo_session_20260923.json").is_file(),
    reason="Optional private research catalog is not bundled",
)


def test_observed_bundles_are_source_and_context_specific():
    catalog = load_catalog()
    digest = catalog["mapping_source_sha256"]
    de30 = observed_session_variants(catalog, pine_hash=digest,
                                     symbol="OANDA:DE30EUR", timeframe="15")
    nas100 = observed_session_variants(catalog, pine_hash=digest,
                                       symbol="OANDA:NAS100USD", timeframe="5")
    assert len(de30) == 4
    assert len(nas100) == 2
    assert all(set(variant) <= SESSION_IDS for variant in de30 + nas100)
    assert observed_session_variants(catalog, pine_hash="different",
                                     symbol="OANDA:DE30EUR", timeframe="15") == []
    assert observed_session_variants(catalog, pine_hash=digest,
                                     symbol="OANDA:DE30EUR", timeframe="5") == []
