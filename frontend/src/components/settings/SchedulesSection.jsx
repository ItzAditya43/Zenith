import { useSettings } from "./SettingsContext.js";

/** Settings → "schedules" section. State lives in SettingsPanel (see SettingsContext). */
export default function SchedulesSection() {
  const {
    schedules,
    schedulesError,
    newScheduleName,
    setNewScheduleName,
    newSchedulePrompt,
    setNewSchedulePrompt,
    newScheduleMode,
    setNewScheduleMode,
    newScheduleInterval,
    setNewScheduleInterval,
    runningSchedule,
    expandedSchedule,
    scheduleRuns,
    addSchedule,
    deleteSchedule,
    toggleSchedule,
    runScheduleNow,
    toggleExpandSchedule,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Scheduled turns</h3>
      <p className="settings-section-desc">
        "Every morning, research X and summarize" without touching the keyboard. Each
        schedule gets its own conversation that keeps a running log across runs.
        Restricted to Chat and Deep Research modes — never Agent — since an unattended
        cron job running shell commands with nobody there to approve it is a real
        escalation, not a formality.
      </p>

      <div className="setting-row setting-row-stack">
        <div className="settings-row">
          <input
            className="settings-input"
            placeholder="Name, e.g. Morning brief"
            aria-label="Schedule name"
            value={newScheduleName}
            onChange={(e) => setNewScheduleName(e.target.value)}
          />
          <select
            className="settings-select"
            style={{ flex: "0 0 140px" }}
            value={newScheduleMode}
            onChange={(e) => setNewScheduleMode(e.target.value)}
            aria-label="Schedule mode"
          >
            <option value="chat">Chat</option>
            <option value="research">Deep Research</option>
          </select>
        </div>
        <textarea
          className="settings-textarea"
          rows={2}
          placeholder="Prompt to run each time…"
          aria-label="Prompt to run each time"
          value={newSchedulePrompt}
          onChange={(e) => setNewSchedulePrompt(e.target.value)}
        />
        <div className="settings-row">
          <label className="setting-label" htmlFor="sched-interval" style={{ flexShrink: 0 }}>
            Every
          </label>
          <select
            id="sched-interval"
            className="settings-select"
            value={newScheduleInterval}
            onChange={(e) => setNewScheduleInterval(e.target.value)}
          >
            <option value={60}>hour</option>
            <option value={360}>6 hours</option>
            <option value={1440}>day</option>
            <option value={10080}>week</option>
          </select>
          <button className="settings-btn-primary" onClick={addSchedule}>
            Add schedule
          </button>
        </div>
      </div>
      {schedulesError && <p className="settings-error">{schedulesError}</p>}

      <ul className="model-list" style={{ marginTop: "0.75rem" }}>
        {schedules.map((s) => (
          <li key={s.id} style={{ flexDirection: "column", alignItems: "stretch", opacity: s.enabled ? 1 : 0.5 }}>
            <div className="settings-row settings-row-space-between">
              <span className="model-name" style={{ flex: 1 }}>
                {s.name}
                <span className="setting-hint" style={{ display: "block" }}>
                  {s.mode} · every {s.interval_minutes} min
                  {s.last_run_at ? ` · last run ${new Date(s.last_run_at * 1000).toLocaleString()}` : " · never run"}
                </span>
              </span>
              <span className="settings-row" style={{ gap: "0.5rem" }}>
                <button
                  className="text-btn"
                  onClick={() => runScheduleNow(s.id)}
                  disabled={runningSchedule === s.id}
                >
                  {runningSchedule === s.id ? "Running…" : "Run now"}
                </button>
                <button className="text-btn" onClick={() => toggleExpandSchedule(s.id)}>
                  History
                </button>
                <button className="text-btn" onClick={() => toggleSchedule(s.id, !s.enabled)}>
                  {s.enabled ? "On" : "Off"}
                </button>
                <button className="icon-btn" onClick={() => deleteSchedule(s.id)} title="Delete" aria-label="Delete schedule">
                  ×
                </button>
              </span>
            </div>
            {expandedSchedule === s.id && (
              <div className="tool-call-body" style={{ padding: "0.5rem 0 0" }}>
                {(scheduleRuns[s.id] || []).map((r) => (
                  <pre key={r.id} className="tool-call-result" style={{ marginBottom: "0.4rem" }}>
                    {new Date(r.started_at * 1000).toLocaleString()} — {r.status}
                    {"\n"}
                    {r.status === "error" ? r.error : r.summary}
                  </pre>
                ))}
                {(scheduleRuns[s.id] || []).length === 0 && (
                  <span className="setting-hint">No runs yet.</span>
                )}
              </div>
            )}
          </li>
        ))}
        {schedules.length === 0 && !schedulesError && (
          <li className="model-empty">No schedules yet.</li>
        )}
      </ul>
    </section>
  );
}
