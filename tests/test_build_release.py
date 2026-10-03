from pathlib import Path

import pytest

from tools.build_release import build_release


@pytest.mark.parametrize("filename", [
    "ftmo_session_20260923.json",
    "ftmo_overnight_33075.jsonl.gz",
])
def test_release_rejects_private_research_files_before_writing(tmp_path: Path, filename: str):
    source = tmp_path / "TV-Scan-Studio"
    source.mkdir()
    (source / "TV-Scan-Studio.exe").write_bytes(b"exe")
    private = source / "_internal" / "tv_scan_studio" / "data"
    private.mkdir(parents=True)
    (private / filename).write_text("private", encoding="utf-8")
    output = tmp_path / "release"

    with pytest.raises(ValueError, match="Özel araştırma verisi"):
        build_release(source, output, "0.2.0")

    assert not output.exists()
