"""
Data loading — questions and admin config.

WHY this module exists (and why it's deliberately thin):
    Right now questions and config live in LOCAL files (a JSON fixture and a
    local config.json). In Phase 5 these move to Cloudflare R2. By keeping all
    file access behind these three functions, the swap to an R2-backed
    implementation changes ONLY this module — callers (main.py) keep calling
    load_questions() / load_config() / save_config() unchanged.
"""

import json
from pathlib import Path

from app.config import settings


# Sensible defaults used when no config.json exists yet.
DEFAULT_CONFIG: dict = {
    "num_questions": 5,
    "default_time_limit_seconds": 90,
    "enabled_question_types": ["technical", "behavioral", "situational"],
    "enabled_categories": [],
}


def load_questions() -> list[dict]:
    """
    Load the full question pool (with answers + keywords) from QUESTIONS_PATH.

    Raises:
        FileNotFoundError: if the path doesn't exist.
        ValueError:        if the file isn't a non-empty JSON list.
    """
    path = Path(settings.QUESTIONS_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Questions file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, list) or not data:
        raise ValueError(
            f"Questions file must be a non-empty JSON list: {path}"
        )

    return data


def load_config() -> dict:
    """
    Load admin config from CONFIG_PATH, falling back to DEFAULT_CONFIG.

    Missing keys in a partial file are backfilled from the defaults, so the
    returned dict always has the full expected shape.
    """
    path = Path(settings.CONFIG_PATH)
    if not path.exists():
        return dict(DEFAULT_CONFIG)

    stored = json.loads(path.read_text(encoding="utf-8"))
    return {**DEFAULT_CONFIG, **stored}


def save_config(cfg: dict) -> None:
    """
    Persist admin config to CONFIG_PATH.

    LOCAL-DEV ONLY: Render's filesystem is ephemeral, so this write does NOT
    survive a restart/redeploy. Phase 5 replaces this with an R2 PUT so config
    is durable across instances.
    """
    Path(settings.CONFIG_PATH).write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )
