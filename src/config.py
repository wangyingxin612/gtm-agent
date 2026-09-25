import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def load_scoring_config(path: str = "scoring_config.json") -> dict:
    """Load scoring config once per process.

    Cached: edits to scoring_config.json (e.g. via scripts/apply_weights.py)
    are not seen by a running process until load_scoring_config.cache_clear()
    is called or the process restarts.
    """
    abs_path = os.path.join(os.path.dirname(__file__), "..", path)
    with open(abs_path) as f:
        return json.load(f)
