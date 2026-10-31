import { useEffect, useRef } from "react";

type AudioCtor = typeof AudioContext;

function audioContext(): AudioContext | null {
  const Ctor: AudioCtor | undefined =
    window.AudioContext || (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext;
  return Ctor ? new Ctor() : null;
}

/** Calls `onLevel(rms)` ~10×/s for `stream` until it changes or unmounts. */
function watchLevel(stream: MediaStream, onLevel: (rms: number, now: number) => void): () => void {
  const ctx = audioContext();
  if (!ctx) return () => {};
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const id = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    onLevel(Math.sqrt(sum / buf.length), performance.now());
  }, 100);
  return () => {
    clearInterval(id);
    ctx.close().catch(() => {});
  };
}

/** End-of-utterance detection: once speech has been heard on `stream`,
 * `silenceMs` of quiet calls `onSilence` (once). Also fires after `maxMs`. */
export function useSilenceStop(
  stream: MediaStream | null,
  onSilence: () => void,
  { threshold = 0.02, silenceMs = 1300, maxMs = 30000 } = {}
): void {
  const cb = useRef(onSilence);
  useEffect(() => {
    cb.current = onSilence;
  });
  useEffect(() => {
    if (!stream) return;
    let heard = false;
    let quietSince = 0;
    let fired = false;
    const t0 = performance.now();
    return watchLevel(stream, (rms, now) => {
      if (fired) return;
      if (rms > threshold) {
        heard = true;
        quietSince = 0;
      } else if (heard) {
        quietSince ||= now;
      }
      if ((heard && quietSince && now - quietSince > silenceMs) || now - t0 > maxMs) {
        fired = true;
        cb.current();
      }
    });
  }, [stream, threshold, silenceMs, maxMs]);
}

/** Barge-in: while `enabled`, listen on an echo-cancelled mic and call
 * `onSpeech` when the user talks for `sustainMs` (louder than speaker bleed). */
export function useBargeIn(enabled: boolean, onSpeech: () => void, { threshold = 0.06, sustainMs = 300 } = {}): void {
  const cb = useRef(onSpeech);
  useEffect(() => {
    cb.current = onSpeech;
  });
  useEffect(() => {
    if (!enabled || !navigator.mediaDevices?.getUserMedia) return;
    let stopWatch = () => {};
    let stream: MediaStream | null = null;
    let alive = true;
    navigator.mediaDevices
      .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((s) => {
        stream = s;
        if (!alive) return s.getTracks().forEach((t) => t.stop());
        let loudSince = 0;
        stopWatch = watchLevel(s, (rms, now) => {
          if (rms < threshold) loudSince = 0;
          else if (!loudSince) loudSince = now;
          else if (now - loudSince > sustainMs) {
            loudSince = Infinity;
            cb.current();
          }
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
      stopWatch();
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [enabled, threshold, sustainMs]);
}
