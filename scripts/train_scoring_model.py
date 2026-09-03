"""
Phase 2 scoring model trainer.

Triggered when signal_snapshots has >= 80 rows with user_outcome filled in.
Reads labeled snapshots, computes feature-outcome correlations, and writes
candidate weight updates to scoring_config_candidates.json for human review.

Usage:
    python scripts/train_scoring_model.py

Output:
    scoring_config_candidates.json   — proposed weight update (review before applying)

After reviewing, apply approved weights with:
    python scripts/apply_weights.py --candidate scoring_config_candidates.json
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.storage.database import get_connection

PHASE2_THRESHOLD = 80
CANDIDATE_PATH = ROOT / "scoring_config_candidates.json"
CONFIG_PATH = ROOT / "scoring_config.json"


def count_labeled(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM signal_snapshots WHERE user_outcome IS NOT NULL"
    ).fetchone()
    return row[0] if row else 0


def load_labeled_snapshots(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT firmographic_score, keyword_score, growth_score,
               timing_score, lookalike_score, total_score, tier_assigned,
               user_outcome
        FROM signal_snapshots
        WHERE user_outcome IS NOT NULL
        """
    ).fetchall()
    cols = [
        "firmographic_score", "keyword_score", "growth_score",
        "timing_score", "lookalike_score", "total_score", "tier_assigned",
        "user_outcome",
    ]
    return [dict(zip(cols, r)) for r in rows]


def compute_candidate_weights(snapshots: list[dict], current_config: dict) -> dict:
    """
    Compute candidate weights from labeled data.

    Strategy (Phase 2 heuristic — replace with proper regression once N > 200):
    - For each sub-score, compute mean sub-score for positive vs negative outcomes.
    - Scale current weights proportionally to the positive/total signal ratio.
    - Renormalize so weights sum to the same total as the current config.
    """
    score_keys = [
        "firmographic_score", "keyword_score", "growth_score",
        "timing_score", "lookalike_score",
    ]
    # Keys as they appear in scoring_config.json "weights" dict
    weight_keys = [
        "firmographic", "keyword_relevance", "growth_signals",
        "timing_indicators", "lookalike_similarity",
    ]

    positive = [s for s in snapshots if s["user_outcome"] in ("kept", "converted")]
    negative = [s for s in snapshots if s["user_outcome"] in ("removed", "skipped")]

    if not positive or not negative:
        print("Warning: need both positive and negative outcomes to compute candidates.")
        print("Returning current weights unchanged.")
        return current_config

    def mean_score(rows, key):
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0

    pos_means = {k: mean_score(positive, k) for k in score_keys}
    neg_means = {k: mean_score(negative, k) for k in score_keys}

    signals = {}
    for sk in score_keys:
        total = pos_means[sk] + neg_means[sk]
        signals[sk] = pos_means[sk] / total if total > 0 else 0.5

    current_weights = current_config.get("weights", {})
    current_total = sum(current_weights.get(wk, 0) for wk in weight_keys)

    raw = {}
    for sk, wk in zip(score_keys, weight_keys):
        raw[wk] = current_weights.get(wk, 1.0) * signals[sk]

    raw_total = sum(raw.values())
    scale = current_total / raw_total if raw_total > 0 else 1.0
    candidate_weights = {wk: round(v * scale, 4) for wk, v in raw.items()}

    candidate_config = dict(current_config)
    candidate_config["weights"] = {**current_weights, **candidate_weights}
    candidate_config["_candidate_metadata"] = {
        "labeled_count": len(snapshots),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "training_method": "heuristic_phase2",
    }
    return candidate_config


def main():
    conn = get_connection()
    labeled_count = count_labeled(conn)

    print(f"Labeled snapshots: {labeled_count} / {PHASE2_THRESHOLD} required")

    if labeled_count < PHASE2_THRESHOLD:
        print(
            f"Phase 2 not yet triggered. Need {PHASE2_THRESHOLD - labeled_count} more "
            f"labeled outcomes."
        )
        sys.exit(0)

    snapshots = load_labeled_snapshots(conn)
    print(f"Loaded {len(snapshots)} labeled snapshots.")

    with open(CONFIG_PATH) as f:
        current_config = json.load(f)

    candidate_config = compute_candidate_weights(snapshots, current_config)

    with open(CANDIDATE_PATH, "w") as f:
        json.dump(candidate_config, f, indent=2)

    print(f"\nCandidate weights written to: {CANDIDATE_PATH}")
    print("\nProposed weight changes:")
    for k, v in candidate_config["weights"].items():
        old = current_config.get("weights", {}).get(k, "N/A")
        marker = " <-- changed" if v != old else ""
        print(f"  {k}: {old} → {v}{marker}")

    print(
        "\nReview the candidates, then run:\n"
        "  python scripts/apply_weights.py --candidate scoring_config_candidates.json"
    )


if __name__ == "__main__":
    main()
