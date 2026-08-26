"""Clean raw EHR workbook sheets without building relational tables or graphs.

The output preserves one CSV per source worksheet.  It is intentionally a
lightweight cleaning step: normalize headers and text cells, convert explicit
missing-value literals to null, and remove only rows or columns that are
entirely null.  It does not join, split, deduplicate, infer clinical values, or
drop rows merely because one field is missing.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


MISSING_LITERALS = {"", "null", "none", "nan", "nat", "n/a", "na", "not available"}


def clean_text(value: Any) -> Any:
    """Normalize only string cells; retain all non-string values unchanged."""
    if not isinstance(value, str):
        return value
    text = " ".join(unicodedata.normalize("NFKC", value).split()).strip()
    return pd.NA if text.casefold() in MISSING_LITERALS else text


def clean_column_names(columns: pd.Index) -> tuple[list[str], dict[str, str]]:
    """Return non-empty, unique normalized column names and a rename audit."""
    used: dict[str, int] = {}
    cleaned: list[str] = []
    renamed: dict[str, str] = {}
    for position, original in enumerate(columns):
        raw = "" if pd.isna(original) else str(original)
        base = clean_text(raw)
        name = f"unnamed_column_{position + 1}" if base is pd.NA else str(base)
        count = used.get(name, 0) + 1
        used[name] = count
        unique_name = name if count == 1 else f"{name}__{count}"
        cleaned.append(unique_name)
        if raw != unique_name:
            renamed[f"{position}:{raw}"] = unique_name
    return cleaned, renamed


def safe_filename(sheet_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", sheet_name)
    ascii_name = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_name).strip("_").lower()
    return slug or "sheet"


def clean_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Clean a single worksheet while preserving its row-level schema."""
    result = frame.copy()
    result.columns, renamed_columns = clean_column_names(result.columns)
    for column in result.columns:
        if result[column].dtype == object or pd.api.types.is_string_dtype(result[column]):
            result[column] = result[column].map(clean_text)

    initial_rows, initial_columns = result.shape
    empty_columns = [column for column in result.columns if result[column].isna().all()]
    result = result.drop(columns=empty_columns)
    result = result.dropna(axis=0, how="all").reset_index(drop=True)
    return result, {
        "input_rows": int(initial_rows),
        "output_rows": int(len(result)),
        "dropped_all_null_rows": int(initial_rows - len(result)),
        "input_columns": int(initial_columns),
        "output_columns": int(len(result.columns)),
        "dropped_all_null_columns": empty_columns,
        "renamed_columns": renamed_columns,
    }


def clean_workbook(workbook: Path, output_dir: Path, sheets: list[str] | None = None) -> dict[str, Any]:
    """Write cleaned source-sheet CSVs atomically, refusing to overwrite output."""
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {output_dir}")

    available = pd.ExcelFile(workbook).sheet_names
    selected = sheets or available
    missing = sorted(set(selected) - set(available))
    if missing:
        raise ValueError(f"requested sheet(s) missing from workbook: {', '.join(missing)}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    try:
        sheet_report: dict[str, Any] = {}
        filenames: set[str] = set()
        for sheet_name in selected:
            frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=object)
            cleaned, report = clean_frame(frame)
            filename = safe_filename(sheet_name) + ".csv"
            if filename in filenames:
                raise ValueError(f"worksheet names map to duplicate output filename: {filename}")
            filenames.add(filename)
            cleaned.to_csv(temporary_dir / filename, index=False, encoding="utf-8")
            report["output_file"] = filename
            sheet_report[sheet_name] = report

        manifest = {
            "preprocessing_version": "raw_csv_clean_v1",
            "source_workbook": str(workbook),
            "policy": {
                "source_sheets_preserved": True,
                "normalized_unicode_and_whitespace": True,
                "missing_literals_to_null": sorted(MISSING_LITERALS),
                "drop_only_all_null_rows": True,
                "drop_only_all_null_columns": True,
                "partial_null_rows_preserved": True,
                "no_entity_table_split": True,
                "no_join_or_clinical_value_inference": True,
                "no_row_deduplication": True,
            },
            "sheets": sheet_report,
        }
        (temporary_dir / "cleaning_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_dir.replace(output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sheet", action="append", default=None, help="Optional exact worksheet name; repeat for several.")
    args = parser.parse_args()

    manifest = clean_workbook(args.workbook.resolve(), args.output_dir.resolve(), args.sheet)
    print(json.dumps({"output": str(args.output_dir), "sheets": manifest["sheets"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
