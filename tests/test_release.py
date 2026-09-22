from pathlib import Path
import hashlib
import zipfile

from tools.build_release import build_release


def test_build_release_creates_verifiable_portable_zip(tmp_path: Path):
    source = tmp_path / "dist" / "TV-Scan-Studio"
    source.mkdir(parents=True)
    (source / "TV-Scan-Studio.exe").write_bytes(b"portable-test")
    (source / "runtime.dll").write_bytes(b"runtime")

    archive, checksum_file, checksum = build_release(source, tmp_path / "output", "9.9.9")

    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum
    assert checksum_file.read_text(encoding="ascii") == f"{checksum}  {archive.name}\n"
    with zipfile.ZipFile(archive) as bundle:
        assert "TV-Scan-Studio/TV-Scan-Studio.exe" in bundle.namelist()
