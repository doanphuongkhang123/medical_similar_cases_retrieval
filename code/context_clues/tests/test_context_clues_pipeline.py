from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from context_clues_pipeline.data import (
    build_concept_map_template,
    prepare_context_clues_events,
    prepare_source_event_dataset,
)
from context_clues_pipeline.embedding import infer_embeddings, tokenize_visit_timelines
from context_clues_pipeline.raw_workbook import validate_structured_tables
from context_clues_pipeline.timeline import build_visit_timelines


@dataclass
class FakeEvent:
    code: str
    value: object = None
    unit: str | None = None
    start: object = None
    end: object = None
    omop_table: str | None = None


class FakeTokenizer:
    def __init__(self) -> None:
        codes = [
            "SNOMED/3950001", "Gender/M", "Visit/IP", "SNOMED/111",
            "SNOMED/222", "RxNorm/333", "CPT4/444", "LOINC/555",
        ]
        self.ids = {code: index + 10 for index, code in enumerate(codes)}

    def convert_event_to_token(self, event: FakeEvent) -> str | None:
        if event.code not in self.ids:
            return None
        # Exercise numeric fallback: numeric LOINC is rejected, code-only is accepted.
        if event.code == "LOINC/555" and event.value is not None:
            return None
        return event.code

    def convert_tokens_to_ids(self, tokens: list[str]) -> list[int]:
        return [self.ids[token] for token in tokens]


class ContextCluesPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input_root = self.root / "ehr"
        self.input_root.mkdir()
        visits = pd.DataFrame(
            {
                "patient_id": ["p1", "p1", "p2"],
                "visit_id": ["v1", "v2", "v3"],
                "admission_time": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
                "discharge_time": pd.to_datetime(["2024-01-03", "2024-02-04", "2024-03-02"]),
                "birth_year": [1980, 1980, 1990],
                "gender_code": ["Nam", "Nam", "Nữ"],
            }
        )
        diagnoses = pd.DataFrame(
            {
                "diagnosis_id": ["d1", "d2", "d3"],
                "patient_id": ["p1", "p1", "p2"],
                "visit_id": ["v1", "v2", "v3"],
                "diagnosis_code": ["A01", "B02", "A01"],
                "diagnosis_text": ["", "", ""],
                "event_time": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]),
            }
        )
        medicines = pd.DataFrame(
            {
                "medicine_id": ["m1"],
                "patient_id": ["p1"],
                "visit_id": ["v2"],
                "active_ingredient": ["Drug A"],
                "drug_name": ["Brand A"],
                "prescribed_time": pd.to_datetime(["2024-02-02"]),
                "unit": ["tablet"],
            }
        )
        procedures = pd.DataFrame(
            {
                "procedure_id": ["r1"],
                "patient_id": ["p2"],
                "visit_id": ["v3"],
                "service_code": ["PROC1"],
                "performed_name": ["Procedure A"],
                "procedure_name": ["Procedure A"],
                "start_time": pd.to_datetime(["2024-03-01 12:00"]),
                "ordered_time": pd.to_datetime(["2024-03-01 10:00"]),
            }
        )
        observations = pd.DataFrame(
            {
                "observation_id": ["o1"],
                "patient_id": ["p1"],
                "visit_id": ["v2"],
                "service_code": ["LABPANEL"],
                "observation_name": ["Test A"],
                "result_numeric": [12.0],
                "result_type": ["numeric_exact"],
                "unit": ["mg/L"],
                "observed_time": pd.to_datetime(["2024-02-03"]),
            }
        )
        for name, frame in {
            "visits": visits,
            "diagnoses": diagnoses,
            "medicines": medicines,
            "procedures": procedures,
            "observations": observations,
        }.items():
            frame.to_parquet(self.input_root / f"{name}.parquet", index=False)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _approved_map(self) -> Path:
        path = self.root / "concept_map.csv"
        mapping = build_concept_map_template(self.input_root, path)
        target_by_key = {
            ("diagnoses", "code:a01"): "SNOMED/111",
            ("diagnoses", "code:b02"): "SNOMED/222",
            ("medicines", "name:drug a"): "RxNorm/333",
            ("procedures", "code:proc1"): "CPT4/444",
            ("observations", "code_name:labpanel|test a"): "LOINC/555",
        }
        for index, row in mapping.iterrows():
            mapping.loc[index, "target_code"] = target_by_key[(row.source_table, row.source_key)]
            mapping.loc[index, "mapping_status"] = "approved"
            if row.source_table == "observations":
                mapping.loc[index, "use_value"] = "true"
        mapping.to_csv(path, index=False)
        return path

    def test_prepare_keeps_outputs_separate_and_builds_visit_history(self) -> None:
        output = self.root / "context_clues" / "prepared"
        manifest = prepare_context_clues_events(
            self.input_root, self._approved_map(), output
        )
        self.assertEqual(manifest["counts"]["visits"], 3)
        self.assertEqual(manifest["event_mapping_coverage"], 1.0)
        self.assertFalse(manifest["clinical_notes_included"])
        self.assertTrue((output / "events.parquet").exists())
        self.assertEqual(json.loads((output / "manifest.json").read_text())["schema_version"], 1)

        events = pd.read_parquet(output / "events.parquet")
        visits = pd.read_parquet(output / "visits.parquet")
        history = {item.visit_id: item for item in build_visit_timelines(events, visits, "history")}
        visit_only = {item.visit_id: item for item in build_visit_timelines(events, visits, "visit_only")}
        self.assertIn("v1", set(history["v2"].events["visit_id"]))
        self.assertNotIn("v1", set(visit_only["v2"].events["visit_id"]))
        self.assertEqual(history["v2"].history_visit_count, 2)

    def test_data_only_stage_materializes_every_source_event(self) -> None:
        output = self.root / "context_clues" / "source_prepared"
        manifest = prepare_source_event_dataset(self.input_root, output)

        self.assertEqual(manifest["counts"]["patients"], 2)
        self.assertEqual(manifest["counts"]["visits"], 3)
        self.assertEqual(manifest["counts"]["source_events"], 6)
        self.assertFalse(manifest["encoder_run"])
        events = pd.read_parquet(output / "source_events.parquet")
        self.assertEqual(len(events), 6)
        self.assertTrue(events["event_id"].is_unique)
        self.assertFalse(events["effective_time"].isna().any())
        self.assertTrue((output / "concept_mapping_worklist.csv").exists())
        self.assertTrue((output / "ENCODER_HANDOFF.md").exists())

    def test_raw_structured_contract_has_no_notes_or_orphan_visits(self) -> None:
        tables = {
            name: pd.read_parquet(self.input_root / f"{name}.parquet")
            for name in ("visits", "diagnoses", "medicines", "procedures", "observations")
        }
        audit = validate_structured_tables(tables)
        self.assertEqual(audit["patients"], 2)
        self.assertEqual(audit["visits"], 3)
        self.assertFalse(audit["clinical_notes_built"])
        self.assertFalse(audit["graph_tables_built"])
        self.assertTrue(
            all(row["orphan_visit_keys"] == 0 for row in audit["tables"].values())
        )

    def test_tokenization_has_numeric_fallback_and_current_visit_tokens(self) -> None:
        output = self.root / "context_clues" / "prepared"
        prepare_context_clues_events(self.input_root, self._approved_map(), output)
        events = pd.read_parquet(output / "events.parquet")
        visits = pd.read_parquet(output / "visits.parquet")
        timelines = build_visit_timelines(events, visits, "history")
        items = tokenize_visit_timelines(
            timelines, FakeTokenizer(), FakeEvent, max_length=4096
        )
        by_visit = {item.visit_id: item for item in items}
        self.assertEqual(by_visit["v2"].n_numeric_fallbacks, 1)
        self.assertGreaterEqual(by_visit["v2"].n_current_visit_clinical_tokens, 3)
        self.assertEqual(len(items), 3)

    def test_inference_returns_l2_normalized_vectors_in_visit_order(self) -> None:
        try:
            import torch
        except ImportError:
            self.skipTest("torch is not installed")

        class FakeBase:
            def __call__(self, input_ids, attention_mask, use_cache, return_dict):
                hidden = torch.stack((input_ids.float(), torch.ones_like(input_ids).float()), dim=-1)
                return SimpleNamespace(last_hidden_state=hidden)

        class FakeModel:
            base_model = FakeBase()

            def eval(self):
                return self

        from context_clues_pipeline.embedding import TokenizedVisit

        items = [
            TokenizedVisit(0, "p1", "v1", pd.Timestamp("2024-01-03"), [10, 11], 2, 2, 2, 0, 2, 1, 1),
            TokenizedVisit(1, "p1", "v2", pd.Timestamp("2024-02-04"), [12], 1, 1, 1, 0, 1, 1, 2),
        ]
        matrix = infer_embeddings(
            items, FakeModel(), pad_token_id=4, device=torch.device("cpu"),
            batch_size=2, max_tokens_per_batch=8, l2_normalize=True,
        )
        self.assertEqual(matrix.shape, (2, 2))
        np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-6)
        self.assertGreater(matrix[1, 0], matrix[0, 0])


if __name__ == "__main__":
    unittest.main()
