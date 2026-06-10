import { useCallback, useEffect, useRef, useState } from 'react';
import { FaceLandmarker, FilesetResolver, type FaceLandmarkerResult } from '@mediapipe/tasks-vision';

// Pin the wasm bundle to the installed @mediapipe/tasks-vision version to avoid runtime mismatch.
const WASM_URL = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm';
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

// Throttle detection to ~8 fps — plenty for a presence indicator, far cheaper than every frame.
const DETECT_INTERVAL_MS = 1000 / 8;

const round3 = (n: number) => Math.round(n * 1000) / 1000;

/** Per-question behavioral metrics, keyed to match the backend (confidence.py). Empty when no face was ever seen. */
export type QuestionMetrics =
  | Record<string, never>
  | { eye_contact_percent: number; facial_confidence_score: number };

interface UseFaceTrackingReturn {
  ready: boolean;
  loading: boolean;
  faceDetected: boolean;
  error: string;
  /** Smoothed (EMA) live eye-contact level 0–1, updated at the detection rate for animated UI. */
  liveEyeContact: number;
  /** Smoothed (EMA) live facial-confidence level 0–1, updated at the detection rate for animated UI. */
  liveFacialConfidence: number;
  /** Latest raw landmarker result — stashed in case later phases want richer signals. */
  lastResultRef: React.MutableRefObject<FaceLandmarkerResult | null>;
  /** Averaged metrics for the current question; {} when no face was detected (→ behavioral_features stays null). */
  getQuestionMetrics: () => QuestionMetrics;
  /** Zero the running accumulators — call when a new question becomes current. */
  resetQuestionMetrics: () => void;
}

/**
 * Best-effort MediaPipe face tracking against a <video> element.
 * Every failure path is swallowed into `error` so callers can degrade gracefully.
 */
