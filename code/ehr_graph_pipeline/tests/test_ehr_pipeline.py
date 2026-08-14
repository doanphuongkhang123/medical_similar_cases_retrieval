from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))
from build_visit_graphs import graph_for_visit
from ehr_common import parse_lab_value
from preprocess_ehr import apply_snapshot, canonicalize, fit_artifacts, split_visits
from supervised_retrieval import candidate_frame, fit_projection, project, ranking_metrics


POLICY = {
    "snapshot": {"first_24h_hours": 24},
    "split": {"seed": 7, "train_fraction": 0.7, "validation_fraction": 0.15},
    "allowed_text_sections": ["LyDoVaoVien"],
    "vitals": ["Mach"],
}


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = {
            "visits": pd.DataFrame({"SoBenhAn": ["V1", "V2"], "NgayVaoVien": ["2025-01-01", "2025-01-02"], "NgayRaVien": ["2025-01-03", "2025-01-04"], "TenPhongBan": ["A", "B"], "LyDoVaoVien": ["secret note", "second note"], "Mach": [80, 90]}),
            "orders": pd.DataFrame({"SoBenhAn": ["V1"], "YeuCauChiTiet_Id": ["O1"], "TenDichVu": ["CBC"], "NgayYeuCau": ["2025-01-01 01:00"]}),
            "medications": pd.DataFrame({"sobenhan": ["V1"], "SoThuTuToa": ["P1"], "TenDuoc": ["Drug A"], "TenHoatChat": ["A"], "NgayKham": ["2025-01-01 02:00"]}),
            "labs": pd.DataFrame({"SoBenhAn": ["V1", "V1"], "YeuCauChiTiet_Id": ["O1", "O1"], "TEN_CHI_SO": ["WBC", "WBC"], "GIA_TRI": ["<3.5", "positive"], "DON_VI_DO": ["K/uL", ""], "NGAY_KQ": ["2025-01-01 03:00", "2025-01-03 03:00"]}),
            "procedures": pd.DataFrame({"YeuCauChiTiet_Id": ["O1"], "TenDichVu": ["Procedure"], "ThoiGianBatDau": ["2025-01-01 04:00"]}),
        }

    def test_lab_parser_preserves_non_numeric_value(self) -> None:
        numeric = parse_lab_value("<= 3,5")
        categorical = parse_lab_value("positive")
        self.assertEqual(numeric["comparison_operator"], "<=")
        self.assertEqual(numeric["numeric_value"], 3.5)
        self.assertTrue(categorical["parse_success"] is False)
        self.assertEqual(categorical["categorical_value"], "positive")

    def test_canonical_graph_has_no_raw_text_and_snapshot_excludes_late_lab(self) -> None:
        visits, events, relations, _ = canonicalize(self.frames, POLICY)
        self.assertNotIn("secret note", " ".join(events.text_value.astype(str)))
        visits = split_visits(visits, POLICY)
        early = apply_snapshot(visits, events, "first_24h", 24)
        self.assertEqual(len(early[early.event_type == "LAB_RESULT"]), 1)
        vocab, stats = fit_artifacts(events, visits)
        graph = graph_for_visit(visits.iloc[0], events[events.visit_id == "V1"], relations[relations.visit_id == "V1"], vocab, stats)
        self.assertEqual(graph["nodes"][0]["node_type"], "VISIT")
        self.assertTrue(any(edge["relation"] == "has_result" for edge in graph["edges"]))
        self.assertFalse(any("secret note" in str(node) for node in graph["nodes"]))

    def test_encoder_emits_l2_normalized_visit_vector(self) -> None:
        try:
            import torch
            from gt_behrt_visit import GTBEHRTVisit
        except ModuleNotFoundError:
            self.skipTest("PyTorch is tested in scr_env on the server")
        model = GTBEHRTVisit(vocab_size=8, node_type_count=3, relation_count=2, hidden_dimension=32, output_dimension=16, layers=2, heads=4, dropout=0.0)
        vector = model(
            torch.tensor([0, 1, 2]), torch.tensor([0, 1, 1]),
            torch.tensor([0.0, 1.0, -1.0]), torch.tensor([0.0, 2.0, 4.0]),
            torch.tensor([0, 1, 2, 1]), torch.tensor([1, 0, 1, 2]), torch.tensor([0, 1, 0, 1]),
        )
        self.assertEqual(tuple(vector.shape), (16,))
        self.assertTrue(torch.allclose(vector.norm(), torch.tensor(1.0), atol=1e-6))

    def test_retrieval_candidates_and_judged_metrics(self) -> None:
        frame = pd.DataFrame({
            "visit_id": ["T1", "T2", "V1"],
            "split": ["train", "train", "validation"],
            "embedding": [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]],
        })
        vectors = np.asarray(frame.embedding.tolist(), dtype=np.float32)
        candidates = candidate_frame(frame, vectors, "validation", "train", top_k=1, random_k=1, seed=7)
        self.assertEqual(len(candidates), 2)
        pairs = candidates.assign(relevance=[2, 0], partition="test")
        report = ranking_metrics(frame, vectors, pairs, "test", [1, 2])
        self.assertEqual(report["evaluation_scope"], "judged_candidate_set_only")
        self.assertEqual(report["queries"], 1)
        self.assertAlmostEqual(report["metrics"]["precision_at_1"], 1.0)

    def test_supervised_projection_uses_train_pairs_and_normalizes_vectors(self) -> None:
        frame = pd.DataFrame({
            "visit_id": ["T1", "T2", "T3", "V1"],
            "split": ["train", "train", "train", "validation"],
            "embedding": [[1.0, 0.0], [0.8, 0.2], [0.0, 1.0], [0.7, 0.3]],
        })
        vectors = np.asarray(frame.embedding.tolist(), dtype=np.float32)
        pairs = pd.DataFrame({
            "query_visit_id": ["T1", "T1"],
            "candidate_visit_id": ["T2", "T3"],
            "relevance": [2, 0],
            "partition": ["train", "train"],
        })
        checkpoint, manifest = fit_projection(frame, vectors, pairs, dimension=2, epochs=2, learning_rate=1e-2, seed=7, device="cpu")
        projected = project(frame, vectors, checkpoint, device="cpu")
        norms = np.linalg.norm(np.asarray(projected.embedding.tolist(), dtype=np.float32), axis=1)
        self.assertEqual(manifest["train_pairs"], 2)
        self.assertTrue(np.allclose(norms, 1.0, atol=1e-6))


if __name__ == "__main__":
    unittest.main()
