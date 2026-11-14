import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api } from "../../lib/api";

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * A shell in the working directory (see backend terminal_service.py).
 *
 * The session lives on the server per conversation, so closing the drawer
 * or switching tabs doesn't kill a running dev server: reopening reattaches
 * and replays the kept scrollback.
 */
export default function TerminalView({ conversationId, active }) {
  const host = useRef(null);
  const term = useRef(null);
  const fit = useRef(null);
  const sid = useRef(null);
  const [status, setStatus] = useState("starting"); // starting | running | exited | error
  const [message, setMessage] = useState("");
  const [restartKey, setRestartKey] = useState(0);

  useEffect(() => {
    const t = new Terminal({
      fontFamily: cssVar("--font-mono", "monospace"),
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 5000,
      allowProposedApi: false,
      theme: {
        background: cssVar("--bg-inset", "#000000"),
        foreground: cssVar("--text-primary", "#dddddd"),
        cursor: cssVar("--signal-general", "#ffaa66"),
        selectionBackground: "rgba(148, 163, 184, 0.25)",
      },
    });
    const f = new FitAddon();
    t.loadAddon(f);
    t.open(host.current);
    term.current = t;
    fit.current = f;
    try { f.fit(); } catch { /* host not laid out yet */ }

    const abort = new AbortController();
    let stopped = false;
    let pending = "";
    let flushTimer = null;

    // Batch keystrokes a little so a paste or fast typing is one request.
    const flush = () => {
      flushTimer = null;
      if (!pending || !sid.current) return;
      const data = pending;
      pending = "";
      api.terminalInput(sid.current, data).catch((err) => setMessage(err.message));
    };
    const onData = t.onData((d) => {
      pending += d;
      if (!flushTimer) flushTimer = setTimeout(flush, 8);
    });
    const onResize = t.onResize(({ cols, rows }) => {
      if (sid.current) api.terminalResize(sid.current, cols, rows).catch(() => {});
    });

    (async () => {
      try {
        const avail = await api.terminalAvailable();
        if (!avail.available) {
          setStatus("error");
          setMessage("The terminal isn't available on Windows yet.");
          return;
        }
        // Measure before starting so the shell knows its real width
        // from the first line it prints.
        await new Promise((r) => requestAnimationFrame(r));
        try { f.fit(); } catch { /* still hidden: the server default is used */ }
        const s = await api.terminalStart(conversationId, t.cols, t.rows);
        sid.current = s.session_id;
        setStatus("running");
        let since = 0;
        while (!stopped) {
          const r = await api.terminalOutput(s.session_id, since, 20, abort.signal);
          if (r.data) t.write(base64ToBytes(r.data));
          since = r.next;
          if (!r.alive) {
            setStatus("exited");
            setMessage(r.exit_code != null ? `Shell exited with code ${r.exit_code}.` : "Shell exited.");
            break;
          }
        }
      } catch (err) {
        if (!stopped) {
          setStatus("error");
          setMessage(err.message);
        }
      }
    })();

    return () => {
      stopped = true;
      abort.abort();
      if (flushTimer) clearTimeout(flushTimer);
      onData.dispose();
      onResize.dispose();
      t.dispose();
      term.current = null;
      // Deliberately not closing the server session: see the doc comment.
    };
  }, [conversationId, restartKey]);

  // Refit when the drawer resizes or the tab becomes visible.
  useEffect(() => {
    if (!host.current) return;
    const ro = new ResizeObserver(() => {
      if (!active) return;
      try { fit.current?.fit(); } catch { /* ignore */ }
    });
    ro.observe(host.current);
    if (active) {
      requestAnimationFrame(() => {
        try { fit.current?.fit(); } catch { /* ignore */ }
        term.current?.focus();
      });
    }
    return () => ro.disconnect();
  }, [active]);

  const restart = async () => {
    if (sid.current) await api.terminalClose(sid.current).catch(() => {});
    sid.current = null;
    setMessage("");
    setStatus("starting");
    setRestartKey((k) => k + 1);
  };

  return (
    <div className="ws-terminal">
      <div className="ws-terminal-host" ref={host} />
      {(status === "exited" || status === "error") && (
        <div className="ws-terminal-status" role="status">
          <span>{message}</span>
          <button className="text-btn" onClick={restart}>Start a new shell</button>
        </div>
      )}
    </div>
  );
}
