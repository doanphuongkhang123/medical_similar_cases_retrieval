from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from retrieval import clean_id


def _display_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        if value.hour == 0 and value.minute == 0 and value.second == 0:
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if text.endswith(" 00:00:00"):
        return text[: -len(" 00:00:00")]
    return text


class EHRRepository:
    """Read-only EHR access optimized for one query and a 20-case shortlist."""

    def __init__(self, root: Path):
        self.root = Path(root)
        visits_path = self.root / "visits.parquet"
        diagnoses_path = self.root / "diagnoses.parquet"
        self.visits = pd.read_parquet(visits_path)
        self.visits["visit_id"] = self.visits["visit_id"].map(clean_id)
        self.visits["patient_id"] = self.visits["patient_id"].map(clean_id)
        self._visit_rows = self.visits.set_index("visit_id", drop=False)

        diagnoses = pd.read_parquet(
            diagnoses_path,
            columns=[
                "visit_id",
                "diagnosis_code",
                "diagnosis_text",
                "diagnosis_type",
                "event_time",
            ],
        )
        diagnoses["visit_id"] = diagnoses["visit_id"].map(clean_id)
        diagnoses = diagnoses.drop_duplicates(
            ["visit_id", "diagnosis_code", "diagnosis_text", "diagnosis_type"]
        )
        self._diagnoses = {
            visit_id: group.reset_index(drop=True)
            for visit_id, group in diagnoses.groupby("visit_id", sort=False)
        }

    def has_visit(self, visit_id: str) -> bool:
        return clean_id(visit_id) in self._visit_rows.index

    def visit(self, visit_id: str) -> dict[str, Any]:
        visit_id = clean_id(visit_id)
        if visit_id not in self._visit_rows.index:
            raise KeyError(f"Unknown EHR visit: {visit_id}")
        row = self._visit_rows.loc[visit_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return {str(key): value for key, value in row.to_dict().items()}

    def overview(self, visit_id: str) -> dict[str, str]:
        row = self.visit(visit_id)
        fields = [
            "patient_id",
            "visit_id",
            "admission_time",
            "discharge_time",
            "department",
            "age_at_visit",
            "gender_code",
            "diagnosis_count",
            "medicine_count",
            "procedure_count",
            "observation_count",
            "note_section_count",
        ]
        return {field: _display_value(row.get(field)) for field in fields}

    def clinical_note(self, visit_id: str) -> str:
        return _display_value(self.visit(visit_id).get("clinical_note"))

    def diagnoses(self, visit_id: str) -> pd.DataFrame:
        visit_id = clean_id(visit_id)
        frame = self._diagnoses.get(visit_id)
        if frame is None:
            return pd.DataFrame(
                columns=["diagnosis_code", "diagnosis_text", "diagnosis_type", "event_time"]
            )
        return frame.drop(columns=["visit_id"], errors="ignore").copy()

    def diagnosis_summary(self, visit_id: str, limit: int = 4) -> str:
        frame = self.diagnoses(visit_id)
        if frame.empty:
            return "Chưa có chẩn đoán"
        labels: list[str] = []
        for row in frame.head(limit).to_dict(orient="records"):
            code = _display_value(row.get("diagnosis_code"))
            text = _display_value(row.get("diagnosis_text"))
            label = f"{code} — {text}" if code and text else code or text
            if label:
                labels.append(label)
        suffix = " …" if len(frame) > limit else ""
        return "; ".join(labels) + suffix

    def _filtered_table(
        self, filename: str, visit_id: str, columns: list[str], limit: int
    ) -> pd.DataFrame:
        path = self.root / filename
        frame = pd.read_parquet(
            path,
            columns=["visit_id", *columns],
            filters=[("visit_id", "==", clean_id(visit_id))],
        )
        return frame.drop(columns=["visit_id"], errors="ignore").head(limit)

    @lru_cache(maxsize=256)
    def medicines(self, visit_id: str, limit: int = 80) -> pd.DataFrame:
        frame = self._filtered_table(
            "medicines.parquet",
            visit_id,
            [
                "drug_name",
                "active_ingredient",
                "route",
                "unit",
                "days",
                "instructions",
                "status",
            ],
            limit * 2,
        )
        return frame.drop_duplicates(
            ["drug_name", "active_ingredient", "route", "instructions"]
        ).head(limit)

    @lru_cache(maxsize=256)
    def procedures(self, visit_id: str, limit: int = 80) -> pd.DataFrame:
        frame = self._filtered_table(
            "procedures.parquet",
            visit_id,
            [
                "procedure_name",
                "performed_name",
                "procedure_class",
                "status",
                "ordered_time",
                "result",
            ],
            limit * 2,
        )
        return frame.drop_duplicates(
            ["procedure_name", "performed_name", "status", "result"]
        ).head(limit)

    @lru_cache(maxsize=256)
    def observations(self, visit_id: str, limit: int = 80) -> pd.DataFrame:
        frame = self._filtered_table(
            "observations.parquet",
            visit_id,
            [
                "observation_name",
                "result_text",
                "result_numeric",
                "unit",
                "reference_range",
                "observed_time",
            ],
            limit,
        )
        return frame
