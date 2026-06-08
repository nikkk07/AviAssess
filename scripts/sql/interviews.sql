-- AviAssess results persistence (Phase 5)
-- Run ONCE in the Supabase SQL editor against the same Postgres the auth
-- service uses. gen_random_uuid() is provided by the built-in pgcrypto in
-- Supabase, so no extension setup is needed.
--
-- DESIGN NOTE: user_id deliberately has NO foreign key to a users table. It
-- just stores the JWT "sub" UUID, so this scoring service stays decoupled from
-- the auth service's schema (no cross-service migration coupling).

-- Parent: one row per completed interview.
CREATE TABLE IF NOT EXISTS interviews (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL,
    created_at    timestamptz DEFAULT now(),
    total_score   float,
    overall_band  text,
    num_questions int,
    num_skipped   int
);

-- Child: one row per answered (or skipped) question.
-- ON DELETE CASCADE so removing an interview cleans up its answers.
CREATE TABLE IF NOT EXISTS interview_answers (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    interview_id  uuid REFERENCES interviews(id) ON DELETE CASCADE,
    question_id   text,
    question_type text,
    final_score   float,
    band          text,
    dimensions    jsonb,
    feedback      jsonb,
    was_skipped   bool
);

-- History lookups are "this user's interviews, newest first" — index both.
CREATE INDEX IF NOT EXISTS idx_interviews_user_created
    ON interviews (user_id, created_at DESC);

-- Detail lookups join answers back to their interview.
CREATE INDEX IF NOT EXISTS idx_interview_answers_interview
    ON interview_answers (interview_id);
