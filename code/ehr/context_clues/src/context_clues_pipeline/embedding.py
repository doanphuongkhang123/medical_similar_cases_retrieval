"""Tokenization audit and frozen Context Clues visit embedding inference."""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .timeline import VisitTimeline, build_visit_timelines


@dataclass(frozen=True)
class TokenizedVisit:
    ordinal: int
    patient_id: str
    visit_id: str
    cutoff_time: pd.Timestamp
    token_ids: list[int]
    n_tokens_before_truncation: int
    n_prepared_events: int
    n_tokenized_events: int
    n_numeric_fallbacks: int
    n_current_visit_tokens: int
    n_current_visit_clinical_tokens: int
    history_visit_count: int


def _event_value(value: Any) -> float | str | None:
    if value is None or value is pd.NA:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    return text or None


def _event_time(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(timestamp) else timestamp.to_pydatetime()


def tokenize_visit_timelines(
    timelines: Iterable[VisitTimeline],
    tokenizer: Any,
    event_class: Any,
    max_length: int,
    numeric_fallback_to_code: bool = True,
) -> list[TokenizedVisit]:
    """Tokenize timelines while retaining the most recent ``max_length`` tokens.

    This matches the published EHRSHOT evaluation path: no BOS/EOS tokens,
    left padding at batch time, and the last hidden state of the last clinical
    token.  A numeric value outside Stanford's learned quantile ranges can fall
    back to the corresponding code-presence token.
    """
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    results: list[TokenizedVisit] = []
    for ordinal, timeline in enumerate(timelines):
        tokens: list[str] = []
        n_fallbacks = 0
        n_current_tokens = 0
        n_current_clinical_tokens = 0
        for row in timeline.events.itertuples(index=False):
            value = _event_value(row.value)
            event = event_class(
                code=str(row.code),
                value=value,
                unit=str(row.unit) if str(row.unit) else None,
                start=_event_time(row.start),
                end=_event_time(row.end),
                omop_table=str(row.omop_table) if str(row.omop_table) else None,
            )
            token = tokenizer.convert_event_to_token(event)
            if token is None and value is not None and numeric_fallback_to_code:
                code_only = event_class(
                    code=str(row.code),
                    value=None,
                    unit=None,
                    start=event.start,
                    end=event.end,
                    omop_table=event.omop_table,
                )
                token = tokenizer.convert_event_to_token(code_only)
                if token is not None:
                    n_fallbacks += 1
            if token is None:
                continue
            tokens.append(token)
            if str(row.visit_id) == timeline.visit_id:
                n_current_tokens += 1
                if str(row.source_table) not in {"visits", "demographics"}:
                    n_current_clinical_tokens += 1

        token_ids = tokenizer.convert_tokens_to_ids(tokens)
        if isinstance(token_ids, int):
            token_ids = [token_ids]
        if not token_ids:
            raise ValueError(f"Visit {timeline.visit_id} produced zero Context Clues tokens")
        n_before = len(token_ids)
        results.append(
            TokenizedVisit(
                ordinal=ordinal,
                patient_id=timeline.patient_id,
                visit_id=timeline.visit_id,
                cutoff_time=timeline.cutoff_time,
                token_ids=list(token_ids[-max_length:]),
                n_tokens_before_truncation=n_before,
                n_prepared_events=len(timeline.events),
                n_tokenized_events=len(tokens),
                n_numeric_fallbacks=n_fallbacks,
                n_current_visit_tokens=n_current_tokens,
                n_current_visit_clinical_tokens=n_current_clinical_tokens,
                history_visit_count=timeline.history_visit_count,
            )
        )
    return results


def tokenization_audit_frame(items: list[TokenizedVisit]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "patient_id": item.patient_id,
                "visit_id": item.visit_id,
                "cutoff_time": item.cutoff_time,
                "n_prepared_events": item.n_prepared_events,
                "n_tokenized_events": item.n_tokenized_events,
                "event_tokenization_coverage": (
                    item.n_tokenized_events / item.n_prepared_events
                    if item.n_prepared_events else 0.0
                ),
                "n_numeric_fallbacks": item.n_numeric_fallbacks,
                "n_tokens_before_truncation": item.n_tokens_before_truncation,
                "n_tokens": len(item.token_ids),
                "was_truncated": item.n_tokens_before_truncation > len(item.token_ids),
                "n_current_visit_tokens": item.n_current_visit_tokens,
                "n_current_visit_clinical_tokens": item.n_current_visit_clinical_tokens,
                "history_visit_count": item.history_visit_count,
            }
            for item in sorted(items, key=lambda value: value.ordinal)
        ]
    )


