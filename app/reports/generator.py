"""
Final-report aggregation.

WHY this module exists:
    Per-answer scoring already happened (engine.score_response, one call per
    question). This module does the LAST step: roll those per-answer results up
    into one session report. It does NO model work and NO re-scoring — it only
    aggregates numbers the engine already produced.

    It reuses engine's banding (_get_band) instead of redefining thresholds, so
    a session's overall band uses the exact same cut-offs as a single answer.
"""

from app.scoring.engine import _get_band


# Short overall message keyed off the session's band.
SUMMARY_MESSAGES = {
    "excellent": "Outstanding session — strong, well-rounded performance throughout.",
    "good":      "Good session overall, with a few areas to sharpen.",
    "partial":   "A mixed session — the basics are there but several answers need depth.",
    "weak":      "This session needs work — review the core concepts and practice delivery.",
    "incorrect": "This session fell short across most questions — significant practice needed.",
}


def aggregate_report(results: list[dict]) -> dict:
    """
    Aggregate per-answer results into a SessionCompleteResponse-shaped dict.

    Scoring rule (matches the engine): a skipped question scores 0 and STILL
    COUNTS — so the total is the mean of final_score over ALL results, including
    skipped-as-0. This is deliberate: skipping is not free.

    Args:
        results: list of per-answer result dicts, each with at least
                 question_id, final_score, band, was_skipped.

    Returns:
        {
          total_score, overall_band, num_questions, num_skipped,
          per_question: [{question_id, final_score, band}, ...],
          summary,
        }
    """
    num_questions = len(results)
    num_skipped = sum(1 for r in results if r.get("was_skipped"))

    # Mean over ALL results (skipped count as their 0). Guard empty → 0.
    if num_questions > 0:
        total_score = round(
            sum(r.get("final_score", 0.0) for r in results) / num_questions, 1
        )
    else:
        total_score = 0.0

    overall_band = _get_band(total_score)

    per_question = [
        {
            "question_id": r.get("question_id"),
            "final_score": r.get("final_score", 0.0),
            "band": r.get("band", "incorrect"),
        }
        for r in results
    ]

    return {
        "total_score": total_score,
        "overall_band": overall_band,
        "num_questions": num_questions,
        "num_skipped": num_skipped,
        "per_question": per_question,
        "summary": SUMMARY_MESSAGES.get(overall_band, ""),
    }