export function useFaceTracking(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  enabled: boolean,
): UseFaceTrackingReturn {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [faceDetected, setFaceDetected] = useState(false);
  const [error, setError] = useState('');

  // Smoothed live levels surfaced to the UI (EMA, written each detection tick).
  const [liveEyeContact, setLiveEyeContact] = useState(0);
  const [liveFacialConfidence, setLiveFacialConfidence] = useState(0);

  const landmarkerRef = useRef<FaceLandmarker | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastDetectRef = useRef(0);
  const lastResultRef = useRef<FaceLandmarkerResult | null>(null);

  // Running per-question accumulators (refs so frames don't trigger re-renders).
  const eyeContactSumRef = useRef(0);
  const facialSumRef = useRef(0);
  const framesWithFaceRef = useRef(0);

  // EMA state held in refs so each frame reads the latest without stale closures.
  const liveEyeRef = useRef(0);
  const liveFacialRef = useRef(0);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    const loop = () => {
      // Re-arm first so an early `return` (e.g. video not ready) still keeps the loop alive.
      rafRef.current = requestAnimationFrame(loop);

      const video = videoRef.current;
      const landmarker = landmarkerRef.current;
      if (!video || !landmarker || video.readyState < 2) return;

      const now = performance.now();
      if (now - lastDetectRef.current < DETECT_INTERVAL_MS) return;
      lastDetectRef.current = now;

      try {
        const result = landmarker.detectForVideo(video, now);
        lastResultRef.current = result;
        const hasFace = (result.faceLandmarks?.length ?? 0) > 0;
        setFaceDetected(hasFace);

        // Only accumulate behavioral metrics on frames where a face is present.
        if (hasFace) {
          const cats = result.faceBlendshapes?.[0]?.categories ?? [];
          const bs: Record<string, number> = {};
          for (const c of cats) bs[c.categoryName] = c.score;

          // EYE CONTACT (v1 heuristic → 0 or 1): looking roughly forward and not mid-blink.
          const gazeAway = Math.max(
            bs.eyeLookOutLeft || 0,
            bs.eyeLookOutRight || 0,
            bs.eyeLookInLeft || 0,
            bs.eyeLookInRight || 0,
            bs.eyeLookUpLeft || 0,
            bs.eyeLookUpRight || 0,
            bs.eyeLookDownLeft || 0,
            bs.eyeLookDownRight || 0,
          );
          const blink = ((bs.eyeBlinkLeft || 0) + (bs.eyeBlinkRight || 0)) / 2;
          const eyeContactFrame = gazeAway < 0.5 && blink < 0.5 ? 1 : 0;

          // FACIAL CONFIDENCE (v1 heuristic → clamp 0–1): smile lifts, tension/worry lowers.
          let s = 0.65;
          const smile = ((bs.mouthSmileLeft || 0) + (bs.mouthSmileRight || 0)) / 2;
          const furrow = ((bs.browDownLeft || 0) + (bs.browDownRight || 0)) / 2;
          const worry = bs.browInnerUp || 0;
          const frown = ((bs.mouthFrownLeft || 0) + (bs.mouthFrownRight || 0)) / 2;
          s += Math.min(smile, 0.4) * 0.4;
          s -= furrow * 0.2;
          s -= worry * 0.25;
          s -= frown * 0.25;
          const facialFrame = Math.max(0, Math.min(1, s));

          eyeContactSumRef.current += eyeContactFrame;
          facialSumRef.current += facialFrame;
          framesWithFaceRef.current += 1;

          // Smooth the live UI levels toward this frame's values.
          liveEyeRef.current = liveEyeRef.current * 0.8 + eyeContactFrame * 0.2;
          liveFacialRef.current = liveFacialRef.current * 0.8 + facialFrame * 0.2;
        } else {
          // No face this frame — decay the live levels toward 0.
          liveEyeRef.current *= 0.8;
          liveFacialRef.current *= 0.8;
        }

        setLiveEyeContact(liveEyeRef.current);
        setLiveFacialConfidence(liveFacialRef.current);
      } catch {
        // Transient detection hiccup — keep looping, don't surface as fatal.
      }
    };

    (async () => {
      setLoading(true);
      setError('');
      try {
        const resolver = await FilesetResolver.forVisionTasks(WASM_URL);
        const landmarker = await FaceLandmarker.createFromOptions(resolver, {
          baseOptions: { modelAssetPath: MODEL_URL, delegate: 'GPU' },
          outputFaceBlendshapes: true,
          outputFacialTransformationMatrixes: true,
          runningMode: 'VIDEO',
          numFaces: 1,
        });
        if (cancelled) {
          landmarker.close();
          return;
        }
        landmarkerRef.current = landmarker;
        setReady(true);
        setLoading(false);
        rafRef.current = requestAnimationFrame(loop);
      } catch (err) {
        if (cancelled) return;
        setLoading(false);
        setReady(false);
        setError('Face tracking unavailable.');
        console.error('Failed to initialize MediaPipe FaceLandmarker', err);
      }
    })();

    return () => {
      cancelled = true;
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      try {
        landmarkerRef.current?.close();
      } catch {
        /* already closed */
      }
      landmarkerRef.current = null;
      lastResultRef.current = null;
      liveEyeRef.current = 0;
      liveFacialRef.current = 0;
      setReady(false);
      setFaceDetected(false);
      setLiveEyeContact(0);
      setLiveFacialConfidence(0);
    };
  }, [enabled, videoRef]);

  // Stable callbacks — they only touch refs, so they never need to be re-created.
  const getQuestionMetrics = useCallback((): QuestionMetrics => {
    const frames = framesWithFaceRef.current;
    if (frames === 0) return {};
    return {
      eye_contact_percent: round3(eyeContactSumRef.current / frames),
      facial_confidence_score: round3(facialSumRef.current / frames),
    };
  }, []);

  const resetQuestionMetrics = useCallback(() => {
    eyeContactSumRef.current = 0;
    facialSumRef.current = 0;
    framesWithFaceRef.current = 0;
  }, []);

  return {
    ready,
    loading,
    faceDetected,
    error,
    liveEyeContact,
    liveFacialConfidence,
    lastResultRef,
    getQuestionMetrics,
    resetQuestionMetrics,
  };
}
