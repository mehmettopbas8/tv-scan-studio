from pathlib import Path
import hashlib
import zipfile

from tools.build_release import build_release


def test_release_version_is_the_package_version_and_hatch_source():
    import tomllib
    from tools.build_release import release_version
    from tv_scan_studio import __version__
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert release_version() == __version__
    assert "version" in project["project"]["dynamic"]
    assert "version" not in project["project"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/tv_scan_studio/__init__.py"


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


def test_release_cli_defaults_to_central_version(tmp_path):
    import subprocess
    import sys
    from tools.build_release import release_version
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "TV-Scan-Studio.exe"
    source.write_bytes(b"test-single-executable")
    output = tmp_path / "release"
    result = subprocess.run(
        [sys.executable, str(root / "tools/build_release.py"), str(source),
         "--output", str(output)], capture_output=True, text=True, check=True,
    )
    version = release_version()
    assert (output / f"TV-Scan-Studio-{version}.exe").read_bytes() == source.read_bytes()
    assert (output / f"TV-Scan-Studio-{version}-portable.zip").is_file()
    assert version in result.stdout


def test_workflow_uses_central_version_and_all_packaged_probes():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/windows-build.yml").read_text(encoding="utf-8")
    assert "tools/build_release.py --print-version" in workflow
    assert "--version 0.2.0" not in workflow
    assert "TV-Scan-Studio-0.2.0" not in workflow
    assert "refs/tags/" in workflow
    for probe in ("--helper-self-test", "--self-test", "--ui-smoke-test"):
        assert workflow.count(probe) >= 2


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


def test_packaging_launcher_is_in_tools_and_resolves_from_project_root():
    import ast
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "TVScanStudio.spec").read_text(encoding="utf-8"))
    analysis = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "Analysis")
    assert ast.literal_eval(analysis.args[0]) == ["tools/run_tv_scan_studio.py"]
    assert (root / "tools/run_tv_scan_studio.py").is_file()
    assert not (root / "run_tv_scan_studio.py").exists()
