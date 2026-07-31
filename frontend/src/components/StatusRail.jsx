import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

/**
 * The "instrument panel" identity piece: a live strip showing what's
 * actually happening on your machine right now — the model currently
 * generating and its real tok/s, plus a count of background processes
 * (persistent shell sessions, open browser automation sessions) a cloud
 * assistant has no equivalent of, because it isn't running on your machine.
 */
export default function StatusRail({ genStats }) {
  const [activity, setActivity] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const tick = () => api.activity().then(setActivity).catch(() => {});
    tick();
    const id = setInterval(tick, 8000);
    return () => clearInterval(id);
  }, []);

  const busyCount = activity?.count || 0;
  const urgentEmails = activity?.urgent_emails || 0;

  return (
    <div className="status-rail">
      {genStats && (
        <span className="status-rail-gen" title={`Generating with ${genStats.model}`}>
          <span className="status-rail-pulse" />
          <span className="status-rail-model">{genStats.model}</span>
          <span className="status-rail-tps">{genStats.tokPerSec.toFixed(0)} tok/s</span>
        </span>
      )}
      {urgentEmails > 0 && (
        <span className="status-rail-urgent" title={`${urgentEmails} urgent email(s) flagged`}>
          <Icon name="at-sign" size={12} />
          {urgentEmails}
        </span>
      )}
      {busyCount > 0 && (
        <div className="status-rail-activity">
          <button
            className={`status-rail-btn ${open ? "is-open" : ""}`}
            onClick={() => setOpen((v) => !v)}
            title="Background activity"
          >
            <Icon name="terminal" size={13} />
            <span>{busyCount} active</span>
          </button>
          {open && (
            <div className="status-rail-popover">
              {activity.shell_sessions.map((s) => (
                <div key={s.id} className="status-rail-item">
                  <Icon name="terminal" size={13} />
                  <span>{s.command}</span>
                </div>
              ))}
              {activity.browser_sessions.map((s, i) => (
                <div key={i} className="status-rail-item">
                  <Icon name="globe" size={13} />
                  <span>{s.url}</span>
                </div>
              ))}
              {busyCount === 0 && <div className="status-rail-item">Nothing running.</div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
