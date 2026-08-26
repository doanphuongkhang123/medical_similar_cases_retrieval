#!/usr/bin/env python3
"""Audit the server-side structured-EHR code and data namespace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PIPELINES = (
    "context_clues",
    "ehr_foundation_encoders",
    "ehr_graph_embedding",
    "HyperGraph",
)

DATA_DIRECTORIES = (
    "context_clues",
    "ehr_foundation_encoders",
    "ehr_preprocessed",
    "experiments",
    "HyperGraph",
    "preprocessed_v2",
    "processed",
    "raw",
)

LEGACY_DATA_PATHS = (
    "context_clues",
    "ehr_foundation_encoders",
    "ehr_preprocessed",
    "HyperGraph",
    "preprocessed_v2",
    "processed",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_summary(path: Path) -> dict[str, int]:
    files = 0
    directories = 0
    bytes_total = 0
    for root, directory_names, file_names in os.walk(path):
        directories += len(directory_names)
        root_path = Path(root)
        for file_name in file_names:
            file_path = root_path / file_name
            if file_path.is_symlink():
                continue
            files += 1
            bytes_total += file_path.stat().st_size
    return {
        "directories": directories,
        "files": files,
        "bytes": bytes_total,
    }


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def audit_layout(code_root: Path, data_root: Path) -> dict[str, object]:
    ehr_code_root = code_root / "ehr"
    ehr_data_root = data_root / "ehr"
    workbook = ehr_data_root / "raw" / "thông tin bệnh án.xlsx"

    missing = [
        str(ehr_code_root / pipeline)
        for pipeline in PIPELINES
        if not (ehr_code_root / pipeline).is_dir()
    ]
    missing.extend(
        str(ehr_data_root / directory)
        for directory in DATA_DIRECTORIES
        if not (ehr_data_root / directory).is_dir()
    )
    if not workbook.is_file():
        missing.append(str(workbook))

    legacy_paths = [
        data_root / directory
        for directory in LEGACY_DATA_PATHS
        if (data_root / directory).exists()
    ]
    legacy_code_paths = [
        code_root / pipeline
        for pipeline in PIPELINES
        if (code_root / pipeline).exists()
    ]
    legacy_workbook = data_root / "raw" / workbook.name
    if legacy_workbook.exists():
        legacy_paths.append(legacy_workbook)

    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_root": str(code_root.resolve()),
        "data_root": str(data_root.resolve()),
        "ehr_code_root": str(ehr_code_root.resolve()),
        "ehr_data_root": str(ehr_data_root.resolve()),
        "raw_workbook": {
            "path": str(workbook.resolve()),
            "sha256": sha256_file(workbook) if workbook.is_file() else None,
            "size_bytes": workbook.stat().st_size if workbook.is_file() else None,
        },
        "path_relocations": {
            str(data_root / "raw" / workbook.name): str(workbook),
            **{
                str(data_root / directory): str(ehr_data_root / directory)
                for directory in DATA_DIRECTORIES
                if directory != "raw"
            },
            **{
                str(code_root / pipeline): str(ehr_code_root / pipeline)
                for pipeline in PIPELINES
            },
        },
        "code": {
            pipeline: tree_summary(ehr_code_root / pipeline)
            for pipeline in PIPELINES
            if (ehr_code_root / pipeline).is_dir()
        },
        "data": {
            directory: tree_summary(ehr_data_root / directory)
            for directory in DATA_DIRECTORIES
            if (ehr_data_root / directory).is_dir()
        },
        "missing_required_paths": missing,
        "legacy_ehr_paths_still_present": [str(path) for path in legacy_paths],
        "legacy_ehr_code_paths_still_present": [
            str(path) for path in legacy_code_paths
        ],
    }
    payload["valid"] = not missing and not legacy_paths and not legacy_code_paths
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = audit_layout(args.code_root.resolve(), args.data_root.resolve())
    if args.manifest:
        write_json_atomic(args.manifest.resolve(), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if not payload["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
