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


def test_single_executable_release_has_no_external_runtime(tmp_path):
    source = tmp_path / "dist" / "TV-Scan-Studio.exe"
    source.parent.mkdir()
    source.write_bytes(b"single-file-test")
    (source.parent / "studio.db").write_bytes(b"never include")
    output = tmp_path / "release"
    archive, checksum_file, checksum = build_release(source, output, "9.9.9")
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.namelist() == ["TV-Scan-Studio/TV-Scan-Studio.exe"]
        assert bundle.read(bundle.namelist()[0]) == source.read_bytes()
    executable = output / "TV-Scan-Studio-9.9.9.exe"
    assert executable.read_bytes() == source.read_bytes()
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert executable.with_suffix(".exe.sha256").read_text() == f"{expected}  {executable.name}\n"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == checksum
    assert checksum_file.is_file()


def test_packaging_spec_embeds_binaries_without_collect_directory():
    import ast
    spec = Path(__file__).resolve().parents[1] / "TVScanStudio.spec"
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)]
    assert not any(node.func.id == "COLLECT" for node in calls)
    exe = next(node for node in calls if node.func.id == "EXE")
    attributes = {node.attr for node in exe.args if isinstance(node, ast.Attribute)}
    assert {"scripts", "binaries", "datas"} <= attributes
    assert not any(item.arg == "exclude_binaries" and isinstance(item.value, ast.Constant)
                   and item.value.value for item in exe.keywords)
