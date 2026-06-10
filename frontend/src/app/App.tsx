import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Mic, Plane, ArrowRight, CheckCircle, RefreshCcw, AlertCircle, Scan, Activity, Camera, Eye, Brain, Cpu, Radar, Zap, ChevronDown, ChevronRight } from 'lucide-react';

import {
  API_BASE_URL,
  getHealth,
  devLogin,
  startSession,
  submitAnswer,
  completeSession,
  isAuthError,
  ApiError,
  type Question,
  type AnswerResult,
  type SessionReport,
  type SessionConfig,
} from '../lib/api';
import { getToken as readStoredToken, setToken as storeToken, looksLikeJwt } from '../lib/token';
import { speak, stopSpeaking } from '../lib/speech';
import { useSpeechRecognition } from '../lib/useSpeechRecognition';
import { useFaceTracking } from '../lib/useFaceTracking';
import { useVoiceAnalysis } from '../lib/useVoiceAnalysis';
import DeviceCheck from './components/DeviceCheck';
import SetupScreen from './components/SetupScreen';
import { Button } from './components/ui/button';
import { Alert, AlertDescription } from './components/ui/alert';

type AppState =
  | 'AUTH_LOADING'
  | 'LOGIN'
  | 'SETUP'
  | 'CONSENT'
  | 'DEVICE_CHECK'
  | 'INTRO'
  | 'INTERVIEW'
  | 'SCORECARD';

// ── Phase A2 auth gating ──
// The user-facing login is disabled: on load the app SILENTLY trades a fixed dev
// code for a real server-minted token. The legacy LOGIN screen is kept in the
// code but gated behind VITE_ENABLE_LOGIN for later re-enable.
const LOGIN_ENABLED = (import.meta.env.VITE_ENABLE_LOGIN as string) === 'true';
const DEV_LOGIN_CODE = (import.meta.env.VITE_DEV_LOGIN_CODE as string) || '';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const fmtScore = (n: number | null | undefined) =>
  n == null || Number.isNaN(n) ? '—' : Number.isInteger(n) ? String(n) : n.toFixed(1);

