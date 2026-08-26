import tempfile
import unittest
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from embed_smb_visits import (
    EMBEDDING_DIMENSION,
    load_shard,
    shard_groups,
    shard_path,
    write_shard_atomic,
)


class SmbResumableInferenceTest(unittest.TestCase):
    def test_atomic_shard_round_trip_and_groups(self) -> None:
        plan = pd.DataFrame({"target_order": np.arange(5, dtype=np.int64)})
        groups = list(shard_groups(plan, 2))
        self.assertEqual([len(group) for _, group in groups], [2, 2, 1])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            start, group = groups[0]
            path = shard_path(root, start, len(group))
            matrix = np.zeros((2, EMBEDDING_DIMENSION), dtype=np.float32)
            matrix[:, 0] = 1.0
            write_shard_atomic(
                path,
                group["target_order"].to_numpy(),
                matrix,
                np.asarray([2.0, 3.0], dtype=np.float32),
                np.asarray([100, 200], dtype=np.int32),
            )
            loaded, norms = load_shard(path, group["target_order"].to_numpy())
            np.testing.assert_array_equal(loaded, matrix)
            np.testing.assert_array_equal(norms, np.asarray([2.0, 3.0]))
            self.assertFalse(path.with_suffix(".npz.tmp").exists())

    def test_corrupt_or_wrong_order_shard_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shard.npz"
            matrix = np.zeros((1, EMBEDDING_DIMENSION), dtype=np.float32)
            matrix[:, 0] = 1.0
            write_shard_atomic(
                path,
                np.asarray([7]),
                matrix,
                np.asarray([2.0]),
                np.asarray([100]),
            )
            with self.assertRaises(ValueError):
                load_shard(path, np.asarray([8]))


if __name__ == "__main__":
    unittest.main()
