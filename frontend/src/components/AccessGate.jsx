import { useState } from "react";
import Icon from "./Icon.jsx";

/**
 * Full-screen gate for the two network-level refusals the backend can send
 * (see backend/app/core/security.py):
 *  - "auth":   shared-secret auth is on — ask for the secret once per device.
 *  - "remote": this device isn't the host machine and the host has no
 *              passcode/secret set yet, so there's nothing to enter here.
 */
export default function AccessGate({ kind, message }) {
  const [secret, setSecret] = useState("");

  const saveSecret = (e) => {
    e.preventDefault();
    if (!secret) return;
    try {
      localStorage.setItem("zenith-secret", secret);
    } catch {
      /* storage blocked — the reload will just ask again */
    }
    window.location.reload();
  };

  if (kind === "remote") {
    return (
      <div className="lock-screen">
        <div className="lock-card" role="dialog" aria-modal="true" aria-labelledby="gate-title">
          <div className="lock-mark" aria-hidden="true" />
          <h1 id="gate-title">Remote access is off</h1>
          <p>
            You're opening Zenith from another device, and the host machine hasn't set a passcode yet.
            On the host, open Settings → Data and set a passcode, then reload this page.
          </p>
          {message && (
            <span className="lock-error">
              <Icon name="alert-triangle" size={13} /> {message}
            </span>
          )}
          <button className="lock-submit" type="button" onClick={() => window.location.reload()}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="lock-screen">
      <form className="lock-card" onSubmit={saveSecret} role="dialog" aria-modal="true" aria-labelledby="gate-title">
        <div className="lock-mark" aria-hidden="true" />
        <h1 id="gate-title">Shared secret required</h1>
        <p>This Zenith server requires its shared secret. It's saved on this device only.</p>
        <input
          type="password"
          className="lock-input"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          placeholder="Shared secret"
          aria-label="Shared secret"
          autoFocus
        />
        <button className="lock-submit" type="submit" disabled={!secret}>
          Continue
        </button>
      </form>
    </div>
  );
}
