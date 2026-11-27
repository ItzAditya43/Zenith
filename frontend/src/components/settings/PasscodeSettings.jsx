import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import Select from "../Select.jsx";

/** Settings → Data → Passcode lock: turn on (with a recovery code),
 * change (needs the current passcode), auto-lock, sign out other devices,
 * new recovery code, turn off. */
export default function PasscodeSettings({ lockEnabled, setLockEnabled }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState("");
  const [recovery, setRecovery] = useState(null);
  const [autoLock, setAutoLock] = useState(0);

  useEffect(() => {
    api.lockStatus().then((s) => setAutoLock(s.auto_lock_minutes || 0)).catch(() => {});
  }, [lockEnabled]);

  const keepToken = (res) => {
    if (res?.token !== undefined) sessionStorage.setItem("zenith-unlock", res.token || "");
    if (res?.recovery_code) setRecovery(res.recovery_code);
  };
  const run = async (fn, ok) => {
    setMsg("");
    try {
      await fn();
      if (ok) setMsg(ok);
    } catch (err) {
      setMsg(err.message || "That didn't work.");
    }
  };
  const save = () => run(async () => {
    if (next.length < 4) throw new Error("Passcode must be at least 4 characters.");
    if (next !== confirm) throw new Error("The two new passcodes don't match.");
    keepToken(await api.lockSet(next, current));
    setLockEnabled(true);
    setCurrent(""); setNext(""); setConfirm("");
  }, lockEnabled ? "Passcode changed." : "Lock is on. It's needed next time Zenith opens in a new window.");

  return (
    <div className="passcode-settings">
      {recovery && (
        <div className="backup-preview" role="status">
          <strong>Recovery code — save it now, it won't be shown again</strong>
          <code className="lock-recovery-code">{recovery}</code>
          <span className="setting-hint">Use it on the lock screen ("Forgot passcode?") if you forget your passcode.</span>
          <div><button className="text-btn" onClick={() => setRecovery(null)}>I saved it</button></div>
        </div>
      )}
      <div className="settings-row" style={{ flexWrap: "wrap" }}>
        {lockEnabled && (
          <input className="settings-input" type="password" placeholder="Current passcode" aria-label="Current passcode"
            value={current} onChange={(e) => setCurrent(e.target.value)} />
        )}
        <input className="settings-input" type="password" placeholder={lockEnabled ? "New passcode" : "Passcode (min 4 characters)"}
          aria-label="New passcode" value={next} onChange={(e) => setNext(e.target.value)} />
        <input className="settings-input" type="password" placeholder="Repeat it" aria-label="Repeat new passcode"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        <button className="settings-btn-primary" onClick={save}>{lockEnabled ? "Change passcode" : "Turn lock on"}</button>
      </div>
      {lockEnabled && (
        <>
          <div className="setting-row">
            <div className="setting-meta">
              <span className="setting-label">Lock when idle</span>
              <span className="setting-hint">Locks this window after no keyboard or mouse use.</span>
            </div>
            <Select className="settings-select" value={autoLock} aria-label="Lock when idle"
              onChange={(e) => {
                const v = Number(e.target.value);
                setAutoLock(v);
                run(() => api.lockSettings(v), v ? "Saved — applies next time Zenith opens." : "Saved.");
              }}>
              <option value={0}>Never</option>
              <option value={5}>After 5 minutes</option>
              <option value={15}>After 15 minutes</option>
              <option value={60}>After 1 hour</option>
            </Select>
          </div>
          <div className="settings-row" style={{ flexWrap: "wrap" }}>
            <button className="settings-btn-secondary" onClick={() => run(async () => keepToken(await api.lockRevokeSessions()),
              "Other browsers and devices are signed out; they'll need the passcode again.")}>
              Sign out other devices
            </button>
            <button className="settings-btn-secondary" onClick={() => run(async () => {
              if (!current) throw new Error("Enter your current passcode first.");
              keepToken(await api.lockSet(current, current, true));
            })}>
              New recovery code
            </button>
            <button className="settings-btn-secondary" onClick={() => run(async () => {
              if (!current) throw new Error("Enter your current passcode to turn the lock off.");
              await api.lockDisable(current);
              sessionStorage.removeItem("zenith-unlock");
              setLockEnabled(false);
              setCurrent("");
            }, "Lock turned off.")}>
              Turn lock off
            </button>
          </div>
        </>
      )}
      {msg && <span className="setting-hint" role="status">{msg}</span>}
    </div>
  );
}
