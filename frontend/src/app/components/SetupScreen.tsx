import React, { useState } from 'react';
import { motion } from 'motion/react';
import { Plane, Zap, ChevronDown, Lock } from 'lucide-react';

import type { SessionConfig } from '../../lib/api';

/**
 * "Configure your mock interview" setup screen (Phase A2).
 *
 * Owns the candidate's selections and, on Commence, emits a SessionConfig whose
 * fields are the EXACT backend param values (interview_type/difficulty strings,
 * numeric question_count, and the chosen airline/aircraft/experience strings).
 *
 * The option lists below are intentionally kept as plain constants so they can be
 * trimmed/extended to match the question dataset later WITHOUT touching the JSX.
 */

// ── Editable option catalogues ──────────────────────────────────────────────
interface InterviewTypeOption {
  label: string;
  value: NonNullable<SessionConfig['interview_type']>;
  enabled: boolean;
}

const INTERVIEW_TYPES: InterviewTypeOption[] = [
  { label: 'HR / Personal', value: 'hr_personal', enabled: true },
  { label: 'Technical', value: 'technical', enabled: true },
  // Recognised by the backend but NOT wired yet — rendered, but unselectable.
  { label: 'Sim Check Debrief', value: 'sim_check_debrief', enabled: false },
  { label: 'Group Exercise', value: 'group_exercise', enabled: false },
];

const AIRLINES = [
  'IndiGo',
  'Air India',
  'SpiceJet',
  'Akasa Air',
  'Emirates',
  'Generic Airline',
];

// First entry ("Any / General") means "no aircraft filter" → sent as null.
const AIRCRAFT_TYPES = [
  'Any / General',
  'Airbus A320 Family',
  'Boeing 737',
  'ATR 72',
  'Boeing 777',
  'Boeing 787 Dreamliner',
  'Airbus A350',
];

const EXPERIENCE_LEVELS = [
  'CPL Fresh (200 hrs)',
  'CPL + Type Rating',
  'First Officer (<1500 hrs)',
  'Senior First Officer (1500+ hrs)',
  'Command / Captain',
];

const DIFFICULTIES: { label: string; value: string }[] = [
  { label: 'Standard', value: 'standard' },
  { label: 'Tough', value: 'tough' },
  { label: 'Friendly', value: 'friendly' },
];

const QUESTION_COUNTS: { count: number; label: string }[] = [
  { count: 5, label: 'Quick Drill' },
  { count: 8, label: 'Standard' },
  { count: 12, label: 'Full Panel' },
];

const AIRCRAFT_ANY = AIRCRAFT_TYPES[0]; // "Any / General" sentinel

interface SetupScreenProps {
  /** Called with the mapped backend config when the user commits. */
  onCommence: (config: SessionConfig) => void;
  /** Optional inline error (e.g. a failed silent sign-in) shown above the form. */
  error?: string;
}

// ── Small presentational helpers (keep the tactical look consistent) ──────────
function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs font-mono text-cyan-400/80 uppercase tracking-widest mb-3">
      {children}
    </label>
  );
}

function Pill({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        'px-4 py-2.5 rounded-sm font-mono text-sm tracking-wide transition-all border',
        disabled
          ? 'border-cyan-500/10 bg-cyan-950/20 text-cyan-500/30 cursor-not-allowed'
          : active
            ? 'border-cyan-400 bg-cyan-500/20 text-cyan-100 shadow-[0_0_15px_rgba(6,182,212,0.25)]'
            : 'border-cyan-500/30 bg-[#030712]/60 text-cyan-300/80 hover:border-cyan-400/70 hover:text-cyan-100',
      ].join(' ')}
    >
      {children}
    </button>
  );
}

