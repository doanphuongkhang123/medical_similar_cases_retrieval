"""Export canonical EHR Parquet tables as UTF-8 CSV files with checksums."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

import pandas as pd


TABLES = (
    "visits",
    "visit_ehr",
    "diagnoses",
    "medicines",
    "procedures",
    "clinical_notes",
    "observations",
    "graph_nodes",
    "graph_edges",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Xuất các bảng EHR Parquet sang CSV UTF-8.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for name in TABLES:
        source = args.input / f"{name}.parquet"
        if not source.exists():
            raise FileNotFoundError(source)
        destination = args.output / f"{name}.csv"
        frame = pd.read_parquet(source)
        frame.to_csv(
            destination,
            index=False,
            encoding="utf-8",
            quoting=csv.QUOTE_MINIMAL,
            lineterminator="\n",
        )
        records.append(
            {
                "file": destination.name,
                "rows": len(frame),
                "columns": len(frame.columns),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
                "encoding": "utf-8",
                "delimiter": ",",
                "header": True,
                "index_written": False,
            }
        )

    pd.DataFrame(records).to_csv(
        args.output / "manifest.csv",
        index=False,
        encoding="utf-8",
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    print(pd.DataFrame(records).to_string(index=False))


if __name__ == "__main__":
    main()
