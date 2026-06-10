"""
Data loading — questions and admin config.

WHY this module exists (and why it's deliberately thin):
    Right now questions and config live in LOCAL files (a JSON fixture and a
    local config.json). In Phase 5 these move to Cloudflare R2. By keeping all
    file access behind these three functions, the swap to an R2-backed
    implementation changes ONLY this module — callers (main.py) keep calling
    load_questions() / load_config() / save_config() unchanged.

QUESTION-BANK JSON SCHEMA (what load_questions() expects):
    The file is a non-empty JSON ARRAY of question objects. Full field-by-field
    contract — including which fields are REQUIRED for scoring — lives in
    docs/QUESTION_SCHEMA.md. Quick reference:

      Core            : id, question, question_type (technical|behavioral|
                        situational), category, difficulty (basic|intermediate|
                        advanced), time_limit_seconds
      Optional tags   : interview_type, airline, aircraft_type, experience
                        (a question LACKING a tag matches ANY requested value)
      Scoring (req'd) : essential_keywords + supporting_keywords  → technical
                        model_answer (or relevance_keywords)       → HR/relevance

    A question missing its scoring fields is still SERVED but cannot be
    meaningfully scored. See docs/QUESTION_SCHEMA.md before adding a dataset.
"""

import json
import logging
from pathlib import Path

from app.config import settings


logger = logging.getLogger("aviassess.loader")


# Sensible defaults used when no config.json exists yet.
DEFAULT_CONFIG: dict = {
    "num_questions": 5,
    "default_time_limit_seconds": 90,
    "enabled_question_types": ["technical", "behavioral", "situational"],
    "enabled_categories": [],
}


# Fields every question row MUST carry to be usable for serving + scoring. The
# KEY must be present; `answer` MAY be null (behavioral/situational items often
# have no single model answer). The optional interview tags (interview_type,
# airline, aircraft_type, experience) are NOT required and may be null.
REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "question",
    "question_type",
    "answer",
    "essential_keywords",
    "supporting_keywords",
    "category",
    "difficulty",
    "time_limit_seconds",
)


def _is_valid_question(row: object, index: int) -> bool:
    """
    True if `row` is a well-formed question. Malformed rows are LOGGED and the
    caller skips them — one bad row must never crash the whole pool.
    """
    if not isinstance(row, dict):
        logger.warning("Skipping question at index %d: not a JSON object.", index)
        return False
    # Presence check only (value may legitimately be null, e.g. `answer`).
    missing = [f for f in REQUIRED_FIELDS if f not in row]
    if missing:
        logger.warning(
            "Skipping question %r (index %d): missing required field(s): %s",
            row.get("id", "<no id>"), index, ", ".join(missing),
        )
        return False
    return True


def load_questions() -> list[dict]:
    """
    Load the full question pool (with answers + keywords) from QUESTIONS_PATH.

    Each row is validated against REQUIRED_FIELDS; rows missing a required field
    (or that aren't JSON objects) are LOGGED and SKIPPED rather than crashing the
    load. Optional interview tags (interview_type/airline/aircraft_type/
    experience) are allowed and may be null. The expected file shape is a plain
    JSON ARRAY — see the schema note at the top of this module.

    Raises:
        FileNotFoundError: if the path doesn't exist.
        ValueError:        if the file isn't a JSON list, or NO valid rows remain.
    """
    path = Path(settings.QUESTIONS_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Questions file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, list) or not data:
        raise ValueError(
            f"Questions file must be a non-empty JSON list: {path}"
        )

    valid = [row for i, row in enumerate(data) if _is_valid_question(row, i)]

    skipped = len(data) - len(valid)
    if skipped:
        logger.warning(
            "Loaded %d of %d questions from %s (%d skipped as malformed).",
            len(valid), len(data), path, skipped,
        )

    if not valid:
        raise ValueError(
            f"No valid questions found in {path} — every row was malformed."
        )

    return valid


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