function Dropdown({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none bg-[#030712]/80 border border-cyan-500/30 rounded-sm px-4 py-3 pr-10 text-cyan-50 font-mono text-sm focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition-all cursor-pointer"
      >
        {options.map((opt) => (
          <option key={opt} value={opt} className="bg-[#030712] text-cyan-50">
            {opt}
          </option>
        ))}
      </select>
      <ChevronDown className="w-4 h-4 text-cyan-400/60 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
    </div>
  );
}

export default function SetupScreen({ onCommence, error }: SetupScreenProps) {
  const [interviewType, setInterviewType] = useState<string>('technical');
  const [airline, setAirline] = useState<string>(AIRLINES[AIRLINES.length - 1]); // Generic Airline
  const [aircraft, setAircraft] = useState<string>(AIRCRAFT_ANY);
  const [experience, setExperience] = useState<string>(EXPERIENCE_LEVELS[0]);
  const [difficulty, setDifficulty] = useState<string>('standard');
  const [questionCount, setQuestionCount] = useState<number>(8);

  function handleCommence() {
    // Map UI selections → EXACT backend params. "Any / General" aircraft means
    // no filter, so it is sent as null rather than a literal string.
    onCommence({
      interview_type: interviewType,
      airline,
      aircraft_type: aircraft === AIRCRAFT_ANY ? null : aircraft,
      experience,
      difficulty,
      question_count: questionCount,
    });
  }

  // The two unselectable types are never assignable to `interviewType`, so a
  // valid (enabled) interview type is always chosen — but guard anyway.
  const canCommence = INTERVIEW_TYPES.some(
    (t) => t.enabled && t.value === interviewType,
  );

  return (
    <motion.div
      key="setup"
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -40 }}
      className="max-w-3xl mx-auto mt-8"
    >
      <div className="relative bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-1 shadow-[0_0_50px_rgba(6,182,212,0.1)]">
        {/* Tech corners */}
        <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan-400" />
        <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan-400" />
        <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-cyan-400" />
        <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-cyan-400" />

        <div className="p-8 sm:p-10 relative z-10">
          {/* Header */}
          <div className="flex items-center gap-4 mb-2">
            <div className="w-12 h-12 bg-cyan-500/10 rounded-full flex items-center justify-center border border-cyan-500/30 shadow-[0_0_20px_rgba(6,182,212,0.25)] shrink-0">
              <Plane className="w-6 h-6 text-cyan-400" />
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold text-white uppercase tracking-widest font-mono">
              Configure your mock interview
            </h1>
          </div>
          <p className="text-cyan-100/60 text-sm font-mono leading-relaxed mb-8 ml-16">
            Set up a realistic, airline-selection-style mock interview. Pick the
            panel, airline, and aircraft to tailor the questions to your target.
          </p>

          {error && (
            <div className="mb-8 flex items-start gap-2 px-4 py-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-xs font-mono">
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-8">
            {/* Interview Type */}
            <div>
              <FieldLabel>Interview Type</FieldLabel>
              <div className="flex flex-wrap gap-3">
                {INTERVIEW_TYPES.map((t) => (
                  <div key={t.value} className="relative">
                    <Pill
                      active={interviewType === t.value}
                      disabled={!t.enabled}
                      onClick={t.enabled ? () => setInterviewType(t.value) : undefined}
                    >
                      <span className="flex items-center gap-2">
                        {!t.enabled && <Lock className="w-3 h-3" />}
                        {t.label}
                      </span>
                    </Pill>
                    {!t.enabled && (
                      <span className="absolute -top-2 -right-2 px-1.5 py-0.5 rounded-sm bg-cyan-950 border border-cyan-500/30 text-[9px] font-mono uppercase tracking-wider text-cyan-400/70">
                        Coming soon
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Airline */}
            <div>
              <FieldLabel>Airline</FieldLabel>
              <div className="flex flex-wrap gap-3">
                {AIRLINES.map((a) => (
                  <Pill key={a} active={airline === a} onClick={() => setAirline(a)}>
                    {a}
                  </Pill>
                ))}
              </div>
            </div>

            {/* Aircraft + Experience (dropdowns) */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <FieldLabel>Aircraft Type</FieldLabel>
                <Dropdown value={aircraft} onChange={setAircraft} options={AIRCRAFT_TYPES} />
              </div>
              <div>
                <FieldLabel>Your Experience</FieldLabel>
                <Dropdown
                  value={experience}
                  onChange={setExperience}
                  options={EXPERIENCE_LEVELS}
                />
              </div>
            </div>

            {/* Difficulty */}
            <div>
              <FieldLabel>Difficulty</FieldLabel>
              <div className="flex flex-wrap gap-3">
                {DIFFICULTIES.map((d) => (
                  <Pill
                    key={d.value}
                    active={difficulty === d.value}
                    onClick={() => setDifficulty(d.value)}
                  >
                    {d.label}
                  </Pill>
                ))}
              </div>
            </div>

            {/* Questions */}
            <div>
              <FieldLabel>Questions</FieldLabel>
              <div className="flex flex-wrap gap-3">
                {QUESTION_COUNTS.map((q) => (
                  <Pill
                    key={q.count}
                    active={questionCount === q.count}
                    onClick={() => setQuestionCount(q.count)}
                  >
                    {q.count} — {q.label}
                  </Pill>
                ))}
              </div>
            </div>
          </div>

          {/* Commence */}
          <div className="mt-10 pt-6 border-t border-cyan-500/20 flex justify-end">
            <button
              type="button"
              onClick={handleCommence}
              disabled={!canCommence}
              className="relative px-10 py-4 bg-cyan-500 text-[#030712] font-mono font-bold text-base rounded-sm overflow-hidden group shadow-[0_0_20px_rgba(6,182,212,0.4)] hover:shadow-[0_0_40px_rgba(6,182,212,0.6)] transition-all disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <span className="relative z-10 flex items-center gap-3 uppercase tracking-widest">
                Commence Interview <Zap className="w-5 h-5" />
              </span>
              <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300" />
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
