import { useEffect, useState } from "react";
import { api } from "../lib/api";

const WORDMARK = `███████╗███████╗███╗   ██╗██╗████████╗██╗  ██╗
╚══███╔╝██╔════╝████╗  ██║██║╚══██╔══╝██║  ██║
  ███╔╝ █████╗  ██╔██╗ ██║██║   ██║   ███████║
 ███╔╝  ██╔══╝  ██║╚██╗██║██║   ██║   ██╔══██║
███████╗███████╗██║ ╚████║██║   ██║   ██║  ██║
╚══════╝╚══════╝╚═╝  ╚═══╝╚═╝   ╚═╝   ╚═╝  ╚═╝`;

type Check = { label: string; detail: string; state: "ok" | "warn" | "off" };

interface Health {
  components?: Record<string, Record<string, unknown>>;
}

function checksFrom(h: Health | null): Check[] {
  const c = h?.components ?? {};
  const ollama = c.ollama ?? {};
  const embed = c.embedding_model ?? {};
  const agent = c.agent_mode ?? {};
  const sandbox = (agent.sandbox ?? {}) as Record<string, unknown>;
  const tts = c.tts ?? {};
  return [
    ollama.ok
      ? { label: "ollama", detail: `${ollama.models ?? "?"} models · ${ollama.latency_ms ?? "?"}ms`, state: "ok" }
      : { label: "ollama", detail: "unreachable — is `ollama serve` running?", state: "warn" },
    embed.ok
      ? { label: "search", detail: `${embed.mode ?? "hybrid"} · ${embed.model}`, state: embed.mode === "hybrid" ? "ok" : "warn" }
      : { label: "search", detail: "keywords only — pull nomic-embed-text for hybrid", state: "warn" },
    agent.enabled
      ? { label: "agent", detail: `on · sandbox ${sandbox.mode ?? "off"}`, state: "ok" }
      : { label: "agent", detail: "off", state: "off" },
    { label: "voice", detail: tts.ok ? "whisper · piper" : "whisper · system tts", state: tts.ok ? "ok" : "off" },
  ];
}

const MARK = { ok: "[ ok ]", warn: "[warn]", off: "[ -- ]" } as const;

/** POST-style boot screen: the wordmark plus real health checks, once per
 * session. Doubles as a health check so problems show up before the first
 * message. Any key or click skips it. */
export default function BootSplash({ onDone }: { onDone: () => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [shown, setShown] = useState(0);
  const checks = checksFrom(health);

  useEffect(() => {
    let alive = true;
    api.health().then((h: Health) => alive && setHealth(h)).catch(() => alive && setHealth({}));
    const skip = () => onDone();
    window.addEventListener("keydown", skip);
    window.addEventListener("pointerdown", skip);
    const cap = setTimeout(onDone, 3000);
    return () => {
      alive = false;
      clearTimeout(cap);
      window.removeEventListener("keydown", skip);
      window.removeEventListener("pointerdown", skip);
    };
  }, [onDone]);

  useEffect(() => {
    if (!health) return;
    if (shown < checks.length) {
      const t = setTimeout(() => setShown((n) => n + 1), 140);
      return () => clearTimeout(t);
    }
    const done = setTimeout(onDone, 450);
    return () => clearTimeout(done);
  }, [health, shown, checks.length, onDone]);

  return (
    <div className="boot-splash" role="status" aria-label="Starting Zenith">
      <pre className="boot-wordmark" aria-hidden="true">{WORDMARK}</pre>
      <div className="boot-checks">
        {checks.slice(0, shown).map((c) => (
          <div key={c.label} className={`boot-check boot-${c.state}`}>
            <span className="boot-mark">{MARK[c.state]}</span>
            <span className="boot-label">{c.label}</span>
            <span className="boot-detail">{c.detail}</span>
          </div>
        ))}
        {(!health || shown < checks.length) && <div className="boot-check boot-off"><span className="boot-mark">[ .. ]</span><span className="boot-label">starting</span></div>}
      </div>
      <pre className="boot-horizon" aria-hidden="true">{"░░░░▒▒▒▒▓▓▓▓████████████████▓▓▓▓▒▒▒▒░░░░"}</pre>
      <span className="boot-hint">press any key</span>
    </div>
  );
}
