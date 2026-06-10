# Question-bank JSON schema

The question bank is a **JSON array of question objects**, loaded by
`app/data/loader.py::load_questions()` from `QUESTIONS_PATH`
(default `tests/fixtures/sample_qa.json`, swappable for Cloudflare R2 later).

This document is the contract the Phase B dataset must satisfy so it drops in
cleanly. A new file just needs to be a non-empty JSON list of objects shaped
like the ones below — no code changes required.

> **Anti-cheat:** the `answer` and keyword fields live ONLY server-side. They are
> never serialized to the browser (see `QuestionPublic` in `app/data/models.py`).

---

## Fields

### Core (always expected)

| Field                 | Type   | Notes |
|-----------------------|--------|-------|
| `id`                  | string | Unique question id (e.g. `"q001"`). **Required** — keys session membership + scoring lookups. |
| `question`            | string | The prompt shown to the candidate. **Required.** |
| `question_type`       | string | One of `technical` \| `behavioral` \| `situational`. Drives which scorer runs and which interview types surface it. **Required.** |
| `category`            | string | Topic bucket (e.g. `aerodynamics`, `teamwork`). Used by the legacy `category` filter. |
| `difficulty`          | string | Backend band: `basic` \| `intermediate` \| `advanced`. Maps from screen bands friendly→basic, standard→intermediate, tough→advanced. |
| `time_limit_seconds`  | int    | Per-question time budget. Falls back to the admin `default_time_limit_seconds` if absent. |

### Interview-configuration tags (Phase A1 — all OPTIONAL)

These let a session be narrowed by interview parameters. **A question that omits
a tag matches ANY requested value of that tag** — untagged questions are never
excluded. This is why the current untagged fixture keeps working unchanged.

| Field            | Type   | Notes |
|------------------|--------|-------|
| `interview_type` | string | Optional hint of the screen interview type this question belongs to (`hr_personal` \| `technical` \| ...). Selection currently derives eligibility from `question_type` via the taxonomy map, so this is informational/forward-looking. |
| `airline`        | string | Optional airline tag (e.g. `"BA"`). Filter is graceful + relaxable. |
| `aircraft_type`  | string | Optional aircraft tag (e.g. `"A320"`). Filter is graceful + relaxable. |
| `experience`     | string | Optional experience tag (e.g. `"cadet"`). Filter is graceful + relaxable. |

Relaxation order when a filtered pool is too thin (most specific dropped first):
`aircraft_type → experience → airline → difficulty`. `question_type` and
`category` are core scope and are never relaxed.

### Scoring fields — **REQUIRED for scoring to be meaningful**

A question missing these is still **served** to the candidate, but **cannot be
meaningfully scored** on its content dimensions.

| Field                  | Type        | Required for | Notes |
|------------------------|-------------|--------------|-------|
| `essential_keywords`   | string[]    | **technical scoring** | Must-hit concepts; absence tanks the technical dimension. |
| `supporting_keywords`  | string[]    | **technical scoring** | Bonus concepts that round out a strong answer. |
| `model_answer` *(or `answer`)* | string \| null | **HR/behavioral relevance scoring** | Reference answer the response is compared against for relevance. |
| `relevance_keywords`   | string[]    | **HR/behavioral relevance scoring** | Alternative to `model_answer`: keyword set used to gauge on-topic relevance. |

> For `technical` questions, provide `essential_keywords` + `supporting_keywords`.
> For `behavioral`/`situational` questions, provide a `model_answer`
> (or `relevance_keywords`). The current fixture uses `essential_keywords` /
> `supporting_keywords` for HR items too; either form is accepted, but the
> relevance scorer is strongest with a `model_answer`.

---

## Minimal examples

Technical question (content-scorable):

```json
{
  "id": "q001",
  "question": "What are the four forces of flight?",
  "question_type": "technical",
  "category": "aerodynamics",
  "difficulty": "basic",
  "time_limit_seconds": 90,
  "essential_keywords": ["lift", "weight", "thrust", "drag"],
  "supporting_keywords": ["equilibrium", "balance"]
}
```

Behavioral question with optional interview tags:

```json
{
  "id": "q120",
  "question": "Describe a time you defused a conflict in the flight deck.",
  "question_type": "behavioral",
  "category": "teamwork",
  "difficulty": "intermediate",
  "time_limit_seconds": 120,
  "interview_type": "hr_personal",
  "airline": "BA",
  "aircraft_type": "A320",
  "experience": "cadet",
  "model_answer": "A strong answer names the conflict, the calm steps taken to de-escalate, and the positive outcome.",
  "essential_keywords": ["a disagreement", "staying calm", "resolving the issue"],
  "supporting_keywords": ["compromise", "professionalism"]
}
```
