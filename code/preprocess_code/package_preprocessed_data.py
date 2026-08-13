"""Package full and preview EHR exports separately and record SHA-256."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path


FULL_FILES = (
    "README.md",
    "manifest.json",
    "ehr_preprocessed.xlsx",
    "visits.parquet",
    "visit_ehr.parquet",
    "diagnoses.parquet",
    "medicines.parquet",
    "procedures.parquet",
    "clinical_notes.parquet",
    "observations.parquet",
    "graph_nodes.parquet",
    "graph_edges.parquet",
    "csv",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_paths(archive: tarfile.TarFile, source: Path, members: tuple[str, ...], root: str) -> None:
    for member in members:
        path = source / member
        if not path.exists():
            raise FileNotFoundError(path)
        archive.add(path, arcname=f"{root}/{member}", recursive=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Đóng gói riêng EHR full và preview.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--preview-dir", default="preview_100_visits")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", default="20260813")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    full_path = args.output / f"ehr_preprocessed_full_{args.tag}.tar.gz"
    preview_path = args.output / f"ehr_preprocessed_preview_100_{args.tag}.tar.gz"
    for path in (full_path, preview_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite: {path}")

    with tarfile.open(full_path, "w:gz", compresslevel=6) as archive:
        add_paths(archive, args.input, FULL_FILES, "ehr_preprocessed_full")

    preview_source = args.input / args.preview_dir
    if not preview_source.is_dir():
        raise FileNotFoundError(preview_source)
    with tarfile.open(preview_path, "w:gz", compresslevel=6) as archive:
        archive.add(preview_source, arcname="ehr_preprocessed_preview_100", recursive=True)

    records = []
    for kind, path in (("full", full_path), ("preview_100", preview_path)):
        records.append(
            {
                "kind": kind,
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(args.input.resolve()),
        "preview_directory": args.preview_dir,
        "archives": records,
    }
    (args.output / "package_manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checksum_text = "".join(
        f"{item['sha256']}  {item['file']}\n" for item in records
    )
    # Write bytes so Windows cannot translate LF to CRLF. The checksum file is
    # consumed by GNU sha256sum on the Linux execution server.
    (args.output / "SHA256SUMS.txt").write_bytes(checksum_text.encode("ascii"))
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
