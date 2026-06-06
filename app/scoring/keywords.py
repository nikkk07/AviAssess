import re

import numpy as np

from app.scoring.normalize import normalize, tokenize
from app.scoring.semantic import get_model

def keyword_coverage(
        student_answer:str,
        essential_keywords:list[str],
        supporting_keywords:list[str]
) -> dict:
    
    # Normalize Student Answer into Tokens

    student_tokens = set(tokenize(student_answer))

    # Also keep the full normalized string for phrase matching
    student_normalized = normalize(student_answer)

    # Check Essential Keywords

    essential_hit = []
    essential_miss = []

    for keyword in essential_keywords:
        kw_normalized = normalize(keyword)

        # Two-Level Matching : 

        # 1. Is the Keyword a Single Word ?
        #     -> Check if it's in the Token Set
        # 2. Is the Keyword a Phrase ?
        #     -> Check if it appear in full string

        if " " not in kw_normalized:

            # Single Word - Check Token Set
            matched =kw_normalized in student_tokens

        else:
            # Multi-Word Phrase - Check SubString
            matched = kw_normalized in student_normalized

        if matched : 
            essential_hit.append(keyword)
        else:
            essential_miss.append(keyword)


        # Check Supporting Keywords ( Same Logic )

        supporting_hit = []

        for keyword in supporting_keywords:
            kw_normalized = normalize(keyword)

            if " " not in kw_normalized:
                matched = kw_normalized in student_tokens
            else : 
                matched = kw_normalized in student_normalized

            if matched : 
                supporting_hit.append(keyword)


        # Calculate Rates 

        # Avoid Division by Zero - if Lists are Empty

        essential_rate = ( len(essential_hit) / len(essential_keywords) if essential_keywords else 1.0)
        supporting_rate = ( len(supporting_hit) / len(supporting_keywords) if supporting_keywords else 0.0)



    # ─────────────────────────────────────────────
    # Weighted combination
    # Essential keywords matter MORE than supporting
    # Weight: 70% essential + 30% supporting
    # ─────────────────────────────────────────────
    score = (0.70 * essential_rate) + (0.30 * supporting_rate)

    return {
        "score": round(score, 4),
        "essential_hit": essential_hit,
        "essential_miss": essential_miss,
        "supporting_hit": supporting_hit,
        "essential_rate": round(essential_rate, 4),
        "supporting_rate": round(supporting_rate, 4),
    }


# ─────────────────────────────────────────────────────────
# SEMANTIC keyword coverage
#
# WHY a second function (instead of replacing the first)?
#     The exact keyword_coverage() above is perfect for TECHNICAL
#     questions, where the dataset author chose precise terms the
#     student is expected to actually say ("lift", "drag", "yaw").
#
#     But BEHAVIORAL / SITUATIONAL questions have no "correct" wording.
#     A great answer to "Why aviation?" might never contain the literal
#     word "passion" — it might say "I've been fascinated by flight since
#     I was a kid". Exact matching scores that as a miss, which is wrong.
#
#     So here we measure whether each keyword's MEANING shows up anywhere
#     in the answer, using the same sentence-transformer already loaded by
#     semantic.py (no second model — that would blow the 512 MB budget).
# ─────────────────────────────────────────────────────────

# Two-tier graded credit. A keyword rarely matches a sentence perfectly,
# so we reward partial thematic presence instead of demanding a near-copy.
# These thresholds are the main calibration dials — the demo prints the
# raw similarities so they can be tuned against real answers.
STRONG_MATCH_THRESHOLD = 0.50   # clear thematic match  -> full credit
WEAK_MATCH_THRESHOLD   = 0.35   # loose thematic match  -> half credit
STRONG_CREDIT          = 1.0
WEAK_CREDIT            = 0.5
NO_CREDIT              = 0.0

# Essentials are the core themes; supporting themes are bonus depth.
WEIGHT_ESSENTIAL  = 0.70
WEIGHT_SUPPORTING = 0.30


