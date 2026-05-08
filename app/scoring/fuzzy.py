from rapidfuzz import fuzz
from normalize import normalize

def fuzzy_similarity ( student_answer:str, expected_answer:str ) -> float :

    '''
    Compute the Fuzzy Similarity between the Student Answer and the Expected Answer

    We'll use Token_Set_Ratio which :
    1. Splits both Strngs into Word Tokens
    2. Sorts Tokens Alphabetically
    3. Computes Similarity on Sorted Tokens
    '''

    # Normalize Both Before Comparing

    s = normalize(student_answer)
    e = normalize(expected_answer)

    if not s or not e :
        return 0.0
    
    score = fuzz.token_set_ratio(s,e) / 100.0

    return round(score, 4)

if __name__ == "__main__":
    pairs = [
        (
            "The rudder controls the yaw of the aircraft",
            "The rudder controls yaw",
            "Subset match — student wrote less"
        ),
        (
            "aerodinamics is the study of air movement",
            "Aerodynamics is the study of how air moves around objects",
            "Typo in aerodynamics"
        ),
        (
            "lift drag weight thrust are the four forces",
            "The four forces of flight are lift weight thrust and drag",
            "Same words different order"
        ),
        (
            "I have no idea",
            "Aerodynamics is the study of how air moves around objects",
            "Completely wrong answer"
        ),
    ]

    print("=" * 60)
    for student, expected, label in pairs:
        score = fuzzy_similarity(student, expected)
        print(f"\n  {label}")
        print(f"  Student  : {student[:55]}")
        print(f"  Expected : {expected[:55]}")
        print(f"  Score    : {round(score * 100, 2)}%")
    print("\n" + "=" * 60)