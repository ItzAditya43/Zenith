import { useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/**
 * Full-screen passcode gate shown when the app is locked. On success it
 * stores the unlock token (sessionStorage, so it clears when the tab closes)
 * and calls onUnlocked so the app renders. "Forgot passcode?" takes the
 * recovery code shown when the lock was turned on.
 */
export default function LockScreen({ onUnlocked }) {
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [code, setCode] = useState("");
  const [newCode, setNewCode] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (recovering) {
        if (passcode.length < 4) throw new Error("New passcode must be at least 4 characters.");
        const res = await api.lockReset(code, passcode);
        sessionStorage.setItem("zenith-unlock", res.token || "");
        setNewCode(res.recovery_code);
      } else {
        if (!passcode) return;
        const { token } = await api.lockVerify(passcode);
        sessionStorage.setItem("zenith-unlock", token || "");
        onUnlocked();
      }
    } catch (err) {
      setError(err.message || "Incorrect passcode.");
      setPasscode("");
    } finally {
      setBusy(false);
    }
  };

  if (newCode) {
    return (
      <div className="lock-screen">
        <div className="lock-card" role="dialog" aria-modal="true" aria-labelledby="lock-screen-title">
          <div className="lock-mark" aria-hidden="true" />
          <h1 id="lock-screen-title">Passcode changed</h1>
          <p>Your old recovery code no longer works. Save this new one somewhere safe:</p>
          <code className="lock-recovery-code">{newCode}</code>
          <button className="lock-submit" onClick={onUnlocked} autoFocus>I saved it — continue</button>
        </div>
      </div>
    );
  }

  return (
    <div className="lock-screen">
      <form className="lock-card" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="lock-screen-title">
        <div className="lock-mark" aria-hidden="true" />
        <h1 id="lock-screen-title">{recovering ? "Reset passcode" : "Zenith is locked"}</h1>
        <p>{recovering ? "Enter the recovery code you saved when you turned the lock on, then a new passcode." : "Enter your passcode to continue."}</p>
        {recovering && (
          <input
            className="lock-input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="XXXX-XXXX-XXXX-XXXX-XXXX"
            aria-label="Recovery code"
            autoFocus
            autoComplete="off"
          />
        )}
        <input
          type="password"
          className="lock-input"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          placeholder={recovering ? "New passcode" : "Passcode"}
          aria-label={recovering ? "New passcode" : "Passcode"}
          autoFocus={!recovering}
        />
        {error && (
          <span className="lock-error" role="alert">
            <Icon name="alert-triangle" size={13} /> {error}
          </span>
        )}
        <button className="lock-submit" type="submit" disabled={busy || !passcode || (recovering && !code)}>
          {busy ? "Checking…" : recovering ? "Reset passcode" : "Unlock"}
        </button>
        <button type="button" className="lock-link" onClick={() => { setRecovering((r) => !r); setError(""); }}>
          {recovering ? "Back to unlock" : "Forgot passcode?"}
        </button>
        {recovering && (
          <p className="lock-fineprint">
            No recovery code? Whoever can open this computer's files can clear <code>lock_pass_hash</code> in
            Zenith's <code>config.json</code> and restart it.
          </p>
        )}
      </form>
    </div>
  );
}
