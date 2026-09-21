import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from common import sha256, write_json
from qwen3_patient_embeddings import (
    DOCUMENT_FILE,
    IDS_FILE,
    QUERY_FILE,
    TASK_INSTRUCTION,
    _load_vectors,
    exact_cosine,
    last_token_pool,
    query_text,
)


class QwenPatientEmbeddingTests(unittest.TestCase):
    def test_query_instruction_and_last_token_pool(self):
        value = query_text("ICD chính: J18.9")
        self.assertEqual(value, f"Instruct: {TASK_INSTRUCTION}\nQuery: ICD chính: J18.9")
        states = torch.arange(2 * 3 * 2).reshape(2, 3, 2)
        right_mask = torch.tensor([[1, 1, 0], [1, 1, 1]])
        pooled = last_token_pool(states, right_mask)
        self.assertTrue(torch.equal(pooled, torch.stack([states[0, 1], states[1, 2]])))
        left_mask = torch.tensor([[0, 1, 1], [1, 1, 1]])
        self.assertTrue(torch.equal(last_token_pool(states, left_mask), states[:, -1]))

    def test_exact_cosine_excludes_self_and_orders_ties_by_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ids = ["P00001", "P00002", "P00003"]
            documents = np.asarray([[1, 0], [0, 1], [0, 1]], dtype=np.float32)
            queries = documents.copy()
            for filename, value in ((DOCUMENT_FILE, documents), (QUERY_FILE, queries)):
                with (root / filename).open("wb") as handle:
                    np.save(handle, value, allow_pickle=False)
            write_json(root / IDS_FILE, ids)
            write_json(root / "manifest.json", {
                "patients": 3, "embedding_dimension": 2,
                "outputs": {
                    DOCUMENT_FILE: sha256(root / DOCUMENT_FILE),
                    QUERY_FILE: sha256(root / QUERY_FILE),
                    IDS_FILE: sha256(root / IDS_FILE),
                },
            })
            result = exact_cosine(root, "P00001", 2)
            self.assertEqual([row["patient_id"] for row in result], ["P00002", "P00003"])
            self.assertTrue(all(row["cosine_similarity"] == 0.0 for row in result))
            with self.assertRaises(KeyError):
                exact_cosine(root, "P99999", 2)

    def test_loader_rejects_non_normalized_vector(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ids = ["P00001", "P00002"]
            documents = np.asarray([[2, 0], [0, 1]], dtype=np.float32)
            queries = np.asarray([[1, 0], [0, 1]], dtype=np.float32)
            for filename, value in ((DOCUMENT_FILE, documents), (QUERY_FILE, queries)):
                with (root / filename).open("wb") as handle:
                    np.save(handle, value, allow_pickle=False)
            write_json(root / IDS_FILE, ids)
            write_json(root / "manifest.json", {
                "patients": 2, "embedding_dimension": 2,
                "outputs": {
                    DOCUMENT_FILE: sha256(root / DOCUMENT_FILE),
                    QUERY_FILE: sha256(root / QUERY_FILE),
                    IDS_FILE: sha256(root / IDS_FILE),
                },
            })
            with self.assertRaisesRegex(ValueError, "not L2-normalized"):
                _load_vectors(root)


if __name__ == "__main__":
    unittest.main()