def summarize_tokenization(audit: pd.DataFrame) -> dict[str, Any]:
    total_events = int(audit["n_prepared_events"].sum())
    tokenized_events = int(audit["n_tokenized_events"].sum())
    return {
        "visits": len(audit),
        "prepared_events_across_timelines": total_events,
        "tokenized_events_across_timelines": tokenized_events,
        "event_tokenization_coverage": (
            float(tokenized_events / total_events) if total_events else 0.0
        ),
        "visits_without_current_clinical_token": int(
            audit["n_current_visit_clinical_tokens"].eq(0).sum()
        ),
        "truncated_visits": int(audit["was_truncated"].sum()),
        "median_tokens": float(audit["n_tokens"].median()),
        "max_tokens": int(audit["n_tokens"].max()),
        "numeric_fallbacks": int(audit["n_numeric_fallbacks"].sum()),
    }


def _batches_by_token_budget(
    items: list[TokenizedVisit],
    batch_size: int,
    max_tokens_per_batch: int,
) -> Iterable[list[TokenizedVisit]]:
    ordered = sorted(items, key=lambda value: len(value.token_ids))
    batch: list[TokenizedVisit] = []
    max_length = 0
    for item in ordered:
        proposed_max = max(max_length, len(item.token_ids))
        proposed_size = len(batch) + 1
        if batch and (
            proposed_size > batch_size
            or proposed_max * proposed_size > max_tokens_per_batch
        ):
            yield batch
            batch = []
            max_length = 0
        batch.append(item)
        max_length = max(max_length, len(item.token_ids))
    if batch:
        yield batch


def infer_embeddings(
    items: list[TokenizedVisit],
    model: Any,
    pad_token_id: int,
    device: Any,
    batch_size: int,
    max_tokens_per_batch: int,
    l2_normalize: bool = True,
) -> np.ndarray:
    """Run a frozen causal model backbone and return vectors in visit order."""
    import torch

    if batch_size <= 0 or max_tokens_per_batch <= 0:
        raise ValueError("batch_size and max_tokens_per_batch must be positive")
    vectors: list[np.ndarray | None] = [None] * len(items)
    model.eval()
    with torch.inference_mode():
        for batch in _batches_by_token_budget(items, batch_size, max_tokens_per_batch):
            width = max(len(item.token_ids) for item in batch)
            input_ids = torch.full(
                (len(batch), width),
                fill_value=pad_token_id,
                dtype=torch.long,
                device=device,
            )
            attention_mask = torch.zeros_like(input_ids)
            for row_index, item in enumerate(batch):
                ids = torch.tensor(item.token_ids, dtype=torch.long, device=device)
                input_ids[row_index, -len(ids):] = ids
                attention_mask[row_index, -len(ids):] = 1

            outputs = model.base_model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                use_cache=False,
                return_dict=True,
            )
            hidden = outputs.last_hidden_state
            reps = hidden[:, -1, :].float()
            if l2_normalize:
                reps = torch.nn.functional.normalize(reps, p=2, dim=-1)
            batch_vectors = reps.cpu().numpy()
            if not np.isfinite(batch_vectors).all():
                raise ValueError("Model produced non-finite embedding values")
            for row_index, item in enumerate(batch):
                vectors[item.ordinal] = batch_vectors[row_index]

    if any(value is None for value in vectors):
        raise RuntimeError("Embedding inference did not return every visit")
    matrix = np.stack([value for value in vectors if value is not None]).astype(np.float32)
    return matrix


def load_prepared_timelines(
    prepared_root: Path,
    timeline_mode: str,
) -> tuple[list[VisitTimeline], dict[str, Any]]:
    events_path = prepared_root / "events.parquet"
    visits_path = prepared_root / "visits.parquet"
    manifest_path = prepared_root / "manifest.json"
    for path in (events_path, visits_path, manifest_path):
        if not path.exists():
            raise FileNotFoundError(path)
    events = pd.read_parquet(events_path)
    visits = pd.read_parquet(visits_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    timelines = build_visit_timelines(events, visits, mode=timeline_mode)  # type: ignore[arg-type]
    return timelines, manifest
