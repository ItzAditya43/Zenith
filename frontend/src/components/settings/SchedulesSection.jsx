import { useState } from "react";
import { useSettings } from "./SettingsContext.js";
import Select from "../Select.jsx";

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
    newScheduleTodoMode,
    setNewScheduleTodoMode,
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
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const [kind, setKind] = useState("daily");
  const [timeOfDay, setTimeOfDay] = useState("08:00");
  const [weekdays, setWeekdays] = useState([0]);
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const submit = () =>
    addSchedule(kind === "interval" ? { kind } : { kind, time_of_day: timeOfDay, timezone: zone, ...(kind === "weekly" ? { weekdays } : {}) });

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Scheduled turns</h3>
      <p className="settings-section-desc">
        "Every morning, research X and summarize" without touching the keyboard. Each
        schedule gets its own conversation that keeps a running log across runs.
        Restricted to Chat and Deep Research modes — never Agent — since an unattended
        cron job running shell commands with nobody there to approve it is a real
        escalation, not a formality. Deleting a schedule keeps its conversation and run history.
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
          <Select
            className="settings-select"
            style={{ flex: "0 0 140px" }}
            value={newScheduleMode}
            onChange={(e) => setNewScheduleMode(e.target.value)}
            aria-label="Schedule mode"
          >
            <option value="chat">Chat</option>
            <option value="research">Deep Research</option>
          </Select>
        </div>
        <textarea
          className="settings-textarea"
          rows={2}
          placeholder="Prompt to run each time…"
          aria-label="Prompt to run each time"
          value={newSchedulePrompt}
          onChange={(e) => setNewSchedulePrompt(e.target.value)}
        />
        <div className="settings-row" style={{ flexWrap: "wrap" }}>
          <Select className="settings-select" style={{ flex: "0 0 150px" }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="How often">
            <option value="daily">Every day at</option>
            <option value="weekly">Every week on</option>
            <option value="interval">Repeat every (advanced)</option>
          </Select>
          {kind === "weekly" && (
            <span className="sched-days" role="group" aria-label="Weekdays">
              {DAYS.map((d, i) => (
                <button
                  key={d}
                  type="button"
                  aria-pressed={weekdays.includes(i)}
                  className={weekdays.includes(i) ? "is-on" : ""}
                  onClick={() => setWeekdays((w) => (w.includes(i) ? w.filter((x) => x !== i) : [...w, i]))}
                >
                  {d}
                </button>
              ))}
            </span>
          )}
          {kind !== "interval" ? (
            <input type="time" className="settings-input" style={{ flex: "0 0 110px" }} value={timeOfDay}
              onChange={(e) => setTimeOfDay(e.target.value)} aria-label="Time of day" />
          ) : (
            <Select
              id="sched-interval"
              className="settings-select"
              value={newScheduleInterval}
              onChange={(e) => setNewScheduleInterval(e.target.value)}
              aria-label="Interval"
            >
              <option value={15}>15 minutes</option>
              <option value={60}>hour</option>
              <option value={360}>6 hours</option>
              <option value={1440}>day</option>
              <option value={10080}>week</option>
            </Select>
          )}
          {kind !== "interval" && <span className="setting-hint">{zone} · follows daylight saving</span>}
        </div>
        <div className="settings-row">
          <Select className="settings-select" value={newScheduleTodoMode} onChange={(e) => setNewScheduleTodoMode(e.target.value)} aria-label="Turn results into to-dos">
            <option value="none">No to-dos</option>
            <option value="add">Add the result as a to-do</option>
            <option value="checklist">Add each follow-up it lists</option>
          </Select>
          <button className="settings-btn-primary" onClick={submit}>
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
                  {s.mode} · {s.description || `every ${s.interval_minutes} min`}{s.todo_mode && s.todo_mode !== "none" ? ` · ${s.todo_mode === "add" ? "adds a to-do" : "adds follow-ups as to-dos"}` : ""}
                  {s.last_run_at ? ` · last run ${new Date(s.last_run_at * 1000).toLocaleString()}` : " · never run"}
                  {s.enabled && s.next_run_at ? ` · next ${new Date(s.next_run_at * 1000).toLocaleString()}` : ""}
                  {s.missed_runs ? ` · ${s.missed_runs} missed while asleep` : ""}
                </span>
                {s.consecutive_failures > 0 && (
                  <span className="settings-error" style={{ display: "block", margin: 0 }}>
                    {s.consecutive_failures} failed run{s.consecutive_failures === 1 ? "" : "s"} in a row{!s.enabled ? " — paused" : ""}
                  </span>
                )}
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
                    {new Date(r.started_at * 1000).toLocaleString()} — {r.status}{r.model ? ` · ${r.model}` : ""}
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
