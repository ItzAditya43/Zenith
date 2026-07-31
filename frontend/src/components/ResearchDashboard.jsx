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

  const refresh = () => api.listResearchReports().then(setReports).catch(() => {});

  useEffect(() => {
    refresh();
  }, []);

  const open = async (id) => {
    setOpenId(id);
    setAnswer(null);
    setQuestion("");
    const d = await api.getResearchReport(id);
    setDetail(d);
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
      <div className="research-modal" onClick={(e) => e.stopPropagation()}>
        <div className="research-list-pane">
          <div className="calendar-header">
            <span>Research</span>
            <button className="icon-btn" onClick={onClose} title="Close">
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
                <button className="icon-btn" onClick={(e) => { e.stopPropagation(); remove(r.id); }} title="Delete">
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
            {detail.sources?.length > 0 && (
              <div className="research-sources">
                <p className="conversation-group-label">Sources</p>
                {detail.sources.map((s, i) => (
                  <a key={i} href={s.url} target="_blank" rel="noreferrer" className="research-source-link">
                    {s.title || s.url}
                  </a>
                ))}
              </div>
            )}
            <div className="settings-row" style={{ marginTop: "1rem" }}>
              <input
                className="settings-input"
                placeholder="Ask a follow-up…"
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
      </div>
    </div>
  );
}
