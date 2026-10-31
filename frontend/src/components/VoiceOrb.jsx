import { useEffect } from "react";
import { useBargeIn } from "../hooks/useVoiceActivity";

const LABEL = {
  idle: "tap to talk",
  listening: "listening",
  transcribing: "transcribing",
  thinking: "thinking",
  speaking: "speaking — talk to interrupt",
};

const clip = (s, n = 220) => (s && s.length > n ? `…${s.slice(-n)}` : s || "");

/** Full-screen hands-free voice mode: an orb that shows whose turn it is,
 * the live transcript, and barge-in (talk over a reply to cut it off). */
export default function VoiceOrb({ phase, userText, replyText, onTap, onBargeIn, onExit }) {
  useBargeIn(phase === "speaking", onBargeIn);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onExit();
      else if (e.key === " " && e.target === document.body) {
        e.preventDefault();
        onTap();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onExit, onTap]);

  return (
    <div className="voice-orb-screen" role="dialog" aria-label="Hands-free voice mode">
      <button className="voice-orb-exit" onClick={onExit} aria-label="Exit voice mode">
        esc
      </button>
      <button className={`voice-orb voice-orb-${phase}`} onClick={onTap} aria-label={LABEL[phase]}>
        <span className="voice-orb-core" />
      </button>
      <p className="voice-orb-label" aria-live="polite">
        {LABEL[phase]}
      </p>
      <div className="voice-orb-transcript">
        {userText && <p className="voice-orb-user">{clip(userText)}</p>}
        {replyText && <p className="voice-orb-reply">{clip(replyText, 320)}</p>}
      </div>
    </div>
  );
}
