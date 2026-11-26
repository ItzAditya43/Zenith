import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import MarkdownRenderer from "./MarkdownRenderer.jsx";

/**
 * Deep research gets a persistent home instead of disappearing into a
 * chat thread — a saved report you can reopen and interrogate with
 * follow-up questions grounded in the original findings and sources.
 */
export default function ResearchDashboard({ onClose }) {
  const [reports, setReports] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [asking, setAsking] = useState(false);
  const [notes, setNotes] = useState("");
  const [claims, setClaims] = useState(null);
  const [claimsBusy, setClaimsBusy] = useState(false);
  const [versions, setVersions] = useState([]);
  const [rerun, setRerun] = useState(null);
  const [err, setErr] = useState("");

  const refresh = () => api.listResearchReports().then(setReports).catch(() => {});

  useEffect(() => {
    refresh();
  }, []);

  const open = async (id) => {
    setOpenId(id);
    setAnswer(null);
    setQuestion("");
    setErr("");
    const d = await api.getResearchReport(id);
    setDetail(d);
    setNotes(d.notes || "");
    setClaims(d.claims || null);
    setRerun(null);
    api.researchVersions(id).then(setVersions).catch(() => setVersions([]));
  };

  const findClaims = async (force = false) => {
    setClaimsBusy(true); setErr("");
    try { setClaims((await api.researchClaims(openId, force)).claims); } catch (e) { setErr(e.message); } finally { setClaimsBusy(false); }
  };
  const checkUpdates = async () => {
    setErr("");
    const id = openId;
    setRerun(await api.researchRerun(id));
    const poll = async () => {
      const st = await api.researchRerunStatus(id).catch(() => ({ status: "failed", error: "Lost track of the update." }));
      setRerun(st);
      if (st.status === "running") setTimeout(poll, 3000);
      else if (st.status === "done") refresh();
    };
    setTimeout(poll, 3000);
  };

  const remove = async (id) => {
    await api.deleteResearchReport(id);
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
    }
    refresh();
  };

  const ask = async () => {
    if (!question.trim()) return;
    setAsking(true);
    try {
      const { answer } = await api.askResearchReport(openId, question.trim());
      setAnswer(answer);
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="calendar-overlay" onClick={onClose}>
      <div className="research-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="research-dashboard-title">
        <div className="research-list-pane">
          <div className="calendar-header">
            <span id="research-dashboard-title">Research</span>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
          <ul className="calendar-event-list">
            {reports.map((r) => (
              <li
                key={r.id}
                className={`calendar-event-item ${openId === r.id ? "is-active" : ""}`}
                style={{ cursor: "pointer" }}
                onClick={() => open(r.id)}
              >
                <div className="calendar-event-title" style={{ maxWidth: "220px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.query}
                </div>
                <button className="icon-btn" onClick={(e) => { e.stopPropagation(); remove(r.id); }} title="Delete" aria-label={`Delete report: ${r.query}`}>
                  <Icon name="x" size={13} />
                </button>
              </li>
            ))}
            {reports.length === 0 && <li className="conversation-empty">No saved research yet.</li>}
          </ul>
        </div>
        {detail && (
          <div className="research-detail-pane">
            <h3 className="settings-section-title">{detail.query}</h3>
            <div className="msg-content">
              <MarkdownRenderer content={detail.answer} />
            </div>
            <div className="rw-bar">
              {versions.length > 1 && (
                <span className="rw-versions">
                  {versions.map((v, i) => (
                    <button key={v.id} className={`membrowser-filter ${v.id === openId ? "is-on" : ""}`} onClick={() => open(v.id)}>
                      v{i + 1} · {new Date(v.created_at * 1000).toLocaleDateString()}
                    </button>
                  ))}
                </span>
              )}
              <button className="wf-btn" onClick={checkUpdates} disabled={rerun?.status === "running"}>
                {rerun?.status === "running" ? "Researching again…" : "Check for updates"}
              </button>
            </div>
            {rerun?.status === "done" && (
              <div className="wf-alert review">
                <strong>Updated version saved.</strong>
                <p>{rerun.diff?.added?.length || 0} new source{rerun.diff?.added?.length === 1 ? "" : "s"}, {rerun.diff?.dropped?.length || 0} no longer used.</p>
                <div><button className="wf-btn primary" onClick={() => open(rerun.new_id)}>Open the new version</button></div>
              </div>
            )}
            {rerun?.status === "failed" && <div className="wf-alert error">{rerun.error}</div>}
            {err && <div className="wf-alert error">{err}</div>}
            {detail.sources?.length > 0 && (
              <div className="research-sources">
                <p className="conversation-group-label">Sources</p>
                {detail.sources.map((s, i) => (
                  <a key={i} href={s.url} target="_blank" rel="noreferrer" className="research-source-link">
                    <span className="src-n">{i + 1}</span> {s.title || s.url}
                  </a>
                ))}
              </div>
            )}
            <div className="rw-section">
              <div className="rw-section-head">
                <p className="conversation-group-label">Claims</p>
                {claims ? <button className="text-btn" onClick={() => findClaims(true)} disabled={claimsBusy}>Re-check</button> : null}
              </div>
              {!claims ? (
                <button className="wf-btn" onClick={() => findClaims()} disabled={claimsBusy}>{claimsBusy ? "Reading the report…" : "List the claims and their sources"}</button>
              ) : claims.length === 0 ? <p className="wf-muted">No clear claims found.</p> : (
                <ul className="rw-claims">
                  {claims.map((c, i) => (
                    <li key={i} className={c.supported ? "" : "is-unsupported"}>
                      <span>{c.claim}</span>
                      <span className="rw-refs">
                        {c.supported ? c.sources.map((n) => (
                          <a key={n} className="src-n" href={detail.sources[n - 1]?.url} target="_blank" rel="noreferrer" title={detail.sources[n - 1]?.title}>{n}</a>
                        )) : <em title="None of the sources back this up; it's the model's own inference">no source</em>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="rw-section">
              <p className="conversation-group-label">Your notes</p>
              <textarea className="rw-notes" rows={4} value={notes} placeholder="Anything you want to remember about this research…"
                onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (detail.notes || "") && api.saveResearchNotes(openId, notes).then((d) => setDetail(d)).catch(() => {})} />
            </div>
            <div className="settings-row" style={{ marginTop: "1rem" }}>
              <input
                className="settings-input"
                placeholder="Ask a follow-up…"
                aria-label="Ask a follow-up"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && ask()}
                disabled={asking}
              />
              <button className="settings-btn-primary" onClick={ask} disabled={asking}>
                {asking ? "…" : "Ask"}
              </button>
            </div>
            {answer && <p className="setting-hint" style={{ marginTop: "0.5rem" }}>{answer}</p>}
          </div>
        )}
        {!detail && (
          <div className="research-detail-pane research-detail-empty">
            <Icon name="flask" size={22} />
            <strong>{reports.length ? "Pick a report" : "Your research shows up here"}</strong>
            <span>
              {reports.length
                ? "Open a report to read it, check its sources and ask follow-ups."
                : "Choose Deep Research in the mode menu under the message box, ask a question, and the report is saved here."}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
