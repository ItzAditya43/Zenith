import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

/**
 * Opt-in background wake-word listener.
 *
 * Privacy contract (do not weaken):
 *  1. Only does anything when `enabled` is true — off by default upstream.
 *  2. Renders an always-visible "listening" indicator whenever the mic
 *     stream is actually open in this mode.
 *  3. Never sends raw continuous audio anywhere. It only ever POSTs short,
 *     locally-detected speech bursts (a few hundred ms to a couple seconds)
 *     to the existing /api/voice/transcribe endpoint — the same call the
 *     hold-to-talk flow already makes. Nothing is stored or logged beyond
 *     that endpoint's normal behavior.
 *
 * Local energy-based VAD: an AnalyserNode reads time-domain data on an
 * interval; when the RMS amplitude crosses a threshold for a minimum
 * duration, we consider that a "speech burst" and start capturing a
 * MediaRecorder clip. When energy drops back below threshold (or a max
 * burst duration is hit), we stop the clip and transcribe it.
 */

const RMS_THRESHOLD = 0.02; // empirical low bar for "someone is speaking"
const MIN_SPEECH_MS = 300; // sustained energy before we call it a burst
const SILENCE_HOLD_MS = 500; // quiet time before we consider the burst over
const MAX_BURST_MS = 4000; // safety cap so a burst can't run forever
const POLL_MS = 60; // VAD sampling interval

export default function WakeWordListener({ enabled, phrase, onWake }) {
  const [listening, setListening] = useState(false);
  const streamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const dataRef = useRef(null);
  const intervalRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const speechStartRef = useRef(null);
  const silenceStartRef = useRef(null);
  const capturingRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) {
      cleanup();
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          // enabled flipped off (or component unmounted) while awaiting permission
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;

        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        const audioCtx = new AudioCtx();
        audioCtxRef.current = audioCtx;
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 1024;
        source.connect(analyser);
        analyserRef.current = analyser;
        dataRef.current = new Uint8Array(analyser.fftSize);

        setListening(true);
        intervalRef.current = setInterval(vadTick, POLL_MS);
      } catch {
        // mic permission denied or unavailable — stay silently off, no retry loop
        setListening(false);
      }
    })();

    return () => {
      cancelled = true;
      cleanup();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  function cleanup() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      try {
        recorderRef.current.stop();
      } catch {
        /* already stopped */
      }
    }
    recorderRef.current = null;
    chunksRef.current = [];
    capturingRef.current = false;
    speechStartRef.current = null;
    silenceStartRef.current = null;

    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    analyserRef.current = null;
    dataRef.current = null;

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    setListening(false);
  }

  function rms() {
    const analyser = analyserRef.current;
    const data = dataRef.current;
    if (!analyser || !data) return 0;
    analyser.getByteTimeDomainData(data);
    let sumSq = 0;
    for (let i = 0; i < data.length; i++) {
      const centered = (data[i] - 128) / 128; // -1..1
      sumSq += centered * centered;
    }
    return Math.sqrt(sumSq / data.length);
  }

  function vadTick() {
    const amplitude = rms();
    const now = Date.now();
    const loud = amplitude >= RMS_THRESHOLD;

    if (!capturingRef.current) {
      if (loud) {
        if (speechStartRef.current == null) speechStartRef.current = now;
        if (now - speechStartRef.current >= MIN_SPEECH_MS) {
          startBurstCapture();
        }
      } else {
        speechStartRef.current = null;
      }
      return;
    }

    // Currently capturing a burst — watch for it ending.
    if (loud) {
      silenceStartRef.current = null;
    } else {
      if (silenceStartRef.current == null) silenceStartRef.current = now;
      if (now - silenceStartRef.current >= SILENCE_HOLD_MS) {
        stopBurstCapture();
        return;
      }
    }
    if (now - speechStartRef.current >= MAX_BURST_MS) {
      stopBurstCapture();
    }
  }

  function startBurstCapture() {
    const stream = streamRef.current;
    if (!stream || capturingRef.current) return;
    let recorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch {
      return; // MediaRecorder unavailable — skip this burst
    }
    capturingRef.current = true;
    silenceStartRef.current = null;
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: "audio/webm" });
      chunksRef.current = [];
      capturingRef.current = false;
      speechStartRef.current = null;
      silenceStartRef.current = null;
      if (blob.size > 0) transcribeBurst(blob);
    };
    recorderRef.current = recorder;
    recorder.start();
  }

  function stopBurstCapture() {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {
        /* ignore */
      }
    }
  }

  async function transcribeBurst(blob) {
    try {
      const result = await api.transcribe(blob, "wakeword-burst.webm");
      const text = (result?.text || "").toLowerCase().trim();
      const target = (phrase || "").toLowerCase().trim();
      if (!mountedRef.current || !target) return;
      if (text.startsWith(target)) {
        onWake?.();
      }
    } catch {
      // transcription failure — silently drop this burst, nothing logged beyond
      // the transcribe call's own normal behavior
    }
  }

  if (!enabled || !listening) return null;

  return (
    <span
      title={`Listening for wake phrase "${phrase}"`}
      aria-label="Wake word listening is active — microphone is on"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: 999,
        border: "1px solid rgba(230, 126, 34, 0.5)",
        background: "rgba(230, 126, 34, 0.12)",
        color: "#e67e22",
        fontSize: 12,
        fontFamily: "var(--font-mono, monospace)",
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: "#e67e22",
          animation: "wake-word-pulse 1.2s ease-in-out infinite",
          flexShrink: 0,
        }}
      />
      <style>{`
        @keyframes wake-word-pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.7); }
        }
      `}</style>
      Listening for wake word
    </span>
  );
}
