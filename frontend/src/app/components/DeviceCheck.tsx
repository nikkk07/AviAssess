import React, { useEffect, useRef, useState } from 'react';
import { Volume2, Mic, CheckCircle2, AlertCircle } from 'lucide-react';

import { Button } from './ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';
import { Progress } from './ui/progress';
import { Checkbox } from './ui/checkbox';
import { Alert, AlertTitle, AlertDescription } from './ui/alert';
import { Label } from './ui/label';

interface DeviceCheckProps {
  onReady: () => void;
}

const SPEAKER_PHRASE =
  'Hello! If you can hear this clearly, your speaker is working.';
// Mic is considered "live" once the RMS-derived level crosses this (0–100 scale).
const MIC_THRESHOLD = 8;

export default function DeviceCheck({ onReady }: DeviceCheckProps) {
  const speechSupported =
    typeof window !== 'undefined' && 'speechSynthesis' in window;

  // ── speaker ──
  const [speaking, setSpeaking] = useState(false);
  const [heardConfirmed, setHeardConfirmed] = useState(false);

  // ── mic ──
  const [micActive, setMicActive] = useState(false);
  const [micLevel, setMicLevel] = useState(0);
  const [micPassed, setMicPassed] = useState(false);
  const [micError, setMicError] = useState('');

  // ── live-audio plumbing (kept in refs so cleanup can reach it) ──
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);

  const speakerPassed = speechSupported && heardConfirmed;
  const bothPassed = speakerPassed && micPassed;

  // ── speaker test ──
  function playTestSound() {
    if (!speechSupported) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(SPEAKER_PHRASE);
    utter.onstart = () => setSpeaking(true);
    utter.onend = () => setSpeaking(false);
    utter.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utter);
  }

  // ── mic test ──
  async function startMicTest() {
    setMicError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioCtx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      analyserRef.current = analyser;

      const buffer = new Uint8Array(analyser.fftSize);
      setMicActive(true);

      const tick = () => {
        analyser.getByteTimeDomainData(buffer);
        // RMS around the 128 mid-point, scaled to a friendly 0–100 range.
        let sumSquares = 0;
        for (let i = 0; i < buffer.length; i += 1) {
          const v = (buffer[i] - 128) / 128;
          sumSquares += v * v;
        }
        const rms = Math.sqrt(sumSquares / buffer.length);
        const level = Math.min(100, Math.round(rms * 400));
        setMicLevel(level);
        if (level >= MIC_THRESHOLD) setMicPassed(true);
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);
    } catch {
      setMicActive(false);
      setMicError(
        'Microphone blocked. Allow mic access in your browser, then try again.',
      );
    }
  }

  // ── cleanup on unmount ──
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      audioCtxRef.current?.close().catch(() => {});
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  return (
    <div className="max-w-xl mx-auto mt-10 space-y-6">
      <div className="text-center space-y-2">
        <h1 className="text-2xl font-bold tracking-widest uppercase font-mono text-cyan-50">
          Device Check
        </h1>
        <p className="text-sm text-cyan-400/70 font-mono">
          Confirm your speaker and microphone before the interview begins.
        </p>
      </div>

      {/* SPEAKER */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Volume2 className="w-5 h-5" /> Speaker test
          </CardTitle>
          <CardDescription>
            Play the test sound and confirm you can hear it clearly.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!speechSupported ? (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertTitle>Speaker test unavailable</AlertTitle>
              <AlertDescription>
                Your browser does not support speech synthesis. Please use Google
                Chrome to complete the device check.
              </AlertDescription>
            </Alert>
          ) : (
            <>
              <Button
                onClick={playTestSound}
                disabled={speaking}
                variant="secondary"
              >
                <Volume2 /> {speaking ? 'Playing…' : 'Play test sound'}
              </Button>

              <div className="flex items-center gap-2">
                <Checkbox
                  id="heard-sound"
                  checked={heardConfirmed}
                  onCheckedChange={(v) => setHeardConfirmed(v === true)}
                />
                <Label htmlFor="heard-sound">I heard the sound clearly</Label>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* MIC */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mic className="w-5 h-5" /> Microphone test
          </CardTitle>
          <CardDescription>
            Start the test, then speak — the bar should move as it hears you.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button onClick={startMicTest} disabled={micActive} variant="secondary">
            <Mic /> {micActive ? 'Listening…' : 'Start mic test'}
          </Button>

          {micActive && (
            <div className="space-y-2">
              <Label>Input level</Label>
              <Progress value={micLevel} />
            </div>
          )}

          {micPassed && (
            <p className="flex items-center gap-2 text-emerald-400 font-mono text-sm">
              <CheckCircle2 className="w-4 h-4" /> Microphone is working
            </p>
          )}

          {micError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertTitle>Microphone blocked</AlertTitle>
              <AlertDescription>{micError}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* CONTINUE */}
      <div className="flex justify-center pt-2">
        <Button size="lg" disabled={!bothPassed} onClick={onReady}>
          Start Interview
        </Button>
      </div>
    </div>
  );
}
