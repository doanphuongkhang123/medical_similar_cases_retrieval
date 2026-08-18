from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))

from retrieval import FusedRetrievalIndex, RetrievalResult  # noqa: E402
from storage import ReviewStore  # noqa: E402


class RetrievalAndStorageTest(unittest.TestCase):
    def test_full_fusion_and_exact_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ehr_path = root / "ehr.parquet"
            text_path = root / "text.csv"
            pd.DataFrame(
                {
                    "visit_id": ["v1", "v2", "v3"],
                    "embedding": [
                        np.asarray([1.0, 0.0], dtype=np.float32),
                        np.asarray([0.9, 0.1], dtype=np.float32),
                        np.asarray([-1.0, 0.0], dtype=np.float32),
                    ],
                }
            ).to_parquet(ehr_path, index=False)
            pd.DataFrame(
                {
                    "visit_id": ["v1", "v2", "v3"],
                    "embedding_0000": [1.0, 0.9, -1.0],
                    "embedding_0001": [0.0, 0.1, 0.0],
                }
            ).to_csv(text_path, index=False)
            index = FusedRetrievalIndex.from_files(ehr_path, text_path)
            results = index.retrieve("v1", k=2)
        self.assertEqual([item.candidate_visit_id for item in results], ["v2", "v3"])
        self.assertEqual(index.config["visit_count"], 3)
        self.assertEqual(index.config["fused_dimension"], 4)

    def test_review_is_append_only_and_preserves_rank(self) -> None:
        candidates = [
            RetrievalResult(rank=rank, candidate_visit_id=f"v{rank}", score=1 - rank / 100)
            for rank in range(1, 21)
        ]
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reviews.sqlite3"
            store = ReviewStore(database_path)
            review_uuid = store.save_review(
                reviewer_id="expert-1",
                query_visit_id="query",
                candidates=candidates,
                selected_visit_ids=["v5", "v2"],
                no_relevant_case=False,
                reviewer_note="relevant",
                retrieval_config={"algorithm": "exact_cosine"},
                query_snapshot={"visit_id": "query"},
            )
            store.save_review(
                reviewer_id="expert-1",
                query_visit_id="query",
                candidates=candidates,
                selected_visit_ids=[],
                no_relevant_case=True,
                reviewer_note="second opinion",
                retrieval_config={"algorithm": "exact_cosine"},
                query_snapshot={"visit_id": "query"},
            )
            self.assertEqual(store.count(), 2)
            with store._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT candidate_visit_id, retrieval_rank, selection_order
                    FROM review_selections s
                    JOIN review_submissions r ON r.id = s.submission_id
                    WHERE r.review_uuid = ?
                    ORDER BY selection_order
                    """,
                    (review_uuid,),
                ).fetchall()
        self.assertEqual(
            [tuple(row) for row in rows],
            [("v2", 2, 1), ("v5", 5, 2)],
        )

    def test_twenty_selected_cases_are_rejected(self) -> None:
        candidates = [
            RetrievalResult(rank=rank, candidate_visit_id=f"v{rank}", score=0.5)
            for rank in range(1, 21)
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory) / "reviews.sqlite3")
            with self.assertRaisesRegex(ValueError, "fewer than 20"):
                store.save_review(
                    reviewer_id="expert",
                    query_visit_id="query",
                    candidates=candidates,
                    selected_visit_ids=[item.candidate_visit_id for item in candidates],
                    no_relevant_case=False,
                    reviewer_note="",
                    retrieval_config=json.loads("{}"),
                    query_snapshot={},
                )


if __name__ == "__main__":
    unittest.main()
