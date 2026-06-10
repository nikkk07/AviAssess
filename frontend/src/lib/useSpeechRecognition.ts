import { useEffect, useRef, useState } from 'react';

import { correctAviationTerms } from './aviationCorrections';

// Web Speech API SpeechRecognition (Chrome/Edge only; prefixed on most builds).
const SR: any =
  typeof window !== 'undefined'
    ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    : undefined;

interface UseSpeechRecognitionArgs {
  onFinalResult: (text: string) => void;
}

interface UseSpeechRecognitionReturn {
  supported: boolean;
  listening: boolean;
  interim: string;
  error: string;
  start: () => void;
  stop: () => void;
}

export function useSpeechRecognition({
  onFinalResult,
}: UseSpeechRecognitionArgs): UseSpeechRecognitionReturn {
  const supported = Boolean(SR);

  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState('');
  const [error, setError] = useState('');

  const recognitionRef = useRef<any>(null);
  // Keep the latest callback without re-creating the recognition instance.
  const onFinalResultRef = useRef(onFinalResult);
  onFinalResultRef.current = onFinalResult;

  useEffect(() => {
    if (!supported) return;

    const recognition = new SR();
    recognition.lang = 'en-US';
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event: any) => {
      let interimText = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? '';
        if (result.isFinal) {
          // Correct curated aviation mishearings on FINALIZED segments only, so
          // both the visible transcript and the submitted answer are clean.
          // (Typed text never passes through here, so it is left untouched.)
          const finalText = correctAviationTerms(transcript.trim());
          if (finalText) onFinalResultRef.current(finalText);
        } else {
          interimText += transcript;
        }
      }
      setInterim(interimText);
    };

    recognition.onerror = (event: any) => {
      const code = event?.error;
      if (code === 'no-speech') {
        // Nothing heard — ignore quietly.
        return;
      }
      if (code === 'not-allowed' || code === 'service-not-allowed') {
        setError('Microphone blocked — allow mic access and try again.');
      } else {
        setError('Voice input error, please type your answer.');
      }
    };

    recognition.onend = () => {
      // Do not auto-restart; the user re-clicks to continue.
      setListening(false);
      setInterim('');
    };

    recognitionRef.current = recognition;

    return () => {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.stop();
      } catch {
        /* already stopped */
      }
      recognitionRef.current = null;
    };
  }, [supported]);

  const start = () => {
    if (!supported || !recognitionRef.current) return;
    setError('');
    setInterim('');
    setListening(true);
    try {
      recognitionRef.current.start();
    } catch {
      // start() throws if already started — ignore.
    }
  };

  const stop = () => {
    if (!supported || !recognitionRef.current) return;
    setListening(false);
    try {
      recognitionRef.current.stop();
    } catch {
      /* already stopped */
    }
  };

  return { supported, listening, interim, error, start, stop };
}
