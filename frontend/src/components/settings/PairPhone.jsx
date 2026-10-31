import { useState } from "react";
import { api } from "../../lib/api";

// The phone loads the web UI, not the backend: reuse this page's port when
// it was served over http (run.sh / vite), else the default web UI port.
function uiPort() {
  const { protocol, port } = window.location;
  return protocol.startsWith("http") && port ? port : "5173";
}

async function qrSvg(text) {
  const { default: qrcode } = await import("qrcode-generator");
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createSvgTag({ cellSize: 5, margin: 2, scalable: true });
}

/** Settings → Connection → Pair a phone: QR code for this machine's
 * Tailscale/LAN address plus a checklist of the gates that still block it. */
export default function PairPhone({ onEnableLan }) {
  const [info, setInfo] = useState(null);
  const [choice, setChoice] = useState(0);
  const [svg, setSvg] = useState("");
  const [error, setError] = useState(null);

  const load = async (pick = 0, refresh = false) => {
    setError(null);
    try {
      const data = info && !refresh ? info : await api.getPairing();
      setInfo(data);
      setChoice(pick);
      const addr = data.addresses[pick];
      setSvg(addr ? await qrSvg(`http://${addr.host}:${uiPort()}`) : "");
    } catch (err) {
      setError(err.message);
    }
  };

  if (!info) {
    return (
      <div className="setting-row">
        <div className="setting-meta">
          <span className="setting-label">Pair a phone</span>
          <span className="setting-hint">Scan a QR code to open Zenith on your phone.</span>
        </div>
        <button className="settings-btn" onClick={() => load(0)}>
          Show QR
        </button>
        {error && <p className="setting-hint" role="alert">{error}</p>}
      </div>
    );
  }

  const addr = info.addresses[choice];
  const steps = [
    { ok: info.cors_allow_lan, label: "Allow LAN / Tailscale access", fix: onEnableLan },
    { ok: info.gate, label: "Passcode set (Settings → Data)" },
    { ok: !!addr?.backend_reachable, label: "Backend listening on the network (start with ZENITH_BIND=0.0.0.0)" },
  ];
  return (
    <div className="pair-phone">
      {info.addresses.length === 0 ? (
        <p className="setting-hint">No network address found — connect to Wi-Fi or Tailscale.</p>
      ) : (
        <>
          <div className="pair-tabs" role="tablist">
            {info.addresses.map((a, i) => (
              <button key={a.kind} role="tab" aria-selected={i === choice} className={i === choice ? "is-selected" : ""} onClick={() => load(i)}>
                {a.kind === "tailscale" ? "Tailscale" : "Same Wi-Fi"}
              </button>
            ))}
          </div>
          <div className="pair-body">
            {/* eslint-disable-next-line react/no-danger -- SVG from the local QR encoder, no user HTML */}
            <div className="pair-qr" aria-label="QR code" role="img" dangerouslySetInnerHTML={{ __html: svg }} />
            <div>
              <code className="pair-url">http://{addr.host}:{uiPort()}</code>
              <ul className="pair-steps">
                {steps.map((s) => (
                  <li key={s.label} className={s.ok ? "is-ok" : "is-todo"}>
                    <span className="pair-mark">{s.ok ? "[ ok ]" : "[ -- ]"}</span> {s.label}
                    {!s.ok && s.fix && (
                      <button className="settings-btn pair-fix" onClick={async () => { await s.fix(); load(choice, true); }}>
                        Turn on
                      </button>
                    )}
                  </li>
                ))}
              </ul>
              <button className="settings-btn" onClick={() => load(choice, true)}>
                Re-check
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
