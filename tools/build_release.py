from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path


def build_release(source: Path, output_dir: Path, version: str) -> tuple[Path, Path, str]:
    if not (source / "TV-Scan-Studio.exe").is_file():
        raise FileNotFoundError(f"Portable uygulama bulunamadı: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_base = output_dir / f"TV-Scan-Studio-{version}-portable"
    archive = Path(f"{archive_base}.zip")
    checksum_file = Path(f"{archive}.sha256")
    archive.unlink(missing_ok=True)
    checksum_file.unlink(missing_ok=True)

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
