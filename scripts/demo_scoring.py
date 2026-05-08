"""
AeroEval - Similarity Scoring Demo
Run this to see how the AI compares answers.

Usage: python scripts/demo_scoring.py
"""

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ─────────────────────────────────────────────
# STEP 1: Load the AI Model
# This model understands the MEANING of sentences
# not just the words.
# ─────────────────────────────────────────────
print("Loading AI model... (first time takes 1-2 min to download)")
model = SentenceTransformer("paraphrase-MiniLM-L3-v2")
print("Model ready!\n")

# ─────────────────────────────────────────────
# STEP 2: Define the Question + Answers
# ─────────────────────────────────────────────
question = "What is Aerodynamics?"

expected_answer = (
    "Aerodynamics is the study of how air moves around objects "
    "and how forces like lift and drag affect motion. It is widely "
    "used in aircraft, cars, and engineering design to improve "
    "performance and efficiency."
). 

student_answer = (
    "Aerodynamics is basically the reason some things cut through "
    "air smoothly while others struggle against it. The better the "
    "airflow, the faster and more efficient the movement feels."
)

# ─────────────────────────────────────────────
# STEP 3: Convert Both Answers into Vectors
# The model reads both answers and converts each
# into a list of 384 numbers (a "vector").
# Similar meaning = similar numbers.
# ─────────────────────────────────────────────
print(f"Question     : {question}")
print(f"Expected     : {expected_answer[:80]}...")
print(f"Student Said : {student_answer[:80]}...")
print()

expected_vector = model.encode([expected_answer])
student_vector  = model.encode([student_answer])

# ─────────────────────────────────────────────
# STEP 4: Compare the Two Vectors
# cosine_similarity returns a value between 0 and 1
# 0 = completely different meaning
# 1 = identical meaning
# ─────────────────────────────────────────────
similarity = cosine_similarity(student_vector, expected_vector)[0][0]

# Convert to percentage
score = round(float(similarity) * 100, 2)

# ─────────────────────────────────────────────
# STEP 5: Show the Result
# ─────────────────────────────────────────────
print("=" * 50)
print(f"  Similarity Score : {score}%")
print("=" * 50)

# Score band
if score >= 85:
    band = "Excellent"
elif score >= 70:
    band = "Good"
elif score >= 50:
    band = "Partial Understanding"
elif score >= 30:
    band = "Weak"
else:
    band = "Incorrect"

print(f"  Performance Band : {band}")
print("=" * 50)