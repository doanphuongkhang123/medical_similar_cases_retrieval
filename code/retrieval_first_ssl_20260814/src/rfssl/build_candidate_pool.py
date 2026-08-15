"""CLI for a quality-gated FAISS cosine candidate pool."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .retrieval import candidate_frame, load_passing_embeddings, nearest_neighbors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--allow-exact-numpy", action="store_true", help="testing fallback when FAISS is unavailable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")
    if args.output_dir.exists():
        raise FileExistsError(f"refusing to overwrite output directory: {args.output_dir}")
    frame, vectors = load_passing_embeddings(args.embeddings, args.quality_report)
    backend = "numpy" if args.allow_exact_numpy else "faiss"
    if backend == "faiss":
        try:
            import faiss  # noqa: F401
        except ImportError as error:
            raise RuntimeError(
                "FAISS is not installed in scr_env. Install a compatible faiss package or pass --allow-exact-numpy for tests."
            ) from error
    args.output_dir.mkdir(parents=True, exist_ok=False)
    neighbors = nearest_neighbors(
        vectors,
        top_k=args.top_k,
        backend=backend,
        index_path=args.output_dir / "visit_embeddings.faiss",
    )
    candidates = candidate_frame(frame, neighbors)
    candidates.to_parquet(args.output_dir / "pre_review_candidates.parquet", index=False)
    (args.output_dir / "index_manifest.json").write_text(
        json.dumps({
            "backend": neighbors.backend,
            "embedding_version": str(frame.embedding_version.iloc[0]),
            "snapshot_mode": str(frame.snapshot_mode.iloc[0]),
            "top_k": int(args.top_k),
            "query_count": int(len(frame)),
            "self_retrieval_excluded": True,
            "clinical_relevance_labels_used": False,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
