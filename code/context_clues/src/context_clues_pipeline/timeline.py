"""Build one chronological Context Clues input timeline per target visit."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

TimelineMode = Literal["history", "visit_only"]


@dataclass(frozen=True)
class VisitTimeline:
    patient_id: str
    visit_id: str
    cutoff_time: pd.Timestamp
    events: pd.DataFrame
    history_visit_count: int


def _validate(events: pd.DataFrame, visits: pd.DataFrame) -> None:
    event_required = {
        "event_id", "patient_id", "visit_id", "code", "value", "unit",
        "start", "end", "omop_table", "event_priority",
    }
    visit_required = {"patient_id", "visit_id", "admission_time", "discharge_time"}
    if event_required - set(events.columns):
        raise ValueError(f"events missing columns: {sorted(event_required - set(events.columns))}")
    if visit_required - set(visits.columns):
        raise ValueError(f"visits missing columns: {sorted(visit_required - set(visits.columns))}")
    if visits["visit_id"].duplicated().any():
        raise ValueError("visit_id must be unique")


def build_visit_timelines(
    events: pd.DataFrame,
    visits: pd.DataFrame,
    mode: TimelineMode = "history",
) -> list[VisitTimeline]:
    """Return target timelines ordered exactly once by visit.

    ``history`` uses all events for the same patient through target discharge.
    ``visit_only`` uses demographics plus events assigned to the target visit.
    """
    if mode not in {"history", "visit_only"}:
        raise ValueError(f"Unknown timeline mode: {mode}")
    events = events.copy()
    visits = visits.copy()
    events["start"] = pd.to_datetime(events["start"], errors="coerce")
    visits["admission_time"] = pd.to_datetime(visits["admission_time"], errors="coerce")
    visits["discharge_time"] = pd.to_datetime(visits["discharge_time"], errors="coerce")
    _validate(events, visits)

    per_patient_events = {
        patient_id: group.sort_values(
            ["start", "event_priority", "event_id"], na_position="last"
        ).reset_index(drop=True)
        for patient_id, group in events.groupby("patient_id", sort=False)
    }
    per_patient_visits = {
        patient_id: group.sort_values(["admission_time", "visit_id"]).reset_index(drop=True)
        for patient_id, group in visits.groupby("patient_id", sort=False)
    }

    timelines: list[VisitTimeline] = []
    ordered_visits = visits.sort_values(["patient_id", "admission_time", "visit_id"])
    for visit in ordered_visits.itertuples(index=False):
        patient_events = per_patient_events[str(visit.patient_id)]
        cutoff = visit.discharge_time
        if pd.isna(cutoff):
            own_times = patient_events.loc[
                patient_events["visit_id"].eq(str(visit.visit_id)), "start"
            ].dropna()
            cutoff = own_times.max() if not own_times.empty else visit.admission_time
        if mode == "history":
            selected = patient_events[
                patient_events["start"].isna() | (patient_events["start"] <= cutoff)
            ].copy()
            history_count = int(
                (
                    per_patient_visits[str(visit.patient_id)]["admission_time"]
                    <= visit.admission_time
                ).sum()
            )
        else:
            selected = patient_events[
                patient_events["visit_id"].isin({"", str(visit.visit_id)})
            ].copy()
            selected = selected[selected["start"].isna() | (selected["start"] <= cutoff)]
            history_count = 1
        timelines.append(
            VisitTimeline(
                patient_id=str(visit.patient_id),
                visit_id=str(visit.visit_id),
                cutoff_time=pd.Timestamp(cutoff),
                events=selected.reset_index(drop=True),
                history_visit_count=history_count,
            )
        )
    return timelines
