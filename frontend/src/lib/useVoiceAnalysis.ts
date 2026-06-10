import { useCallback, useEffect, useRef } from 'react';

// Process the analyser buffer ~10 times a second — enough for prosody, cheap on the main thread.
const TICK_MS = 100;
// Below this RMS the frame is treated as silence (no voice, no pitch sample).
const RMS_VOICED_THRESHOLD = 0.01;

const round3 = (n: number) => Math.round(n * 1000) / 1000;

/** Per-question voice prosody, keyed to match the backend (confidence.py). Keys are present only when measurable. */
export type VoiceMetrics = {
  pitch_variance?: number;
  speaking_rate_wpm?: number;
};

interface UseVoiceAnalysisReturn {
  /** Metrics for the current question; omits each key whose evidence threshold wasn't met. {} when no real speech. */
  getQuestionVoiceMetrics: (wordCount: number) => VoiceMetrics;
  /** Zero the running accumulators — call when a new question becomes current. */
  resetQuestionVoiceMetrics: () => void;
}

/**
 * Canonical autocorrelation pitch detector (returns fundamental frequency in Hz, or -1).
 * Kept verbatim — a well-known, battle-tested implementation.
 */
function autoCorrelate(buf: Float32Array, sampleRate: number): number {
  const SIZE = buf.length;
  let rms = 0;
  for (let i = 0; i < SIZE; i++) {
    const v = buf[i];
    rms += v * v;
  }
  rms = Math.sqrt(rms / SIZE);
  if (rms < 0.01) return -1;
  let r1 = 0,
    r2 = SIZE - 1;
  const thres = 0.2;
  for (let i = 0; i < SIZE / 2; i++) if (Math.abs(buf[i]) < thres) { r1 = i; break; }
  for (let i = 1; i < SIZE / 2; i++) if (Math.abs(buf[SIZE - i]) < thres) { r2 = SIZE - i; break; }
  const b = buf.slice(r1, r2);
  const n = b.length;
  const c = new Array(n).fill(0);
  for (let i = 0; i < n; i++) for (let j = 0; j < n - i; j++) c[i] += b[j] * b[j + i];
  let d = 0;
  while (d + 1 < n && c[d] > c[d + 1]) d++;
  let maxval = -1,
    maxpos = -1;
  for (let i = d; i < n; i++) if (c[i] > maxval) { maxval = c[i]; maxpos = i; }
  let T0 = maxpos;
  const x1 = c[T0 - 1] || 0,
    x2 = c[T0] || 0,
    x3 = c[T0 + 1] || 0;
  const a = (x1 + x3 - 2 * x2) / 2,
    bb = (x3 - x1) / 2;
  if (a) T0 = T0 - bb / (2 * a);
  return T0 > 0 ? sampleRate / T0 : -1;
}

/**
 * Best-effort voice prosody analysis via the Web Audio API. Opens its own audio-only
 * stream (independent of SpeechRecognition). If the mic is denied or silent, it simply
 * produces no metrics — it never throws and never blocks the interview.
 */
export function useVoiceAnalysis(enabled: boolean): UseVoiceAnalysisReturn {
  // Running per-question accumulators (refs so audio frames never trigger re-renders).
  const voicedSecondsRef = useRef(0);
  const pitchesRef = useRef<number[]>([]);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let raf: number | null = null;
    let ctx: AudioContext | null = null;
    let stream: MediaStream | null = null;
    let analyser: AnalyserNode | null = null;
    let buffer: Float32Array | null = null;
    let lastTick = 0;

    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (!analyser || !buffer || !ctx) return;

      const now = performance.now();
      if (now - lastTick < TICK_MS) return;
      const dt = lastTick ? (now - lastTick) / 1000 : TICK_MS / 1000;
      lastTick = now;

      analyser.getFloatTimeDomainData(buffer);
      let rms = 0;
      for (let i = 0; i < buffer.length; i++) {
        const v = buffer[i];
        rms += v * v;
      }
      rms = Math.sqrt(rms / buffer.length);

      if (rms > RMS_VOICED_THRESHOLD) {
        voicedSecondsRef.current += dt;
        const pitch = autoCorrelate(buffer, ctx.sampleRate);
        if (pitch >= 70 && pitch <= 400) pitchesRef.current.push(pitch);
      }
    };

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        const AC: typeof AudioContext =
          window.AudioContext || (window as any).webkitAudioContext;
        ctx = new AC();
        const source = ctx.createMediaStreamSource(stream);
        analyser = ctx.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);
        buffer = new Float32Array(analyser.fftSize);
        lastTick = 0;
        raf = requestAnimationFrame(loop);
      } catch (err) {
        if (cancelled) return;
        // Denied / unavailable: stay silent, produce no metrics. Never throw.
        console.warn('useVoiceAnalysis: audio unavailable', err);
      }
    })();

    return () => {
      cancelled = true;
      if (raf != null) cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach((t) => t.stop());
      if (ctx) {
        try {
          ctx.close();
        } catch {
          /* already closed */
        }
      }
    };
  }, [enabled]);

  const getQuestionVoiceMetrics = useCallback((wordCount: number): VoiceMetrics => {
    const result: VoiceMetrics = {};
    const voiced = voicedSecondsRef.current;
    const pitches = pitchesRef.current;

    // Speaking rate needs enough voiced audio AND words to be meaningful.
    if (voiced >= 2 && wordCount > 0) {
      result.speaking_rate_wpm = Math.round(wordCount / (voiced / 60));
    }

    // Pitch variance needs a decent sample of voiced pitches; reported as a clamped CV.
    if (pitches.length >= 10) {
      const mean = pitches.reduce((a, b) => a + b, 0) / pitches.length;
      const variance = pitches.reduce((a, b) => a + (b - mean) * (b - mean), 0) / pitches.length;
      const std = Math.sqrt(variance);
      const cv = mean ? std / mean : 0;
      result.pitch_variance = round3(Math.max(0, Math.min(1, cv)));
    }

    return result;
  }, []);

  const resetQuestionVoiceMetrics = useCallback(() => {
    voicedSecondsRef.current = 0;
    pitchesRef.current = [];
  }, []);

  return { getQuestionVoiceMetrics, resetQuestionVoiceMetrics };
}
