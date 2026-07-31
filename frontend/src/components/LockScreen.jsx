import { useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/**
 * Full-screen passcode gate shown when the app is locked. On success it
 * stores the unlock token (sessionStorage, so it clears when the tab closes)
 * and calls onUnlocked so the app renders.
 */
export default function LockScreen({ onUnlocked }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!passcode || busy) return;
    setBusy(true);
    setError("");
    try {
      const { token } = await api.lockVerify(passcode);
      sessionStorage.setItem("zenith-unlock", token || "");
      onUnlocked();
    } catch (err) {
      setError(err.message || "Incorrect passcode.");
      setPasscode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="lock-screen">
      <form className="lock-card" onSubmit={submit}>
        <div className="lock-mark" aria-hidden="true" />
        <h1>Zenith is locked</h1>
        <p>Enter your passcode to continue.</p>
        <input
          type="password"
          className="lock-input"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          placeholder="Passcode"
          autoFocus
        />
        {error && (
          <span className="lock-error">
            <Icon name="alert-triangle" size={13} /> {error}
          </span>
        )}
        <button className="lock-submit" type="submit" disabled={busy || !passcode}>
          {busy ? "Unlocking…" : "Unlock"}
        </button>
      </form>
    </div>
  );
}
