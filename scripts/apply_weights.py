"""
Human-approved weight update script.

Applies a candidate scoring config (produced by train_scoring_model.py) to
scoring_config.json after human review. Backs up the current config first.

Usage:
    python scripts/apply_weights.py --candidate scoring_config_candidates.json

    # Dry-run (show diff without writing):
    python scripts/apply_weights.py --candidate scoring_config_candidates.json --dry-run

Backup location: scoring_config_history/scoring_config_v{N}.json
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_scoring_config  # noqa: E402
CONFIG_PATH = ROOT / "scoring_config.json"
HISTORY_DIR = ROOT / "scoring_config_history"


def next_version(history_dir: Path) -> str:
    existing = sorted(history_dir.glob("scoring_config_v*.json"))
    if not existing:
        return "v1"
    last = existing[-1].stem  # e.g. "scoring_config_v3"
    n = int(last.split("_v")[-1])
    return f"v{n + 1}"


def diff_weights(old: dict, new: dict) -> list[str]:
    old_w = old.get("weights", {})
    new_w = new.get("weights", {})
    all_keys = sorted(set(old_w) | set(new_w))
    lines = []
    for k in all_keys:
        o = old_w.get(k, "—")
        n = new_w.get(k, "—")
        marker = " ***" if o != n else ""
        lines.append(f"  {k}: {o} → {n}{marker}")
    return lines


def apply(candidate_path: Path, dry_run: bool) -> None:
    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    if not candidate_path.exists():
        print(f"Error: {candidate_path} not found.", file=sys.stderr)
        sys.exit(1)

    with open(CONFIG_PATH) as f:
        current = json.load(f)

    with open(candidate_path) as f:
        candidate = json.load(f)

    # Strip internal metadata before applying
    candidate_clean = {k: v for k, v in candidate.items() if not k.startswith("_")}

    print("Weight changes to apply:")
    for line in diff_weights(current, candidate_clean):
        print(line)

    if dry_run:
        print("\nDry-run — no changes written.")
        return

    HISTORY_DIR.mkdir(exist_ok=True)
    version = next_version(HISTORY_DIR)
    backup_path = HISTORY_DIR / f"scoring_config_{version}.json"
    shutil.copy2(CONFIG_PATH, backup_path)
    print(f"\nBackup written: {backup_path}")

    # Bump version in config
    old_version = current.get("version", "0.0.0")
    parts = str(old_version).split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    candidate_clean["version"] = ".".join(parts)
    candidate_clean["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with open(CONFIG_PATH, "w") as f:
        json.dump(candidate_clean, f, indent=2)

    # load_scoring_config() is lru_cached; drop the stale copy if this runs
    # in-process (e.g. from a notebook). Other running processes must restart.
    load_scoring_config.cache_clear()

    print(f"scoring_config.json updated → version {candidate_clean['version']}")
    print("\nDone. Run `pytest tests/` to confirm nothing broke.")


def main():
    parser = argparse.ArgumentParser(description="Apply approved weight candidate to scoring_config.json")
    parser.add_argument("--candidate", required=True, help="Path to candidate JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Show diff without writing")
    args = parser.parse_args()

    apply(Path(args.candidate), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