export default function App() {
  const [appState, setAppState] = useState<AppState>('AUTH_LOADING');
  const [token, setToken] = useState('');
  const [devCode, setDevCode] = useState('');
  const [devSubmitting, setDevSubmitting] = useState(false);

  // Interview parameters chosen on the SETUP screen, passed to startSession().
  const [sessionConfig, setSessionConfig] = useState<SessionConfig>({});

  // ── session / interview state (now driven by the real backend) ──
  const [sessionToken, setSessionToken] = useState('');
  const [questions, setQuestions] = useState<Question[]>([]);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [currentAnswer, setCurrentAnswer] = useState('');
  const [timeLeft, setTimeLeft] = useState(120);
  const [results, setResults] = useState<AnswerResult[]>([]);
  const [report, setReport] = useState<SessionReport | null>(null);
  // Candidate's own answer text, kept per question_id so the scorecard can show
  // it beside the model answer (the backend never echoes the submitted text).
  const [answersByQuestion, setAnswersByQuestion] = useState<Record<string, string>>({});
  // Which scorecard question row is expanded (collapsible review).
  const [expandedQ, setExpandedQ] = useState<string | null>(null);

  const [isRecording, setIsRecording] = useState(false);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [warming, setWarming] = useState('');
  const [error, setError] = useState('');

  const inFlightRef = useRef(false);
  const [cameraActive, setCameraActive] = useState(false);

  const currentQuestion = questions[currentQuestionIndex];

  // ── speech-to-text: append finalized speech into the existing answer box ──
  const {
    supported: sttSupported,
    listening,
    interim,
    error: sttError,
    start: startListening,
    stop: stopListening,
  } = useSpeechRecognition({
    onFinalResult: (chunk) =>
      setCurrentAnswer((prev) => (prev ? prev.trimEnd() + ' ' : '') + chunk.trim()),
  });

  // ── face tracking → per-question behavioral_features + live UI levels (best-effort) ──
  // App owns the single <video> ref + the hook; the same element is shown in the AI panel.
  const faceVideoRef = useRef<HTMLVideoElement>(null);
  const {
    faceDetected,
    liveEyeContact,
    liveFacialConfidence,
    getQuestionMetrics,
    resetQuestionMetrics,
  } = useFaceTracking(faceVideoRef, appState === 'INTERVIEW');

  // ── voice prosody → merged into the same behavioral_features blob (best-effort) ──
  const { getQuestionVoiceMetrics, resetQuestionVoiceMetrics } = useVoiceAnalysis(
    appState === 'INTERVIEW',
  );

  // ── Auto-listen plumbing (PART 3) ──
  // Live mirrors of fast-changing values so the TTS 'end' callback (which fires
  // outside React's render flow, sometimes late) always reads CURRENT values
  // instead of a stale closure.
  const appStateRef = useRef(appState);
  appStateRef.current = appState;
  const sttSupportedRef = useRef(sttSupported);
  sttSupportedRef.current = sttSupported;
  const submittingRef = useRef(submitting);
  submittingRef.current = submitting;
  const listeningRef = useRef(listening);
  listeningRef.current = listening;
  const startListeningRef = useRef(startListening);
  startListeningRef.current = startListening;
  const activeQuestionIdRef = useRef<string | undefined>(currentQuestion?.id);
  activeQuestionIdRef.current = currentQuestion?.id;

  // After a question is read aloud, auto-start the mic — but ONLY if we're still
  // on the same question, STT is supported, and we're not mid-submit/already
  // listening. Any of those failing safely falls back to manual typing/mic.
  function maybeAutoListen(questionId: string) {
    if (!sttSupportedRef.current) return;                 // non-Chrome: typing only
    if (appStateRef.current !== 'INTERVIEW') return;      // left the interview
    if (activeQuestionIdRef.current !== questionId) return; // question changed / cancelled
    if (submittingRef.current) return;                    // scoring in flight
    if (listeningRef.current) return;                     // already listening
    startListeningRef.current();
  }

  // Read a question aloud, then hand off to auto-listen when the TTS ends. Used
  // by both the per-question effect and the manual Replay button, so a skipped/
  // blocked auto-play can still be recovered via Replay.
  function playQuestion(q: { id: string; question: string }) {
    speak(q.question, () => maybeAutoListen(q.id));
  }

  // ── Silent sign-in on load (user-facing login disabled) ──
  // Reuse a token from this tab if present; otherwise trade the fixed dev code
  // for a real token, then open the SETUP screen. On failure show a friendly
  // inline error (and fall back to the gated LOGIN screen only if re-enabled).
  async function bootAuth() {
    setError('');
    const existing = readStoredToken();
    if (existing) {
      setToken(existing);
      setAppState('SETUP');
      return;
    }
    if (LOGIN_ENABLED) {
      setAppState('LOGIN');
      return;
    }
    if (!DEV_LOGIN_CODE) {
      setAppState('AUTH_LOADING');
      setError('Sign-in is not configured (VITE_DEV_LOGIN_CODE is missing).');
      return;
    }
    setAppState('AUTH_LOADING');
    try {
      const { access_token } = await devLogin(DEV_LOGIN_CODE);
      storeToken(access_token);
      setToken(access_token);
      setAppState('SETUP');
    } catch (err: any) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Could not establish a secure session. Please retry.',
      );
      setAppState('AUTH_LOADING');
    }
  }

  useEffect(() => {
    bootAuth();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── single webcam stream: feeds the on-screen preview AND MediaPipe face tracking ──
  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      if (faceVideoRef.current) {
        faceVideoRef.current.srcObject = stream;
      }
      setCameraActive(true);
    } catch (err) {
      console.error('Failed to access camera', err);
      setCameraActive(false);
    }
  };

  const stopCamera = () => {
    if (faceVideoRef.current && faceVideoRef.current.srcObject) {
      const stream = faceVideoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach((track) => track.stop());
      faceVideoRef.current.srcObject = null;
    }
    setCameraActive(false);
  };

  useEffect(() => {
    if (appState === 'INTERVIEW') {
      startCamera();
    } else {
      stopCamera();
    }
    return () => stopCamera();
  }, [appState]);

  // ── auth handling ──
  function resetSession() {
    setSessionToken('');
    setQuestions([]);
    setCurrentQuestionIndex(0);
    setResults([]);
    setReport(null);
    setCurrentAnswer('');
    setAnswersByQuestion({});
    setExpandedQ(null);
    setError('');
  }

  function handleAuthError() {
    setToken('');
    storeToken('');
    resetSession();
    setSubmitting(false);
    inFlightRef.current = false;
    if (LOGIN_ENABLED) {
      setError('Your token was rejected (expired or invalid). Paste a fresh one.');
      setAppState('LOGIN');
    } else {
      // Login UI is disabled — silently re-establish a token and return to setup.
      setError('Session expired — re-establishing a secure link…');
      bootAuth();
    }
  }

  function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    const t = token.trim();
    if (!t) return;
    storeToken(t);
    setError('');
    setAppState('DEVICE_CHECK');
  }

  // ── DEV-ONLY: trade a fixed code for a server-minted token ──
  async function handleDevLogin(e: React.FormEvent) {
    e.preventDefault();
    const code = devCode.trim();
    if (!code || devSubmitting) return;
    setDevSubmitting(true);
    setError('');
    try {
      const { access_token } = await devLogin(code);
      storeToken(access_token);
      setToken(access_token);
      setAppState('DEVICE_CHECK');
    } catch (err: any) {
      setError(err instanceof ApiError ? err.message : 'Dev login failed.');
    } finally {
      setDevSubmitting(false);
    }
  }

  // ── start (with cold-start warm-up), real questions from the API ──
  async function warmUp() {
    const deadline = Date.now() + 90000;
    let attempt = 0;
    while (Date.now() < deadline) {
      attempt += 1;
      try {
        const h = await getHealth();
        if (h?.status === 'ok') return true;
      } catch {
        /* still waking — retry */
      }
      setWarming(`Waking the scoring service (cold start, up to ~60s)… attempt ${attempt}`);
      await sleep(3000);
    }
    return false;
  }

  async function handleStartInterview() {
    setStarting(true);
    setError('');
    setWarming('');
    try {
      await warmUp(); // best-effort; we still try to start even if it times out
      setWarming('');
      const data = await startSession(token, sessionConfig);
      const qs = data.questions || [];
      if (qs.length === 0) {
        setError('No questions were returned for this session.');
        return;
      }
      setSessionToken(data.session_token);
      setQuestions(qs);
      setCurrentQuestionIndex(0);
      setResults([]);
      setReport(null);
      setCurrentAnswer('');
      setIsRecording(false);
      setTimeLeft(qs[0].time_limit_seconds || 90);
      setAppState('INTERVIEW');
    } catch (err: any) {
      if (isAuthError(err)) return handleAuthError();
      setError(err?.message || 'Could not start the interview.');
    } finally {
      setStarting(false);
      setWarming('');
    }
  }

  // ── submit / skip one answer → real score, then advance or finalize ──
  async function submitCurrent(wasSkipped: boolean) {
    if (inFlightRef.current || submitting || !currentQuestion) return;
    if (!wasSkipped && !currentAnswer.trim()) return;

    stopListening(); // end voice capture before scoring this answer

    inFlightRef.current = true;
    setSubmitting(true);
    setError('');

    const q = currentQuestion;
    const limit = q.time_limit_seconds || 90;

    // Remember what the candidate actually answered, for the scorecard review.
    const candidateText = wasSkipped ? '' : currentAnswer.trim();
    setAnswersByQuestion((prev) => ({ ...prev, [q.id]: candidateText }));

    // Snapshot this question's camera + voice metrics; null when neither produced data.
    const cam = getQuestionMetrics();
    const words = currentAnswer.trim() ? currentAnswer.trim().split(/\s+/).length : 0;
    const voice = getQuestionVoiceMetrics(words);
    const merged = { ...cam, ...voice };
    const behavioral_features = Object.keys(merged).length ? merged : null;
    resetQuestionMetrics();
    resetQuestionVoiceMetrics();

    try {
      const result = await submitAnswer(token, {
        session_token: sessionToken,
        question_id: q.id,
        student_answer_text: candidateText,
        time_taken_seconds: Math.max(0, limit - timeLeft),
        was_skipped: wasSkipped,
        behavioral_features,
      });

      const nextResults = [...results, result];
      setResults(nextResults);

      if (currentQuestionIndex < questions.length - 1) {
        const ni = currentQuestionIndex + 1;
        setCurrentQuestionIndex(ni);
        setCurrentAnswer('');
        setIsRecording(false);
        setTimeLeft(questions[ni].time_limit_seconds || 90);
        setSubmitting(false);
        inFlightRef.current = false;
      } else {
        await finalize(nextResults);
      }
    } catch (err: any) {
      if (isAuthError(err)) return handleAuthError();
      // Stay on the question so the user can retry.
      setError(err?.message || 'Scoring failed. Try submitting again.');
      setSubmitting(false);
      inFlightRef.current = false;
    }
  }

  async function finalize(allResults: AnswerResult[]) {
    try {
      const rep = await completeSession(token, sessionToken, allResults);
      setReport(rep);
      setAppState('SCORECARD');
    } catch (err: any) {
      if (isAuthError(err)) return handleAuthError();
      setError(err?.message || 'Could not finalize the interview. Try again.');
    } finally {
      setSubmitting(false);
      inFlightRef.current = false;
    }
  }

  const handleSubmitAnswer = () => submitCurrent(false);
  const handleSkip = () => submitCurrent(true);

  function handleRestart() {
    resetSession();
    setAppState('SETUP');
  }

  // ── countdown (frozen while a score is in flight) ──
  useEffect(() => {
    if (appState !== 'INTERVIEW' || submitting) return;
    const timer = setInterval(() => {
      setTimeLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(timer);
  }, [appState, submitting, currentQuestionIndex]);

  // ── auto-submit on expiry: empty answer counts as a skip ──
  useEffect(() => {
    if (appState === 'INTERVIEW' && timeLeft === 0 && !inFlightRef.current && !submitting) {
      submitCurrent(currentAnswer.trim().length === 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeLeft, appState]);

  // ── read each new question aloud (TTS); auto-listen on end; cancel on change ──
  useEffect(() => {
    if (appState !== 'INTERVIEW' || !currentQuestion) return;
    playQuestion(currentQuestion);
    return () => stopSpeaking();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appState, currentQuestion?.id]);

  // ── stop voice capture (and clear the interim preview) on question change/unmount ──
  useEffect(() => {
    return () => stopListening();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentQuestionIndex]);

  // ── reset behavioral accumulators (camera + voice) when a new question becomes current ──
  useEffect(() => {
    resetQuestionMetrics();
    resetQuestionVoiceMetrics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentQuestionIndex]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // Real report-derived values for the scorecard.
  const totalScore = report?.total_score ?? 0;
  const passed = totalScore > 60;
  const perQuestion = report?.per_question ?? [];

  // Scorecard joins (by question_id): question text, the answer the candidate
  // gave, the per-answer feedback, and the post-interview model answer.
  const questionTextById: Record<string, string> = {};
  for (const q of questions) questionTextById[q.id] = q.question;
  const resultById: Record<string, AnswerResult> = {};
  for (const r of results) resultById[r.question_id] = r;
  const modelAnswers = report?.model_answers ?? {};

  // Futuristic Background Grid
  const GridBackground = () => (
    <div className="fixed inset-0 pointer-events-none z-[-1] overflow-hidden bg-[#030712]">
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#0ea5e91a_1px,transparent_1px),linear-gradient(to_bottom,#0ea5e91a_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_60%_at_50%_50%,#000_70%,transparent_100%)]" />
      <motion.div
        animate={{ y: ['-100%', '100%'] }}
        transition={{ repeat: Infinity, duration: 8, ease: 'linear' }}
        className="absolute top-0 left-0 right-0 h-32 bg-gradient-to-b from-transparent via-cyan-500/10 to-transparent blur-xl"
      />
    </div>
  );

  return (
    <div className="min-h-screen text-cyan-50 font-sans selection:bg-cyan-500/30 overflow-x-hidden">
      <GridBackground />

      {/* HUD Header */}
      <header className="border-b border-cyan-500/20 bg-[#030712]/60 backdrop-blur-xl sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="relative w-10 h-10 flex items-center justify-center">
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 10, repeat: Infinity, ease: 'linear' }}
                className="absolute inset-0 border border-cyan-500/30 rounded-full border-t-cyan-500"
              />
              <Plane className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <div className="font-bold text-lg tracking-widest text-cyan-50 uppercase drop-shadow-[0_0_8px_rgba(34,211,238,0.5)]">
                We One Aviation
              </div>
              <div className="text-[10px] text-cyan-500 font-mono tracking-widest uppercase">
                Tactical AI Assessment v6.1
              </div>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="hidden sm:flex items-center gap-2 font-mono text-xs text-cyan-400/70">
              <Cpu className="w-4 h-4" />
              <span>SYS_ONLINE</span>
            </div>
            {token && appState !== 'LOGIN' && (
              <div className="px-3 py-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-xs font-mono flex items-center gap-2 shadow-[0_0_10px_rgba(16,185,129,0.2)]">
                <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                SECURE_LINK
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8 sm:py-12">
        <AnimatePresence mode="wait">

          {appState === 'AUTH_LOADING' && (
            <motion.div
              key="auth-loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="max-w-md mx-auto mt-28 text-center"
            >
              {error ? (
                <div className="space-y-6">
                  <div className="flex items-start gap-2 px-4 py-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-sm font-mono text-left">
                    <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                    <span>{error}</span>
                  </div>
                  <button
                    onClick={bootAuth}
                    className="px-8 py-3 bg-cyan-500/10 border border-cyan-400 text-cyan-300 hover:bg-cyan-500 hover:text-[#030712] font-mono font-bold text-sm uppercase tracking-widest transition-all rounded-sm"
                  >
                    Retry Sign-In
                  </button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-4 text-cyan-300 font-mono">
                  <span className="w-8 h-8 rounded-full border-2 border-cyan-500/40 border-t-cyan-300 animate-spin" />
                  <span className="text-sm uppercase tracking-widest">
                    Establishing secure link…
                  </span>
                </div>
              )}
            </motion.div>
          )}

          {appState === 'SETUP' && (
            <SetupScreen
              onCommence={(cfg) => {
                setSessionConfig(cfg);
                setError('');
                setAppState('CONSENT');
              }}
            />
          )}

          {appState === 'CONSENT' && (
            <motion.div
              key="consent"
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -40 }}
              className="max-w-2xl mx-auto mt-16"
            >
              <div className="relative bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-1 shadow-[0_0_50px_rgba(6,182,212,0.1)]">
                <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan-400" />
                <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan-400" />
                <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-cyan-400" />
                <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-cyan-400" />

                <div className="p-8 sm:p-10 relative z-10">
                  <div className="flex items-center justify-center gap-3 mb-6">
                    <Camera className="w-7 h-7 text-cyan-400" />
                    <Mic className="w-7 h-7 text-cyan-400" />
                  </div>
                  <h2 className="text-xl sm:text-2xl font-bold text-center text-white mb-6 uppercase tracking-widest font-mono">
                    Camera &amp; microphone notice
                  </h2>
                  <p className="text-cyan-100/80 text-center leading-relaxed font-mono text-sm mb-10">
                    This mock interview uses your camera and microphone to analyse
                    your delivery (eye contact, expression, voice). No video or
                    audio is recorded, stored, or sent — only the derived scores.
                    You can answer by typing instead.
                  </p>

                  <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
                    <button
                      onClick={() => {
                        setError('');
                        setAppState('DEVICE_CHECK');
                      }}
                      className="px-8 py-3.5 bg-cyan-500 text-[#030712] font-mono font-bold text-sm uppercase tracking-widest rounded-sm hover:shadow-[0_0_30px_rgba(6,182,212,0.5)] transition-all flex items-center gap-2"
                    >
                      <CheckCircle className="w-4 h-4" /> I understand — continue
                    </button>
                    <button
                      onClick={() => setAppState('SETUP')}
                      className="text-cyan-500/60 hover:text-cyan-400 font-mono text-sm px-6 py-3.5 transition-colors uppercase tracking-widest"
                    >
                      [ Back to setup ]
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {LOGIN_ENABLED && appState === 'LOGIN' && (
            <motion.div
              key="login"
              initial={{ opacity: 0, scale: 0.9, filter: 'blur(10px)' }}
              animate={{ opacity: 1, scale: 1, filter: 'blur(0px)' }}
              exit={{ opacity: 0, scale: 1.1, filter: 'blur(10px)' }}
              className="max-w-md mx-auto mt-20"
            >
              <div className="relative bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-lg p-1 shadow-[0_0_40px_rgba(6,182,212,0.15)] overflow-hidden">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/10 via-transparent to-blue-600/10" />

                {/* Tech Corners */}
                <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-cyan-400" />
                <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-cyan-400" />
                <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-cyan-400" />
                <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-cyan-400" />

                <div className="p-8 relative z-10">
                  <div className="flex items-center justify-center mb-6">
                    <Scan className="w-12 h-12 text-cyan-400 animate-pulse" />
                  </div>
                  <h2 className="text-2xl font-bold text-center text-white mb-2 font-mono uppercase tracking-widest">Auth Required</h2>
                  <p className="text-cyan-400/60 text-center mb-8 text-sm font-mono">
                    Paste your access token (eyJ…) to establish a secure link.
                  </p>

                  {error && (
                    <div className="mb-6 flex items-start gap-2 px-4 py-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-xs font-mono">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                      <span>{error}</span>
                    </div>
                  )}

                  {/* DEV-ONLY: fixed-code sign-in. Only works when the server has
                      DEV_LOGIN_ENABLED set; otherwise the route 404s. */}
                  <form onSubmit={handleDevLogin} className="space-y-4 mb-6">
                    <div className="relative group">
                      <div className="absolute inset-0 bg-cyan-500/20 blur-md rounded-lg opacity-0 group-focus-within:opacity-100 transition-opacity" />
                      <input
                        type="number"
                        inputMode="numeric"
                        value={devCode}
                        onChange={(e) => setDevCode(e.target.value)}
                        placeholder="DEV CODE (6 DIGITS)"
                        className="relative w-full bg-[#030712] border border-cyan-500/30 rounded-lg px-4 py-4 text-cyan-50 font-mono placeholder:text-cyan-700 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition-all tracking-[0.3em] text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={!devCode.trim() || devSubmitting}
                      className="w-full bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/50 hover:border-cyan-400 text-cyan-300 hover:text-cyan-100 font-mono font-bold py-3 rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {devSubmitting ? 'SIGNING IN…' : 'SIGN IN'}
                    </button>
                  </form>

                  <div className="flex items-center gap-3 mb-6">
                    <div className="h-px flex-1 bg-cyan-500/20" />
                    <span className="text-[10px] font-mono text-cyan-500/40 uppercase tracking-widest">or paste token</span>
                    <div className="h-px flex-1 bg-cyan-500/20" />
                  </div>

                  <form onSubmit={handleLogin} className="space-y-6">
                    <div className="relative group">
                      <div className="absolute inset-0 bg-cyan-500/20 blur-md rounded-lg opacity-0 group-focus-within:opacity-100 transition-opacity" />
                      <input
                        type="text"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        placeholder="PASTE ACCESS TOKEN (eyJ...)"
                        className="relative w-full bg-[#030712] border border-cyan-500/30 rounded-lg px-4 py-4 text-cyan-50 font-mono placeholder:text-cyan-700 focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400 transition-all tracking-wider text-center"
                        required
                      />
                    </div>
                    {token.trim() && !looksLikeJwt(token.trim()) && (
                      <p className="text-amber-400/70 text-center text-[11px] font-mono -mt-2">
                        That doesn’t look like an access token (eyJ…). It will be rejected by the server.
                      </p>
                    )}
                    <button
                      type="submit"
                      className="w-full bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/50 hover:border-cyan-400 text-cyan-300 hover:text-cyan-100 font-mono font-bold py-4 rounded-lg transition-all flex items-center justify-center gap-3 group relative overflow-hidden"
                    >
                      <span className="relative z-10 flex items-center gap-2">
                        INITIALIZE <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                      </span>
                      <motion.div
                        className="absolute inset-0 bg-cyan-500/20"
                        initial={{ x: '-100%' }}
                        whileHover={{ x: '0%' }}
                        transition={{ duration: 0.3 }}
                      />
                    </button>
                  </form>
                </div>
              </div>
            </motion.div>
          )}

          {appState === 'DEVICE_CHECK' && (
            <motion.div
              key="devicecheck"
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -40 }}
            >
              <DeviceCheck onReady={() => setAppState('INTRO')} />
            </motion.div>
          )}

          {appState === 'INTRO' && (
            <motion.div
              key="intro"
              initial={{ opacity: 0, y: 40 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -40 }}
              className="mt-10"
            >
              <div className="relative max-w-3xl mx-auto bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-1 shadow-[0_0_50px_rgba(6,182,212,0.1)]">
                <div className="p-10 relative z-10 text-center">
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: 'spring', delay: 0.2 }}
                    className="w-20 h-20 bg-cyan-500/10 rounded-full flex items-center justify-center mx-auto mb-6 border border-cyan-500/30 shadow-[0_0_30px_rgba(6,182,212,0.3)]"
                  >
                    <Plane className="w-10 h-10 text-cyan-400" />
                  </motion.div>

                  <h1 className="text-4xl font-bold text-white mb-6 uppercase tracking-widest font-mono">
                    System Ready
                  </h1>

                  <p className="text-cyan-100/70 text-lg leading-relaxed mb-10 max-w-2xl mx-auto font-mono">
                    <span className="text-cyan-400">&gt;</span> Candidate environment verified.<br />
                    <span className="text-cyan-400">&gt;</span> AI Face/Eye Tracking subsystem online.<br />
                    <span className="text-cyan-400">&gt;</span> You will be evaluated through a live, AI-scored assessment.<br />
                    <span className="text-cyan-400 animate-pulse">&gt; Awaiting pilot initiation...</span>
                  </p>

                  {warming && (
                    <div className="mb-6 max-w-xl mx-auto flex items-center justify-center gap-3 px-4 py-3 rounded-lg border border-cyan-500/30 bg-cyan-500/10 text-cyan-300 text-xs font-mono">
                      <span className="w-3 h-3 rounded-full border-2 border-cyan-500/40 border-t-cyan-300 animate-spin" />
                      {warming}
                    </div>
                  )}
                  {error && (
                    <div className="mb-6 max-w-xl mx-auto flex items-start gap-2 px-4 py-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-xs font-mono">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                      <span>{error}</span>
                    </div>
                  )}

                  <div className="flex flex-col sm:flex-row items-center justify-center gap-6">
                    <button
                      onClick={handleStartInterview}
                      disabled={starting}
                      className="relative px-10 py-4 bg-cyan-500 text-[#030712] font-mono font-bold text-lg rounded-sm overflow-hidden group shadow-[0_0_20px_rgba(6,182,212,0.4)] hover:shadow-[0_0_40px_rgba(6,182,212,0.6)] transition-all disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                      <span className="relative z-10 flex items-center gap-3">
                        {starting ? 'INITIALIZING…' : 'ENGAGE PROTOCOL'} <Zap className="w-5 h-5" />
                      </span>
                      <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-300" />
                    </button>

                    <button
                      onClick={() => {
                        resetSession();
                        if (LOGIN_ENABLED) {
                          storeToken('');
                          setToken('');
                          setAppState('LOGIN');
                        } else {
                          // Login UI disabled — keep the token, return to setup.
                          setAppState('SETUP');
                        }
                      }}
                      disabled={starting}
                      className="text-cyan-500/60 hover:text-cyan-400 font-mono text-sm px-6 py-4 transition-colors uppercase tracking-widest disabled:opacity-50"
                    >
                      {LOGIN_ENABLED ? '[ Abort / Re-Auth ]' : '[ Back to Setup ]'}
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {appState === 'INTERVIEW' && currentQuestion && (
            <motion.div
              key="interview"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-8 h-full"
            >
              {/* Left Column: Interview Question & Input */}
              <div className="flex flex-col gap-6">
                <div className="bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-6 md:p-8 relative overflow-hidden flex-1 shadow-[0_0_30px_rgba(6,182,212,0.05)]">
                  {/* Decorative Elements */}
                  <div className="absolute top-0 right-0 p-4 opacity-20 pointer-events-none">
                    <Radar className="w-32 h-32 text-cyan-500" />
                  </div>

                  <div className="flex justify-between items-end border-b border-cyan-500/20 pb-6 mb-8">
                    <div>
                      <div className="text-cyan-500/60 font-mono text-xs uppercase tracking-widest mb-2 flex items-center gap-2">
                        <Cpu className="w-3 h-3" /> Module {currentQuestionIndex + 1} // {questions.length}
                      </div>
                      <div className="inline-block px-3 py-1 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 font-mono text-sm rounded shadow-[0_0_15px_rgba(6,182,212,0.15)] uppercase">
                        {[currentQuestion.question_type, currentQuestion.category].filter(Boolean).join(' · ') || 'ASSESSMENT'}
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-cyan-500/60 font-mono text-xs uppercase tracking-widest mb-2">
                        Time Remaining
                      </div>
                      <div className={`font-mono text-3xl font-bold tracking-wider ${timeLeft <= 30 ? 'text-red-500 animate-pulse drop-shadow-[0_0_10px_rgba(239,68,68,0.5)]' : 'text-cyan-300 drop-shadow-[0_0_10px_rgba(103,232,249,0.3)]'}`}>
                        {formatTime(timeLeft)}
                      </div>
                    </div>
                  </div>

                  <motion.h2
                    key={currentQuestionIndex}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="text-2xl sm:text-3xl font-semibold text-white leading-tight mb-10"
                  >
                    {currentQuestion.question}
                  </motion.h2>

                  <div className="-mt-6 mb-8">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => playQuestion(currentQuestion)}
                    >
                      🔊 Replay
                    </Button>
                  </div>

                  <div className="space-y-4 flex-1">
                    <div className="flex justify-between items-center mb-2">
                      <label className="text-xs font-mono text-cyan-400/80 uppercase tracking-widest">
                        Response Input
                      </label>
                      {/* Speech-to-text: append spoken answer into the box (Chrome/Edge only) */}
                      {sttSupported ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => (listening ? stopListening() : startListening())}
                          disabled={submitting}
                          className={listening ? 'border-red-500/50 text-red-400 animate-pulse' : ''}
                        >
                          <Mic className="w-3.5 h-3.5" />
                          {listening ? '⏹ Stop' : '🎤 Speak'}
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled
                          title="Voice input needs Google Chrome"
                        >
                          <Mic className="w-3.5 h-3.5" />
                          Voice input needs Google Chrome
                        </Button>
                      )}
                    </div>

                    <div className="relative group h-[250px]">
                      <div className="absolute top-0 left-0 w-2 h-2 border-t-2 border-l-2 border-cyan-400 z-10" />
                      <div className="absolute bottom-0 right-0 w-2 h-2 border-b-2 border-r-2 border-cyan-400 z-10" />

                      <textarea
                        value={currentAnswer}
                        onChange={(e) => setCurrentAnswer(e.target.value)}
                        placeholder="Awaiting input..."
                        disabled={submitting}
                        className="w-full h-full bg-[#030712]/80 border border-cyan-500/20 p-5 text-cyan-50 font-mono placeholder:text-cyan-800/50 focus:outline-none focus:border-cyan-400 focus:bg-[#030712] transition-all resize-none shadow-inner custom-scrollbar disabled:opacity-60"
                      />
                    </div>

                    {/* Live (non-final) speech preview while listening */}
                    {listening && interim && (
                      <p className="text-xs font-mono text-cyan-500/50 italic truncate">
                        {interim}
                      </p>
                    )}

                    {/* Friendly voice-input error (typing still works) */}
                    {sttError && (
                      <Alert variant="destructive">
                        <AlertDescription>{sttError}</AlertDescription>
                      </Alert>
                    )}
                  </div>

                  {error && (
                    <div className="mt-6 flex items-start gap-2 px-4 py-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-xs font-mono">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                      <span>{error}</span>
                    </div>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-4 mt-8 pt-6 border-t border-cyan-500/20">
                    <div className="text-xs font-mono text-cyan-500/40">
                      CHAR_COUNT: {currentAnswer.length}
                    </div>

                    <div className="flex gap-4">
                      <button
                        onClick={handleSkip}
                        disabled={submitting}
                        className="px-6 py-3 border border-cyan-500/30 text-cyan-400 font-mono text-sm uppercase tracking-widest hover:bg-cyan-500/10 transition-all rounded-sm disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        Skip
                      </button>
                      <button
                        onClick={handleSubmitAnswer}
                        disabled={!currentAnswer.trim() || submitting}
                        className="px-8 py-3 bg-cyan-500/20 border border-cyan-400 text-cyan-300 disabled:opacity-50 disabled:cursor-not-allowed font-mono text-sm font-bold uppercase tracking-widest hover:bg-cyan-500 hover:text-[#030712] transition-all rounded-sm flex items-center gap-2 shadow-[0_0_15px_rgba(6,182,212,0.2)]"
                      >
                        {submitting ? 'SCORING…' : 'Transmit'} <CheckCircle className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Column: AI Analysis & Camera */}
              <div className="flex flex-col gap-6">
                {/* AI Camera Module */}
                <div className="bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl overflow-hidden relative shadow-[0_0_30px_rgba(6,182,212,0.1)] group">
                  <div className="absolute top-2 left-2 right-2 flex justify-between z-10">
                    <div className="bg-black/50 backdrop-blur-md px-2 py-1 rounded border border-white/10 flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${cameraActive ? 'bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,1)] animate-pulse' : 'bg-red-500'}`} />
                      <span className="text-[10px] font-mono text-cyan-100">AI_VISION_ACTIVE</span>
                    </div>
                    <div className="bg-black/50 backdrop-blur-md px-2 py-1 rounded border border-white/10 flex items-center gap-1">
                      <Eye className="w-3 h-3 text-cyan-400" />
                      <span className="text-[10px] font-mono text-cyan-100">TRACKING</span>
                    </div>
                  </div>

                  {/* AI Facial Tracking Overlay */}
                  <div className="absolute inset-0 pointer-events-none z-10 border-[1px] border-cyan-500/20 m-4 rounded overflow-hidden">
                    <div className="absolute inset-0 flex items-center justify-center">
                      <motion.div
                        animate={{ scale: [1, 1.02, 0.98, 1], opacity: [0.6, 0.9, 0.6] }}
                        transition={{ repeat: Infinity, duration: 4, ease: 'easeInOut' }}
                        className="w-44 h-56 border border-cyan-400/50 rounded-lg relative"
                      >
                        <div className="absolute top-[35%] left-[25%] w-6 h-3 border border-cyan-400/60 rounded-[50%]" />
                        <div className="absolute top-[35%] right-[25%] w-6 h-3 border border-cyan-400/60 rounded-[50%]" />
                        <div className="absolute bottom-[25%] left-1/2 -translate-x-1/2 w-10 h-2 border-b-2 border-cyan-400/60 rounded-[50%]" />
                        <div className="absolute top-0 left-0 w-3 h-3 border-t-2 border-l-2 border-cyan-400" />
                        <div className="absolute top-0 right-0 w-3 h-3 border-t-2 border-r-2 border-cyan-400" />
                        <div className="absolute bottom-0 left-0 w-3 h-3 border-b-2 border-l-2 border-cyan-400" />
                        <div className="absolute bottom-0 right-0 w-3 h-3 border-b-2 border-r-2 border-cyan-400" />
                        <motion.div
                          animate={{ top: ['0%', '100%', '0%'] }}
                          transition={{ repeat: Infinity, duration: 3, ease: 'linear' }}
                          className="absolute left-0 right-0 h-[1px] bg-cyan-400/80 shadow-[0_0_10px_rgba(34,211,238,0.8)]"
                        />
                      </motion.div>
                    </div>

                    <div className="absolute top-0 bottom-0 left-1/3 w-[1px] bg-cyan-500/10" />
                    <div className="absolute top-0 bottom-0 right-1/3 w-[1px] bg-cyan-500/10" />
                    <div className="absolute left-0 right-0 top-1/3 h-[1px] bg-cyan-500/10" />
                    <div className="absolute left-0 right-0 bottom-1/3 h-[1px] bg-cyan-500/10" />
                  </div>

                  <div className="aspect-video bg-[#030712] relative flex items-center justify-center overflow-hidden">
                    {/* Single real webcam feed — also the source MediaPipe analyses. Kept mounted so the ref is stable. */}
                    <video
                      ref={faceVideoRef}
                      autoPlay
                      playsInline
                      muted
                      className={`w-full h-full object-cover opacity-90 ${cameraActive ? '' : 'hidden'}`}
                    />
                    {!cameraActive && (
                      <div className="flex flex-col items-center text-cyan-500/40">
                        <Camera className="w-8 h-8 mb-2" />
                        <span className="text-xs font-mono">VISION UNAVAILABLE</span>
                      </div>
                    )}

                    <div className="absolute inset-0 bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.25)_50%),linear-gradient(90deg,rgba(0,255,255,0.03),rgba(0,0,0,0),rgba(0,255,255,0.03))] bg-[length:100%_4px,3px_100%] pointer-events-none z-10 opacity-40" />
                  </div>
                </div>

                {/* Real-time AI Analysis Module (visual telemetry) */}
                <div className="bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-5 flex-1 shadow-[0_0_30px_rgba(6,182,212,0.05)]">
                  <h3 className="text-xs font-mono text-cyan-500/60 uppercase tracking-widest border-b border-cyan-500/20 pb-3 mb-4 flex items-center gap-2">
                    <Brain className="w-4 h-4" /> Real-Time AI Analysis
                  </h3>

                  <div className="space-y-4">
                    <div className="flex justify-between items-center text-sm font-mono">
                      <span className="text-cyan-400/70">ANSWERS SCORED</span>
                      <span className="text-cyan-300">{results.length} / {questions.length}</span>
                    </div>
                    <div className="h-1.5 w-full bg-cyan-950 rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.8)]"
                        animate={{ width: `${questions.length ? (results.length / questions.length) * 100 : 0}%` }}
                        transition={{ duration: 0.5 }}
                      />
                    </div>

                    <div className="flex justify-between items-center text-sm font-mono pt-2">
                      <span className="text-cyan-400/70">EYE TRACKING</span>
                      <span className="text-cyan-300">
                        {!faceDetected
                          ? '—'
                          : liveEyeContact > 0.6
                            ? 'FOCUSED'
                            : liveEyeContact > 0.3
                              ? 'WANDERING'
                              : 'AWAY'}
                      </span>
                    </div>
                    <div className="h-1.5 w-full bg-cyan-950 rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.6)]"
                        animate={{ width: `${faceDetected ? Math.round(liveEyeContact * 100) : 0}%` }}
                        transition={{ duration: 0.2, ease: 'easeOut' }}
                      />
                    </div>

                    <div className="flex justify-between items-center text-sm font-mono pt-2">
                      <span className="text-cyan-400/70">MICRO-EXPRESSIONS</span>
                      <span className="text-cyan-300">
                        {!faceDetected
                          ? '—'
                          : liveFacialConfidence > 0.6
                            ? 'CALM'
                            : liveFacialConfidence > 0.4
                              ? 'NEUTRAL'
                              : 'TENSE'}
                      </span>
                    </div>
                    <div className="h-1.5 w-full bg-cyan-950 rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-cyan-500 shadow-[0_0_10px_rgba(34,211,238,0.5)]"
                        animate={{ width: `${faceDetected ? Math.round(liveFacialConfidence * 100) : 0}%` }}
                        transition={{ duration: 0.2, ease: 'easeOut' }}
                      />
                    </div>
                  </div>

                  <div className="mt-8 p-3 border border-cyan-500/20 bg-cyan-500/5 rounded text-xs font-mono text-cyan-500/60 leading-relaxed">
                    <span className="text-cyan-400 animate-pulse font-bold">&gt;_</span> Responses are scored live by the AviAssess engine. Camera telemetry above is live face tracking feeding your behavioral score.
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {appState === 'SCORECARD' && (
            <motion.div
              key="scorecard"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className="max-w-4xl mx-auto space-y-6"
            >
              <div className="bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-10 relative overflow-hidden text-center shadow-[0_0_50px_rgba(6,182,212,0.15)]">
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

                <h3 className="text-sm font-mono text-cyan-400/80 uppercase tracking-widest mb-4">Mission Debrief // Evaluation Score</h3>

                <div className="flex justify-center items-end gap-4 mb-8">
                  <div className="text-8xl font-bold text-white tracking-tighter drop-shadow-[0_0_20px_rgba(34,211,238,0.5)]">
                    {fmtScore(totalScore)}
                  </div>
                  <div className="text-2xl text-cyan-500/50 font-mono mb-2">/ 100</div>
                </div>

                <div className="inline-block px-6 py-2 rounded-sm border mb-8 font-mono font-bold tracking-widest uppercase">
                  {passed ? (
                    <span className="text-cyan-400 border-cyan-500/50 bg-cyan-500/10 shadow-[0_0_20px_rgba(34,211,238,0.2)]">
                      Clearance Granted{report?.overall_band ? ` · ${report.overall_band}` : ''}
                    </span>
                  ) : (
                    <span className="text-red-400 border-red-500/50 bg-red-500/10 shadow-[0_0_20px_rgba(239,68,68,0.2)]">
                      Clearance Denied{report?.overall_band ? ` · ${report.overall_band}` : ''}
                    </span>
                  )}
                </div>

                <p className="text-cyan-100/70 text-lg max-w-2xl mx-auto font-mono">
                  &gt; {report?.summary
                    ? report.summary
                    : passed
                      ? 'Candidate demonstrated optimal performance metrics. Aviation protocols successfully verified.'
                      : 'Critical failure in protocol adherence. Recommend extensive simulation retraining.'}
                </p>

                {report && (
                  <p className="text-cyan-500/50 text-xs font-mono mt-4">
                    {report.num_questions} question{report.num_questions === 1 ? '' : 's'} · {report.num_skipped} skipped
                  </p>
                )}
              </div>

              <div className="bg-[#080d1a]/80 backdrop-blur-xl border border-cyan-500/30 rounded-xl p-8 shadow-[0_0_30px_rgba(6,182,212,0.1)]">
                <h3 className="text-sm font-mono text-cyan-400/80 uppercase tracking-widest mb-6 flex items-center gap-2">
                  <Activity className="w-4 h-4" /> Per-Question Breakdown
                </h3>

                <div className="space-y-2">
                  {perQuestion.map((q, i) => {
                    const skipped = (q.band || '').toLowerCase() === 'skipped';
                    const qid = q.question_id;
                    const expanded = expandedQ === qid;
                    const questionText = questionTextById[qid];
                    const candidateAnswer = (answersByQuestion[qid] || '').trim();
                    // Model answers are revealed post-interview; may be null for
                    // behavioral questions. Quality depends on the Phase B dataset.
                    const modelAnswer = (modelAnswers[qid] || '')?.trim?.() || '';
                    const fb = resultById[qid]?.feedback;

                    return (
                      <motion.div
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}
                        key={qid || i}
                        className="bg-cyan-950/20 border border-cyan-500/10 rounded-sm hover:border-cyan-500/30 transition-colors overflow-hidden"
                      >
                        {/* Header row — click to expand the review */}
                        <button
                          type="button"
                          onClick={() => setExpandedQ(expanded ? null : qid)}
                          className="w-full flex items-center justify-between gap-4 p-4 text-left group"
                        >
                          <div className="flex items-center gap-4 min-w-0">
                            {expanded ? (
                              <ChevronDown className="w-4 h-4 text-cyan-400 shrink-0" />
                            ) : (
                              <ChevronRight className="w-4 h-4 text-cyan-500/50 shrink-0" />
                            )}
                            <div className="text-cyan-500/40 font-mono text-sm w-6 shrink-0">0{i + 1}</div>
                            <div className="text-cyan-100 font-mono text-sm truncate group-hover:text-cyan-300 transition-colors">
                              {questionText || String(qid).toUpperCase()}
                            </div>
                          </div>
                          <div className="flex items-center gap-4 sm:gap-6 shrink-0">
                            <span
                              className={`text-xs font-mono tracking-widest px-3 py-1 rounded-sm border uppercase ${skipped ? 'bg-red-500/10 border-red-500/30 text-red-400' : 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'}`}
                            >
                              {q.band || (skipped ? 'skipped' : 'scored')}
                            </span>
                            <div className="text-white font-mono w-12 text-right text-lg">
                              {fmtScore(q.final_score)}
                            </div>
                          </div>
                        </button>

                        {/* Collapsible review body */}
                        {expanded && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            className="border-t border-cyan-500/10 px-4 sm:px-6 py-5 space-y-5"
                          >
                            {questionText && (
                              <div>
                                <div className="text-[10px] font-mono text-cyan-500/50 uppercase tracking-widest mb-1">Question</div>
                                <p className="text-cyan-100/90 text-sm leading-relaxed">{questionText}</p>
                              </div>
                            )}

                            <div>
                              <div className="text-[10px] font-mono text-cyan-500/50 uppercase tracking-widest mb-1">Your answer</div>
                              <p className="text-cyan-50/90 text-sm leading-relaxed whitespace-pre-wrap font-mono bg-[#030712]/60 border border-cyan-500/15 rounded-sm p-3">
                                {candidateAnswer || <span className="text-cyan-500/40 italic">— skipped / no answer —</span>}
                              </p>
                            </div>

                            <div>
                              <div className="text-[10px] font-mono text-emerald-400/60 uppercase tracking-widest mb-1">Model answer</div>
                              <p className="text-emerald-100/90 text-sm leading-relaxed whitespace-pre-wrap bg-emerald-500/5 border border-emerald-500/20 rounded-sm p-3">
                                {modelAnswer || (
                                  <span className="text-cyan-500/40 italic">
                                    No model answer for this question (open-ended / behavioral).
                                  </span>
                                )}
                              </p>
                            </div>

                            {fb?.overall && (
                              <div>
                                <div className="text-[10px] font-mono text-cyan-500/50 uppercase tracking-widest mb-1">Feedback</div>
                                <p className="text-cyan-200/80 text-sm leading-relaxed">{fb.overall}</p>
                                {(fb.keywords_hit?.length || fb.keywords_missed?.length) ? (
                                  <div className="flex flex-wrap gap-2 mt-3">
                                    {fb.keywords_hit?.map((k) => (
                                      <span key={`hit-${k}`} className="text-[10px] font-mono px-2 py-0.5 rounded-sm border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
                                        ✓ {k}
                                      </span>
                                    ))}
                                    {fb.keywords_missed?.map((k) => (
                                      <span key={`miss-${k}`} className="text-[10px] font-mono px-2 py-0.5 rounded-sm border border-red-500/30 bg-red-500/10 text-red-300">
                                        ✗ {k}
                                      </span>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            )}
                          </motion.div>
                        )}
                      </motion.div>
                    );
                  })}
                </div>
              </div>

              <div className="flex justify-center pt-8">
                <button
                  onClick={handleRestart}
                  className="px-10 py-4 bg-cyan-500/10 border border-cyan-400 text-cyan-300 hover:bg-cyan-500 hover:text-[#030712] font-mono font-bold text-sm uppercase tracking-widest transition-all rounded-sm flex items-center gap-3 shadow-[0_0_20px_rgba(6,182,212,0.2)] group"
                >
                  <RefreshCcw className="w-5 h-5 group-hover:-rotate-180 transition-transform duration-500" />
                  Re-Initialize Session
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Footer info */}
        <div className="mt-16 text-center text-[10px] text-cyan-500/40 font-mono tracking-widest uppercase pb-8">
          Secure API Link: {API_BASE_URL}
        </div>
      </main>

      {/* Global scanline overlay */}
      <div className="fixed inset-0 bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.25)_50%),linear-gradient(90deg,rgba(0,255,255,0.03),rgba(0,0,0,0),rgba(0,255,255,0.03))] bg-[length:100%_4px,3px_100%] pointer-events-none z-[100] opacity-10 mix-blend-overlay" />
    </div>
  );
}
