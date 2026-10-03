from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path


PRIVATE_RESEARCH_FILES = {"ftmo_session_20260923.json", "ftmo_overnight_33075.jsonl.gz"}


def build_release(source: Path, output_dir: Path, version: str) -> tuple[Path, Path, str]:
    single_file = source.is_file()
    if single_file and source.suffix.lower() != ".exe":
        raise ValueError("Tek dosyalı dağıtım kaynağı bir EXE olmalı.")
    if not single_file and not (source / "TV-Scan-Studio.exe").is_file():
        raise FileNotFoundError(f"Portable uygulama bulunamadı: {source}")
    private_files = [path for path in source.rglob("*") if path.name in PRIVATE_RESEARCH_FILES]
    if private_files:
        raise ValueError("Özel araştırma verisi taşınabilir pakete eklenemez.")
    local_files = [path for path in source.rglob("*") if path.is_file() and (
        path.name.lower() in {".env", "studio.db-wal", "studio.db-shm"}
        or path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
        or any(part.lower() in {".git", "screenshots", "backups"}
               for part in path.relative_to(source).parts[:-1])
    )]
    if local_files:
        raise ValueError("Yerel kullanıcı verisi taşınabilir pakete eklenemez.")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_base = output_dir / f"TV-Scan-Studio-{version}-portable"
    archive = Path(f"{archive_base}.zip")
    checksum_file = Path(f"{archive}.sha256")
    archive.unlink(missing_ok=True)
    checksum_file.unlink(missing_ok=True)

    if single_file:
        executable = output_dir / f"TV-Scan-Studio-{version}.exe"
        if source.resolve() != executable.resolve():
            shutil.copy2(source, executable)
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        executable.with_suffix(".exe.sha256").write_text(
            f"{executable_hash}  {executable.name}\n", encoding="ascii")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(executable, "TV-Scan-Studio/TV-Scan-Studio.exe")
    else:
        # Historical onedir artifacts remain readable; new builds use onefile.
        shutil.make_archive(str(archive_base), "zip", root_dir=source.parent, base_dir=source.name)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum_file.write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    return archive, checksum_file, checksum


def main() -> int:
    parser = argparse.ArgumentParser(description="Taşınabilir sürüm ZIP ve SHA-256 üretir.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--version", default="0.2.0")
    args = parser.parse_args()
    archive, checksum_file, checksum = build_release(args.source, args.output, args.version)
    print(archive.resolve())
    print(checksum_file.resolve())
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
