from __future__ import annotations

import unittest
from pathlib import Path
import sys

import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).parents[1]))

from embed_clinical_notes import (
    _aggregate_note_text,
    _prepare_visits,
    last_token_pool,
)


class TextEmbeddingTest(unittest.TestCase):
    def test_prepare_visits_reconstructs_preprocessed_text_and_preserves_order(self) -> None:
        notes = pd.DataFrame({
            "note_id": ["n2", "n1"],
            "patient_id": ["p1", "p1"],
            "visit_id": ["v1", "v1"],
            "note_type": ["visit_note", "visit_note"],
            "section_name": ["S2", "S1"],
            "note_text": ["two", "one"],
            "event_time": [pd.NaT, pd.Timestamp("2025-01-01")],
            "source_sheet": ["sheet", "sheet"],
            "source_key": ["k2", "k1"],
            "source_row_count": [1, 2],
        })
        visits = pd.DataFrame({
            "patient_id": ["p1"], "visit_id": ["v1"], "primary_key": ["p1::v1"],
            "admission_time": [pd.Timestamp("2025-01-01")], "discharge_time": [pd.Timestamp("2025-01-02")],
            "department": ["d"], "birth_year": [1980], "age_at_visit": [45], "gender_code": ["x"],
            "clinical_note": ["[S2]\ntwo\n\n[S1]\none"], "diagnosis_count": [0], "medicine_count": [0],
            "procedure_count": [0], "note_section_count": [2], "observation_count": [0],
            "has_diagnosis": [False], "has_medicine": [False], "has_procedure": [False],
            "has_clinical_note": [True],
        })
        prepared, order = _prepare_visits(notes, visits)
        self.assertEqual(order, ["v1"])
        self.assertEqual(prepared.loc[0, "actual_note_row_count"], 2)
        self.assertEqual(prepared.loc[0, "source_row_count_total"], 3)
        self.assertEqual(prepared.loc[0, "chunk_count"], 1)

    def test_aggregate_note_text_is_section_aware(self) -> None:
        group = pd.DataFrame({"section_name": ["A", "B"], "note_text": ["one", "two"]})
        self.assertEqual(_aggregate_note_text(group), "[A]\none\n\n[B]\ntwo")

    def test_last_token_pool_uses_last_non_padding_token(self) -> None:
        hidden = torch.tensor([
            [[10.0, 10.0], [1.0, 2.0], [3.0, 4.0]],
            [[5.0, 6.0], [7.0, 8.0], [9.0, 10.0]],
        ])
        mask = torch.tensor([[0, 1, 1], [1, 1, 1]])
        pooled = last_token_pool(hidden, mask)
        self.assertTrue(torch.equal(pooled, torch.tensor([[3.0, 4.0], [9.0, 10.0]])))

    def test_last_token_pool_handles_right_padding(self) -> None:
        hidden = torch.tensor([[[1.0, 2.0], [3.0, 4.0], [99.0, 99.0]]])
        mask = torch.tensor([[1, 1, 0]])
        pooled = last_token_pool(hidden, mask)
        self.assertTrue(torch.equal(pooled, torch.tensor([[3.0, 4.0]])))

    def test_prepare_visits_rejects_duplicate_visit_ids(self) -> None:
        frame = pd.DataFrame({
            "note_id": ["n1"], "patient_id": ["p1"], "visit_id": ["v1"], "note_type": ["t"],
            "section_name": ["s"], "note_text": ["fixture one"], "event_time": [pd.NaT],
            "source_sheet": ["sheet"], "source_key": ["k"], "source_row_count": [1],
        })
        visits = pd.DataFrame({"visit_id": ["v1", "v1"]})
        with self.assertRaises(ValueError):
            _prepare_visits(frame, visits)


if __name__ == "__main__":
    unittest.main()
