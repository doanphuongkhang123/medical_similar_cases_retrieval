from __future__ import annotations

import math
import random
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
import torch

from rfssl.data import GraphExample, MISSING_TIME_BUCKET, RELATION_TO_ID, TYPE_TO_ID, load_structured_dataset
from rfssl.model import StructuredGraphSSL
from rfssl.objectives import (
    choose_mask_indices,
    choose_mnp_index,
    corrupt_graph_for_mi,
    local_global_mi_loss,
    VICRegStatisticsQueue,
    vicreg_mi_loss,
)
from rfssl.retrieval import candidate_frame, nearest_neighbors
from rfssl.train import _build_parser, _quality_report, _retrieval_embedding


class StructuredSSLTest(unittest.TestCase):
    def setUp(self) -> None:
        self.vocab = {
            "<PAD>": 0, "<MASK>": 1, "<UNK>": 2,
            "DIAGNOSIS:a": 3, "OBSERVATION:b": 4, "OBSERVATION:c": 5,
        }
        self.stats = {
            "OBSERVATION:b": {"median": 5.0, "iqr": 2.0},
            "OBSERVATION:c": {"median": 5.0, "iqr": 2.0},
        }
        self.example = GraphExample(
            visit_id="fixture-v1",
            split="train",
            node_types=(TYPE_TO_ID["VISIT"], TYPE_TO_ID["DIAGNOSIS"], TYPE_TO_ID["OBSERVATION"], TYPE_TO_ID["OBSERVATION"]),
            tokens=("<PAD>", "DIAGNOSIS:a", "OBSERVATION:b", "OBSERVATION:c"),
            numeric_values=(math.nan, math.nan, 3.0, 7.0),
            counts=(0, 1, 1, 1),
            time_hours=(0.0, 0.0, 720.0, 721.0),
            order_keys=("", "", "O1", "O1"),
            edges=(
                (0, 1, RELATION_TO_ID["has_diagnosis"]), (1, 0, RELATION_TO_ID["diagnosis_of"]),
                (0, 2, RELATION_TO_ID["has_observation"]), (2, 0, RELATION_TO_ID["observation_of"]),
                (0, 3, RELATION_TO_ID["has_observation"]), (3, 0, RELATION_TO_ID["observation_of"]),
                (2, 3, RELATION_TO_ID["next_same_test"]), (3, 2, RELATION_TO_ID["prev_same_test"]),
            ),
        )

    def test_masked_graph_and_encoder_are_finite(self) -> None:
        graph = self.example.tensors(self.vocab, self.stats, torch.device("cpu"), concept_mask=[1], numeric_mask=[2])
        self.assertEqual(graph["concept_ids"].tolist()[1], self.vocab["<MASK>"])
        self.assertEqual(float(graph["numeric"][2, 6]), 1.0)
        self.assertEqual(graph["time_buckets"].tolist(), [0, 0, 30, 30])
        model = StructuredGraphSSL(vocab_size=len(self.vocab), node_type_count=5, relation_count=12, hidden_dim=32, output_dim=16, layers=2, heads=4, dropout=0.0)
        hidden, embedding = model(**graph)
        self.assertEqual(tuple(hidden.shape), (4, 32))
        self.assertEqual(tuple(embedding.shape), (16,))
        self.assertTrue(torch.isfinite(embedding).all())
        self.assertTrue(torch.allclose(embedding.norm(), torch.tensor(1.0), atol=1e-5))

    def test_training_defaults_are_twenty_epochs_with_validation_controls(self) -> None:
        args = _build_parser().parse_args([
            "--data-root", "/tmp/fixture-data", "--output", "/tmp/fixture-output", "--stage", "1",
        ])
        self.assertEqual(args.epochs, 20)
        self.assertEqual(args.early_stopping_patience, 5)
        self.assertEqual(args.scheduler_patience, 2)
        self.assertEqual(args.scheduler_factor, 0.5)

    def test_inf_ehr_style_objective_is_finite(self) -> None:
        graph = self.example.tensors(self.vocab, self.stats, torch.device("cpu"), concept_mask=[1])
        model = StructuredGraphSSL(vocab_size=len(self.vocab), node_type_count=5, relation_count=12, hidden_dim=32, output_dim=16, layers=2, heads=4, dropout=0.0)
        hidden_one, _, raw_one = model(return_raw=True, **graph)
        hidden_two, _, raw_two = model(return_raw=True, **graph)
        corrupted = corrupt_graph_for_mi(graph)
        self.assertIsNotNone(corrupted)
        assert corrupted is not None
        self.assertFalse(torch.equal(graph["concept_ids"], corrupted["concept_ids"]))
        _, _, raw_corrupted = model(return_raw=True, **corrupted)
        mi = local_global_mi_loss(model, hidden_one, raw_one, raw_corrupted)
        loss, components = vicreg_mi_loss(torch.stack([raw_one, raw_two]), torch.stack([raw_two, raw_one]), [mi])
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(set(components), {"similarity", "variance", "covariance", "mi"})

    def test_mi_corruption_uses_exact_known_24h_buckets(self) -> None:
        graph = self.example.tensors(self.vocab, self.stats, torch.device("cpu"))
        self.assertEqual(graph["time_buckets"].tolist()[2:], [30, 30])
        self.assertIsNotNone(corrupt_graph_for_mi(graph))

        different_windows = dict(graph)
        different_buckets = graph["time_buckets"].clone()
        different_buckets[3] = 41
        different_windows["time_buckets"] = different_buckets
        self.assertIsNone(corrupt_graph_for_mi(different_windows))

        unknown_windows = dict(graph)
        unknown_buckets = graph["time_buckets"].clone()
        unknown_buckets[2:] = MISSING_TIME_BUCKET
        unknown_windows["time_buckets"] = unknown_buckets
        self.assertIsNone(corrupt_graph_for_mi(unknown_windows))

    def test_stage_three_exports_encoder_embedding_not_projector(self) -> None:
        graph = self.example.tensors(self.vocab, self.stats, torch.device("cpu"))
        model = StructuredGraphSSL(vocab_size=len(self.vocab), node_type_count=5, relation_count=12, hidden_dim=32, output_dim=16, layers=2, heads=4, dropout=0.0)
        model.eval()
        with torch.no_grad():
            _, expected = model(**graph)
            exported_before = _retrieval_embedding(model, graph)
            for parameter in model.ssl_projector.parameters():
                parameter.fill_(123.0)
            exported_after = _retrieval_embedding(model, graph)
        self.assertTrue(torch.allclose(exported_before, expected, atol=1e-6))
        self.assertTrue(torch.allclose(exported_after, expected, atol=1e-6))

    def test_detached_vicreg_statistics_queue_changes_only_moment_terms(self) -> None:
        current_one = torch.tensor([[1.0, 0.0]], requires_grad=True)
        current_two = torch.tensor([[0.0, 1.0]], requires_grad=True)
        queue = VICRegStatisticsQueue(history_size=2, max_stat_vectors=3)
        queue.enqueue(
            torch.tensor([[2.0, 0.0], [3.0, 0.0]], requires_grad=True),
            torch.tensor([[0.0, 2.0], [0.0, 3.0]], requires_grad=True),
        )
        statistic_one, statistic_two, history_count = queue.statistics(current_one, current_two)
        self.assertEqual(history_count, 2)
        self.assertEqual(tuple(statistic_one.shape), (3, 2))
        self.assertTrue(all(not vector.requires_grad for vector in queue._one))
        self.assertTrue(all(not vector.requires_grad for vector in queue._two))

        base_loss, base_components = vicreg_mi_loss(current_one, current_two, [])
        queued_loss, queued_components = vicreg_mi_loss(
            current_one, current_two, [],
            statistics_one=statistic_one,
            statistics_two=statistic_two,
        )
        self.assertTrue(torch.allclose(base_components["similarity"], queued_components["similarity"]))
        self.assertTrue(torch.allclose(base_components["mi"], queued_components["mi"]))
        self.assertFalse(torch.allclose(base_loss, queued_loss))
        queued_loss.backward()
        self.assertIsNotNone(current_one.grad)
        self.assertTrue(torch.isfinite(current_one.grad).all())

    def test_vicreg_statistics_queue_is_fifo_and_zero_history_is_noop(self) -> None:
        queue = VICRegStatisticsQueue(history_size=2, max_stat_vectors=4)
        for value in (1.0, 2.0, 3.0):
            vectors = torch.tensor([[value, 0.0]])
            queue.enqueue(vectors, vectors + 10.0)
        self.assertEqual(queue.history_count, 2)
        self.assertEqual([float(vector[0]) for vector in queue._one], [2.0, 3.0])

        current_one = torch.tensor([[1.0, 0.0], [0.0, 1.0]])
        current_two = torch.tensor([[0.5, 0.5], [0.0, 1.0]])
        no_history = VICRegStatisticsQueue(history_size=0, max_stat_vectors=4)
        stats_one, stats_two, count = no_history.statistics(current_one, current_two)
        self.assertEqual(count, 0)
        direct, _ = vicreg_mi_loss(current_one, current_two, [])
        queued, _ = vicreg_mi_loss(current_one, current_two, [], statistics_one=stats_one, statistics_two=stats_two)
        self.assertTrue(torch.allclose(direct, queued))

    def test_quality_gate_uses_validation_not_all_splits(self) -> None:
        frame = pd.DataFrame({
            "split": ["train", "validation", "validation", "test"],
            "embedding": [[math.nan, 0.0], [1.0, 0.0], [0.0, 1.0], [math.nan, 0.0]],
            "node_count": [5, 6, 7, 8],
        })
        report = _quality_report(frame, {"cross_view_recall_at_1_delta": 1.0})
        self.assertEqual(report["quality_gate_split"], "validation")
        self.assertEqual(report["embedding_count"], 2)
        self.assertTrue(report["finite"])
        self.assertFalse(report["all_split_descriptive"]["finite"])

    def test_masking_and_mnp_preserve_the_sole_core_node(self) -> None:
        rng = random.Random(7)
        concepts = choose_mask_indices(self.example, ratio=1.0, numeric_only=False, rng=rng)
        self.assertNotIn(1, concepts)
        numeric = choose_mask_indices(self.example, ratio=1.0, numeric_only=True, rng=rng)
        self.assertEqual(set(numeric), {2, 3})
        for _ in range(20):
            self.assertNotEqual(choose_mnp_index(self.example, {}, rng), 1)

    def test_exact_candidate_pool_excludes_self(self) -> None:
        vectors = np.asarray([
            [1.0, 0.0],
            [0.8, 0.6],
            [0.0, 1.0],
        ], dtype=np.float32)
        frame = pd.DataFrame({
            "visit_id": ["v1", "v2", "v3"],
            "split": ["train", "validation", "test"],
            "snapshot_mode": ["full_visit"] * 3,
            "embedding_version": ["fixture"] * 3,
            "node_count_by_type": [
                '{"DIAGNOSIS": 1, "MEDICINE": 0, "OBSERVATION": 2, "PROCEDURE": 0, "VISIT": 1}',
                '{"DIAGNOSIS": 1, "MEDICINE": 1, "OBSERVATION": 1, "PROCEDURE": 0, "VISIT": 1}',
                '{"DIAGNOSIS": 0, "MEDICINE": 0, "OBSERVATION": 2, "PROCEDURE": 1, "VISIT": 1}',
            ],
            "node_count": [3, 4, 4],
        })
        neighbors = nearest_neighbors(vectors, top_k=2, backend="numpy")
        candidates = candidate_frame(frame, neighbors)
        self.assertEqual(len(candidates), 6)
        self.assertTrue((candidates.query_visit_id != candidates.candidate_visit_id).all())
        self.assertEqual(candidates.groupby("query_visit_id")["rank"].max().tolist(), [2, 2, 2])

    def test_description_only_diagnosis_never_becomes_a_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pd.DataFrame({
                "visit_id": ["fixture-v1"],
                "admission_time": ["2026-01-01T00:00:00Z"],
            }).to_csv(root / "visits.csv", index=False)
            pd.DataFrame({
                "visit_id": ["fixture-v1"],
                "diagnosis_code": [""],
                "diagnosis_text": ["free-text-fixture"],
                "diagnosis_type": ["primary"],
                "event_time": ["2026-01-01T01:00:00Z"],
            }).to_csv(root / "diagnoses.csv", index=False)
            for table in ("medicines", "procedures", "observations"):
                pd.DataFrame({"visit_id": []}).to_csv(root / f"{table}.csv", index=False)
            dataset = load_structured_dataset(root)
        self.assertEqual(dataset.examples[0].node_types, (TYPE_TO_ID["VISIT"],))


if __name__ == "__main__":
    unittest.main()
