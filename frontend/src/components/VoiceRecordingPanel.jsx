import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

/**
 * Live recording panel: elapsed timer + a real-time waveform driven by a Web
 * Audio AnalyserNode on the recorder's MediaStream, plus a cancel (X) button.
 * Tapping the panel (anywhere but X) stops + transcribes; X discards.
 */
export default function VoiceRecordingPanel({ stream, transcribing, onStop, onCancel }) {
  const canvasRef = useRef(null);
  const [seconds, setSeconds] = useState(0);

  // Elapsed timer.
  useEffect(() => {
    if (transcribing) return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [transcribing]);

  // Waveform: AnalyserNode → animated centered bars on the canvas.
  useEffect(() => {
    if (!stream || !canvasRef.current) return;
    let raf;
    let audioCtx;
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 128;
      source.connect(analyser);
      const bins = analyser.frequencyBinCount;
      const data = new Uint8Array(bins);
      const canvas = canvasRef.current;
      const ctx = canvas.getContext("2d");

      const accent =
        getComputedStyle(document.documentElement).getPropertyValue("--signal-general").trim() ||
        "#4dd9c0";

      const draw = () => {
        raf = requestAnimationFrame(draw);
        analyser.getByteFrequencyData(data);
        const dpr = window.devicePixelRatio || 1;
        const w = (canvas.width = canvas.clientWidth * dpr);
        const h = (canvas.height = canvas.clientHeight * dpr);
        ctx.clearRect(0, 0, w, h);
        const barW = (w / bins) * 1.6;
        let x = 0;
        for (let i = 0; i < bins; i++) {
          const amp = data[i] / 255; // 0..1
          const barH = Math.max(2 * dpr, amp * h * 0.9);
          ctx.fillStyle = accent;
          ctx.globalAlpha = 0.35 + amp * 0.65;
          ctx.fillRect(x, (h - barH) / 2, barW * 0.6, barH);
          x += barW;
        }
        ctx.globalAlpha = 1;
      };
      draw();
    } catch {
      /* Web Audio unavailable — panel still works, just without the waveform */
    }
    return () => {
      cancelAnimationFrame(raf);
      audioCtx?.close().catch(() => {});
    };
  }, [stream]);

  const mmss = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;

  return (
    <div
      className="voice-panel"
      role="button"
      tabIndex={0}
      title="Tap to stop and transcribe"
      onClick={onStop}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onStop()}
    >
      <span className="voice-panel-time">{mmss}</span>
      <canvas ref={canvasRef} className="voice-panel-wave" />
      <span className="voice-panel-label">{transcribing ? "Transcribing…" : "Listening…"}</span>
      <button
        className="voice-panel-cancel"
        title="Discard"
        onClick={(e) => {
          e.stopPropagation();
          onCancel();
        }}
      >
        <Icon name="x" size={16} />
      </button>
    </div>
  );
}
