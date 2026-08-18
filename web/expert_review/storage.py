from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from retrieval import RetrievalResult, clean_id


SCHEMA = """
CREATE TABLE IF NOT EXISTS review_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_uuid TEXT NOT NULL UNIQUE,
    reviewer_id TEXT NOT NULL,
    query_visit_id TEXT NOT NULL,
    submitted_at_utc TEXT NOT NULL,
    selected_count INTEGER NOT NULL CHECK (selected_count >= 0 AND selected_count < 20),
    retrieval_top_k INTEGER NOT NULL CHECK (retrieval_top_k = 20),
    no_relevant_case INTEGER NOT NULL CHECK (no_relevant_case IN (0, 1)),
    reviewer_note TEXT NOT NULL DEFAULT '',
    retrieval_config_json TEXT NOT NULL,
    query_snapshot_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_selections (
    submission_id INTEGER NOT NULL,
    selection_order INTEGER NOT NULL,
    candidate_visit_id TEXT NOT NULL,
    retrieval_rank INTEGER NOT NULL CHECK (retrieval_rank BETWEEN 1 AND 20),
    retrieval_score REAL NOT NULL,
    PRIMARY KEY (submission_id, candidate_visit_id),
    FOREIGN KEY (submission_id) REFERENCES review_submissions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_review_query
ON review_submissions(query_visit_id, submitted_at_utc);

CREATE INDEX IF NOT EXISTS idx_review_reviewer
ON review_submissions(reviewer_id, submitted_at_utc);
"""


class ReviewStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def save_review(
        self,
        *,
        reviewer_id: str,
        query_visit_id: str,
        candidates: Sequence[RetrievalResult],
        selected_visit_ids: Sequence[str],
        no_relevant_case: bool,
        reviewer_note: str,
        retrieval_config: dict[str, Any],
        query_snapshot: dict[str, Any],
    ) -> str:
        reviewer_id = reviewer_id.strip()
        query_visit_id = clean_id(query_visit_id)
        selected = [clean_id(value) for value in selected_visit_ids]
        if not reviewer_id:
            raise ValueError("Reviewer ID is required")
        if not query_visit_id:
            raise ValueError("Query visit ID is required")
        if len(candidates) != 20:
            raise ValueError("A review submission must be based on exactly top 20")
        if len(selected) >= 20:
            raise ValueError("Ground-truth top-k must contain fewer than 20 cases")
        if len(selected) != len(set(selected)):
            raise ValueError("Duplicate selected candidate")
        if no_relevant_case and selected:
            raise ValueError("Cannot select candidates and mark no relevant case")
        if not no_relevant_case and not selected:
            raise ValueError("Select at least one case or mark no relevant case")

        candidate_map = {item.candidate_visit_id: item for item in candidates}
        unknown = [visit_id for visit_id in selected if visit_id not in candidate_map]
        if unknown:
            raise ValueError(f"Selected cases are not in the retrieved top 20: {unknown}")

        ordered = sorted(
            (candidate_map[visit_id] for visit_id in selected), key=lambda item: item.rank
        )
        review_uuid = str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO review_submissions (
                    review_uuid, reviewer_id, query_visit_id, submitted_at_utc,
                    selected_count, retrieval_top_k, no_relevant_case,
                    reviewer_note, retrieval_config_json, query_snapshot_json
                ) VALUES (?, ?, ?, ?, ?, 20, ?, ?, ?, ?)
                """,
                (
                    review_uuid,
                    reviewer_id,
                    query_visit_id,
                    submitted_at,
                    len(ordered),
                    int(no_relevant_case),
                    reviewer_note.strip(),
                    json.dumps(retrieval_config, ensure_ascii=False, sort_keys=True),
                    json.dumps(query_snapshot, ensure_ascii=False, default=str, sort_keys=True),
                ),
            )
            submission_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO review_selections (
                    submission_id, selection_order, candidate_visit_id,
                    retrieval_rank, retrieval_score
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        submission_id,
                        order,
                        item.candidate_visit_id,
                        item.rank,
                        item.score,
                    )
                    for order, item in enumerate(ordered, start=1)
                ],
            )
        return review_uuid

    def recent_reviews(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT review_uuid, reviewer_id, query_visit_id, submitted_at_utc,
                       selected_count, no_relevant_case
                FROM review_submissions
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM review_submissions"
            ).fetchone()
        return int(row["count"])
