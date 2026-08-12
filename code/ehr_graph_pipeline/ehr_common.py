"""Shared, deterministic helpers. These helpers never log clinical text."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


def normalize_name(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return " ".join(unicodedata.normalize("NFKC", str(value)).split()).strip()


def normalized_key(value: Any) -> str:
    return normalize_name(value).casefold()


def find_column(frame: pd.DataFrame, *candidates: str) -> str | None:
    wanted = {normalized_key(value) for value in candidates}
    for column in frame.columns:
        # pandas disambiguates duplicate workbook headers with '.1', '.2', ...
        if normalized_key(re.sub(r"\.\d+$", "", str(column))) in wanted:
            return str(column)
    return None


def require_column(frame: pd.DataFrame, *candidates: str) -> str:
    found = find_column(frame, *candidates)
    if found is None:
        raise ValueError(f"Required column missing; expected one of {candidates!r}")
    return found


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def row_hash(row: pd.Series, fields: Iterable[str]) -> str:
    return stable_hash({field: normalize_name(row.get(field)) for field in fields})


_COMPARISON = re.compile(r"^\s*(<=|>=|<|>)\s*(.+?)\s*$")
_NUMBER = re.compile(r"^[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?$")


def parse_lab_value(value: Any) -> dict[str, Any]:
    """Preserve unparsable values rather than converting them to zero."""
    text = normalize_name(value)
    result: dict[str, Any] = {
        "numeric_value": np.nan,
        "comparison_operator": "",
        "categorical_value": "",
        "parse_success": False,
    }
    if not text:
        return result
    match = _COMPARISON.match(text)
    if match:
        result["comparison_operator"] = match.group(1)
        text = match.group(2)
    if _NUMBER.match(text):
        result["numeric_value"] = float(text.replace(",", "."))
        result["parse_success"] = True
    else:
        result["categorical_value"] = text.casefold()
    return result


def robust_stats(values: pd.Series) -> tuple[float, float]:
    valid = pd.to_numeric(values, errors="coerce").dropna()
    if valid.empty:
        return 0.0, 1.0
    median = float(valid.median())
    iqr = float(valid.quantile(0.75) - valid.quantile(0.25))
    return median, iqr if iqr > 1e-8 else 1.0


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
