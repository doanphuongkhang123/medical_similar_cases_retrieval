from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DATA_ROOT = Path(
    "/mnt/disk4/similar_cases_retrieval/data"
)
DEFAULT_EHR_ROOT = DEFAULT_DATA_ROOT / "ehr/ehr_preprocessed/ehr_preprocessed_full"
DEFAULT_EHR_EMBEDDINGS = (
    DEFAULT_DATA_ROOT
    / "experiments/retrieval_first_ssl_structured_full_s3_projectorfix_20260815"
    / "visit_embeddings.parquet"
)
DEFAULT_TEXT_EMBEDDINGS = (
    DEFAULT_DATA_ROOT / "note_emb/visit_note_embeddings_qwen3_8b_256d.csv"
)


@dataclass(frozen=True)
class AppConfig:
    ehr_root: Path
    ehr_embeddings: Path
    text_embeddings: Path
    database_path: Path
    top_k: int = 20
    ehr_weight: float = 1.0
    text_weight: float = 1.0

    @classmethod
    def from_environment(cls) -> "AppConfig":
        app_root = Path(__file__).resolve().parent
        return cls(
            ehr_root=Path(os.environ.get("EXPERT_REVIEW_EHR_ROOT", DEFAULT_EHR_ROOT)),
            ehr_embeddings=Path(
                os.environ.get(
                    "EXPERT_REVIEW_EHR_EMBEDDINGS", DEFAULT_EHR_EMBEDDINGS
                )
            ),
            text_embeddings=Path(
                os.environ.get(
                    "EXPERT_REVIEW_TEXT_EMBEDDINGS", DEFAULT_TEXT_EMBEDDINGS
                )
            ),
            database_path=Path(
                os.environ.get(
                    "EXPERT_REVIEW_DATABASE",
                    app_root / "data/ground_truth.sqlite3",
                )
            ),
            ehr_weight=float(os.environ.get("EXPERT_REVIEW_EHR_WEIGHT", "1.0")),
            text_weight=float(os.environ.get("EXPERT_REVIEW_TEXT_WEIGHT", "1.0")),
        )

    def validate(self) -> None:
        required = {
            "EHR directory": self.ehr_root,
            "EHR embeddings": self.ehr_embeddings,
            "text embeddings": self.text_embeddings,
        }
        missing = [f"{name}: {path}" for name, path in required.items() if not path.exists()]
        if missing:
            raise FileNotFoundError("Missing required input:\n" + "\n".join(missing))
        if self.top_k != 20:
            raise ValueError("The expert-review interface is fixed to top_k=20")
        if self.ehr_weight <= 0 or self.text_weight <= 0:
            raise ValueError("Embedding weights must be positive")
