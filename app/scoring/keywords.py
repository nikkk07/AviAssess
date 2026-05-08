from normalize import normalize, tokenize

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