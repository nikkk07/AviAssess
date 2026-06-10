// Browser-native text-to-speech via the Web Speech API. No dependencies.

export function isSpeechSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

// Pick the first English voice, if the voice list has loaded yet.
function pickEnglishVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => v.lang && v.lang.toLowerCase().startsWith('en')) ?? null;
}

/**
 * Speak `text`. `onEnd` (optional) fires once the utterance FINISHES naturally,
 * which callers use to auto-start the mic. It is intentionally NOT called when
 * speech is unsupported or when this utterance is cut short by a later
 * speak()/stopSpeaking() cancel — so it only signals a genuine end-of-question.
 */
export function speak(text: string, onEnd?: () => void): void {
  if (!isSpeechSupported()) return;

  // Cancel anything in flight so questions never overlap. (This fires the PREVIOUS
  // utterance's own onend, but each utterance carries its own callback, so the
  // cancelled one cannot trigger this call's onEnd.)
  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = 'en-US';
  utterance.rate = 1;
  utterance.pitch = 1;
  if (onEnd) utterance.onend = () => onEnd();

  const voice = pickEnglishVoice();
  if (voice) {
    // Voices already loaded — use the chosen English voice.
    utterance.voice = voice;
  } else {
    // The voice list loads asynchronously; refine the pick once it arrives.
    // If it never fires (or is empty), the browser default is used.
    const onVoicesChanged = () => {
      const v = pickEnglishVoice();
      if (v) utterance.voice = v;
      window.speechSynthesis.removeEventListener('voiceschanged', onVoicesChanged);
    };
    window.speechSynthesis.addEventListener('voiceschanged', onVoicesChanged);
  }

  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  window.speechSynthesis?.cancel();
}
