# Combining all the Three Scoring Engines into one

from semantic import semantic_similarity
from keywords import keyword_coverage
from fuzzy import fuzzy_similarity

# Signal Weight Must Sum to 1.0
# change these to tune scoring behavior

WEIGHT_SEMANTIC = 0.6
WEIGHT_KEYWORD = 0.25
WEIGHT_FUZZY = 0.15

def score_answer (
        
        student_answer:str,
        expected_answer:str,
        essential_keywords:list[str],
        supporting_keywords:list[str]
) -> dict:
    
    '''
    Score a Student's Answer Against the Expected Answer 
    
    Args : 
        student_answer : Raw Text From the Student
        expected_answer : Reference Answer from Dataset
        essential_keywords : Must-have concepts
        supporting_keywords : Nice-to-have concepts

    Returns ; 
        Full Scoring Result dict with score , band , breakdown , feedback and keyword details 
    '''

    # Guard : Empty Answer

    if not student_answer or not student_answer.strip() : 
        return _empty_result()
    
    # Run all three Scorers Independently

    semantic_score = semantic_similarity(student_answer, expected_answer)

    keyword_result = keyword_coverage( student_answer, essential_keywords, supporting_keywords)

    keyword_score = keyword_result["score"]

    fuzzy_score = fuzzy_similarity(student_answer, expected_answer)

    # Weighted Combination

    raw_score = (
        (WEIGHT_SEMANTIC * semantic_score) +
        ( WEIGHT_KEYWORD * keyword_score) +
        ( WEIGHT_FUZZY * fuzzy_score )
    ) 

    # Length Penalty : Short Answers or One-Word Answers

    student_word_count = len(student_answer.strip().split())
    expected_word_count = len(expected_answer.strip().split())

    if student_word_count < 4 and expected_word_count >= 15 :
        raw_score *= 0.5  # 50% Penalty for too short answers

    # Clamp Final Score to [0,1]
    final_score = max(0.0 , min(1.0, raw_score))

    # Convert to Percentage

    final_percentage = round(final_score * 100, 1)

    # Score Band

    band = _get_band(final_percentage)

    # Feedback Message 

    feedback = _generate_feedback(
        score = final_percentage,
        band = band, 
        essential_hit = keyword_result["essential_hit"],
        essential_miss = keyword_result["essential_miss"],
        supporting_hit = keyword_result["supporting_hit"],
    )

    return {
        # main result

        "score" : final_percentage, 
        "band" : band,
        "feedback" : feedback

        # Score Breakdown for Front End Display

        "breakdown" : {
            "semantic" : round(semantic_score * 100, 1),
            "keyword" : round(keyword_score * 100, 1),
            "fuzzy" : round(fuzzy_score * 100, 1),
        }
    }
    