def _split_sentences(text: str) -> list[str]:
    """
    Split raw text into sentences on . ! ? — BEFORE any normalization.

    WHY before normalize()? normalize() strips all punctuation, which would
    erase the very sentence boundaries we need. We split first, then normalize
    each sentence individually for encoding.
    """
    if not text or not text.strip():
        return []

    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def _credit_for(similarity: float) -> float:
    """Map a raw max-similarity to graded keyword credit."""
    if similarity >= STRONG_MATCH_THRESHOLD:
        return STRONG_CREDIT
    if similarity >= WEAK_MATCH_THRESHOLD:
        return WEAK_CREDIT
    return NO_CREDIT


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    """Normalize each row to unit length so a dot product == cosine similarity."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # guard: zero vectors stay zero, no divide-by-zero
    return matrix / norms


def semantic_keyword_coverage(
        student_answer: str,
        essential_keywords: list[str],
        supporting_keywords: list[str],
) -> dict:
    """
    Measure how well each keyword's MEANING appears in the answer.

    Pipeline:
        1. Split the answer into sentences (before normalization).
        2. Batch-encode all sentences in ONE model.encode() call, and all
           keywords in ONE call (batching is far cheaper than per-item calls).
        3. Build an (S x K) cosine-similarity matrix.
        4. For each keyword, take its MAX similarity across every sentence —
           the theme only needs to appear somewhere, not in every sentence.
        5. Convert each max-similarity to graded credit (strong/weak/none).

    Returns:
        {
          "score": float 0-1,
          "essential_hit":  [...], "essential_miss": [...],
          "supporting_hit": [...],
          "essential_rate": float, "supporting_rate": float,
          "similarities": {keyword: raw_max_similarity},  # for calibration
        }

    A keyword counts as "hit" if it earned ANY credit (max-sim >= WEAK).
    """

    all_keywords = list(essential_keywords) + list(supporting_keywords)
    n_essential  = len(essential_keywords)

    # Normalize each sentence individually for encoding (consistent with
    # how semantic.py embeds text). Empty-after-normalize sentences drop out.
    sentences = [normalize(s) for s in _split_sentences(student_answer)]
    sentences = [s for s in sentences if s]

    # ─────────────────────────────────────────────
    # Compute the max similarity per keyword.
    # Guard: with no sentences (empty answer) or no keywords,
    # every similarity is 0 — skip the model entirely.
    # ─────────────────────────────────────────────
    if not sentences or not all_keywords:
        max_sims = [0.0] * len(all_keywords)
    else:
        model = get_model()

        sentence_vecs = np.asarray(
            model.encode(sentences), dtype=float
        )
        keyword_vecs = np.asarray(
            model.encode([normalize(k) for k in all_keywords]), dtype=float
        )

        # Cosine matrix via unit-normalized dot product: (S x d)(d x K) = (S x K)
        sim_matrix = _unit_rows(sentence_vecs) @ _unit_rows(keyword_vecs).T

        # Best-matching sentence per keyword, clipped to a clean [0, 1].
        max_sims = np.clip(sim_matrix.max(axis=0), 0.0, 1.0).tolist()

    # ─────────────────────────────────────────────
    # Grade every keyword
    # ─────────────────────────────────────────────
    similarities: dict[str, float] = {}
    essential_hit, essential_miss, supporting_hit = [], [], []
    essential_credits, supporting_credits = [], []

    for index, keyword in enumerate(all_keywords):
        similarity = float(max_sims[index])
        similarities[keyword] = round(similarity, 4)

        credit = _credit_for(similarity)
        is_essential = index < n_essential

        if is_essential:
            essential_credits.append(credit)
            (essential_hit if credit > 0 else essential_miss).append(keyword)
        else:
            supporting_credits.append(credit)
            if credit > 0:
                supporting_hit.append(keyword)

    # ─────────────────────────────────────────────
    # Aggregate.
    # Score uses MEAN CREDIT (graded), so half-credits count.
    # Rates use HIT FRACTION (binary), for human-readable reporting.
    # Empty-list defaults mirror the exact keyword_coverage() above.
    # ─────────────────────────────────────────────
    essential_score = (
        sum(essential_credits) / len(essential_credits)
        if essential_credits else 1.0
    )
    supporting_score = (
        sum(supporting_credits) / len(supporting_credits)
        if supporting_credits else 0.0
    )
    score = (WEIGHT_ESSENTIAL * essential_score) + (WEIGHT_SUPPORTING * supporting_score)

    essential_rate = (
        len(essential_hit) / len(essential_keywords)
        if essential_keywords else 1.0
    )
    supporting_rate = (
        len(supporting_hit) / len(supporting_keywords)
        if supporting_keywords else 0.0
    )

    return {
        "score": round(score, 4),
        "essential_hit": essential_hit,
        "essential_miss": essential_miss,
        "supporting_hit": supporting_hit,
        "essential_rate": round(essential_rate, 4),
        "supporting_rate": round(supporting_rate, 4),
        "similarities": similarities,
    }


if __name__ == "__main__":

    student = (
        "Aerodynamics is basically the reason some things cut "
        "through air smoothly while others struggle against it. "
        "The better the airflow, the faster and more efficient "
        "the movement feels."
    )

    essential = ["aerodynamics", "air", "lift", "drag"]
    supporting = ["fluid", "speed", "pressure", "efficiency", "airflow"]

    result = keyword_coverage(student, essential, supporting)

    print("=" * 50)
    print(f"  Keyword Score    : {round(result['score'] * 100, 2)}%")
    print(f"  Essential Hit    : {result['essential_hit']}")
    print(f"  Essential Miss   : {result['essential_miss']}")
    print(f"  Supporting Hit   : {result['supporting_hit']}")
    print(f"  Essential Rate   : {round(result['essential_rate'] * 100)}%")
    print(f"  Supporting Rate  : {round(result['supporting_rate'] * 100)}%")
    print("=" * 50)

    # ─────────────────────────────────────────────
    # SEMANTIC keyword coverage demo
    # Same answer, but matched by MEANING instead of exact words.
    # ─────────────────────────────────────────────
    sem_result = semantic_keyword_coverage(student, essential, supporting)

    print("\n" + "=" * 50)
    print("  SEMANTIC KEYWORD COVERAGE")
    print("=" * 50)
    print(f"  Score            : {round(sem_result['score'] * 100, 2)}%")
    print(f"  Essential Hit    : {sem_result['essential_hit']}")
    print(f"  Essential Miss   : {sem_result['essential_miss']}")
    print(f"  Supporting Hit   : {sem_result['supporting_hit']}")
    print(f"  Essential Rate   : {round(sem_result['essential_rate'] * 100)}%")
    print(f"  Supporting Rate  : {round(sem_result['supporting_rate'] * 100)}%")
    print(f"  Similarities     : {sem_result['similarities']}")
    print("=" * 50)