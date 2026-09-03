import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def load_scoring_config(path: str = "scoring_config.json") -> dict:
    abs_path = os.path.join(os.path.dirname(__file__), "..", path)
    with open(abs_path) as f:
        return json.load(f)
