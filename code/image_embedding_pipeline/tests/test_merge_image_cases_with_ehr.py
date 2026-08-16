from pathlib import Path
import sys

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from merge_image_cases_with_ehr import MATCHED_STATUS, match_study_date_to_visit


def _visit(visit_id: str, admission: str, discharge: str | None):
    return {
        "visit_id": visit_id,
        "admission_time": pd.Timestamp(admission),
        "discharge_time": pd.Timestamp(discharge) if discharge else pd.NaT,
    }


def test_matches_one_inclusive_visit_interval():
    visit_id, status = match_study_date_to_visit(
        pd.Timestamp("2024-03-02"),
        [_visit("v1", "2024-03-01 10:00", "2024-03-02 08:00")],
    )
    assert visit_id == "v1"
    assert status == MATCHED_STATUS


def test_open_discharge_is_same_day_only():
    visit_id, status = match_study_date_to_visit(
        pd.Timestamp("2024-03-02"),
        [_visit("v1", "2024-03-01 10:00", None)],
    )
    assert visit_id == ""
    assert status == "no_visit_on_study_date"


def test_rejects_overlapping_visit_intervals():
    visit_id, status = match_study_date_to_visit(
        pd.Timestamp("2024-03-02"),
        [
            _visit("v1", "2024-03-01", "2024-03-03"),
            _visit("v2", "2024-03-02", "2024-03-04"),
        ],
    )
    assert visit_id == ""
    assert status == "ambiguous_overlapping_visit_intervals"
