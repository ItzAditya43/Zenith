import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { confirmDialog } from "../lib/dialogs";
import Icon from "./Icon.jsx";
import Select from "./Select.jsx";

const CATS = { urgent: "Urgent", reply: "Needs reply", fyi: "FYI", newsletter: "Newsletters" };
const TABS = [["all", "All"], ["urgent", "Urgent"], ["reply", "Needs reply"], ["fyi", "FYI"], ["newsletter", "Newsletters"], ["drafts", "Drafts"], ["filters", "Filters"]];

function when(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Inbox with triage (urgent / needs reply / FYI / newsletters), your own
 * filters, and reply drafts that are only sent when you press Send. */
export default function MailPanel({ onClose, onOpenSettings }) {
  const [tab, setTab] = useState("all");
  const [mail, setMail] = useState(null);
  const [drafts, setDrafts] = useState([]);
  const [filters, setFilters] = useState([]);
  const [sel, setSel] = useState(null);
  const [msg, setMsg] = useState(null);
  const [summary, setSummary] = useState("");
  const [draft, setDraft] = useState(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [newFilter, setNewFilter] = useState({ name: "", field: "from", contains: "", category: "newsletter" });

  const load = useCallback(async () => {
    try {
      const [m, d, f] = await Promise.all([api.emailInbox(), api.emailDrafts(), api.emailFilters()]);
      setMail(m); setDrafts(d); setFilters(f); setError("");
    } catch (e) { setError(e.message); setMail([]); }
  }, []);
  useEffect(() => {
    Promise.all([api.emailInbox(), api.emailDrafts(), api.emailFilters()])
      .then(([m, d, f]) => { setMail(m); setDrafts(d); setFilters(f); })
      .catch((e) => { setError(e.message); setMail([]); });
  }, []);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const openMsg = async (m) => {
    setSel(m.id); setMsg(null); setSummary(""); setDraft(drafts.find((d) => d.message_id === m.id) || null);
    try { setMsg(await api.emailMessage(m.id)); } catch (e) { setError(e.message); }
  };
  const triage = async () => {
    setBusy("triage");
    try { const r = await api.emailTriage(true); if (r.error) setError(r.error); await load(); } finally { setBusy(""); }
  };
  const makeDraft = async () => {
    setBusy("draft");
    try { const d = await api.createEmailDraft(sel, instruction); setDraft(d); setInstruction(""); setDrafts(await api.emailDrafts()); }
    catch (e) { setError(e.message); } finally { setBusy(""); }
  };
  const saveDraft = async (patch) => { setDraft((d) => ({ ...d, ...patch })); };
  const send = async () => {
    if (!(await confirmDialog({ title: `Send to ${draft.to_addr}?`, message: draft.subject, confirmLabel: "Send" }))) return;
    setBusy("send");
    try {
      await api.updateEmailDraft(draft.id, { to: draft.to_addr, subject: draft.subject, body: draft.body });
      await api.sendEmailDraft(draft.id);
      setDraft(null); await load();
    } catch (e) { setError(e.message); } finally { setBusy(""); }
  };
  const discard = async () => { await api.discardEmailDraft(draft.id); setDraft(null); setDrafts(await api.emailDrafts()); };

  const rows = mail ? (tab === "all" ? mail : mail.filter((m) => m.category === tab)) : [];
  const notConfigured = error && /isn't configured|Missing email config/i.test(error);

  return createPortal(
    <div className="notes-overlay" onClick={onClose}>
      <div className="notes-modal mail-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="mail-title">
        <div className="notes-header">
          <span id="mail-title"><Icon name="at-sign" size={16} /> Mail</span>
          <div className="membrowser-head-actions">
            <button className="wf-btn" onClick={triage} disabled={!!busy || notConfigured}>{busy === "triage" ? "Sorting…" : "Sort inbox"}</button>
            <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" size={14} /></button>
          </div>
        </div>
        {notConfigured ? (
          <div className="cmp-empty">
            <p className="wf-muted">Connect your mailbox first. Zenith reads it over IMAP and sends over SMTP from this machine; drafts are never sent without you.</p>
            <button className="wf-btn primary" onClick={() => { onClose(); onOpenSettings("email"); }}>Set up email</button>
          </div>
        ) : (
          <>
            <div className="rr-tabs" style={{ flexWrap: "wrap" }}>
              {TABS.map(([k, l]) => {
                const n = k === "drafts" ? drafts.length : k === "filters" ? filters.length : k === "all" ? null : (mail || []).filter((m) => m.category === k).length;
                return <button key={k} className={`membrowser-filter ${tab === k ? "is-on" : ""}`} onClick={() => setTab(k)}>{l}{n ? ` · ${n}` : ""}</button>;
              })}
            </div>
            {error && <div className="cstate-error" style={{ margin: "0 26px 10px" }}>{error}</div>}
            {tab === "filters" ? (
              <div className="membrowser-list">
                <p className="wf-muted" style={{ margin: 0 }}>Filters sort matching mail before the model looks at it, so they're instant and predictable.</p>
                <div className="mail-filter-new">
                  <Select value={newFilter.field} onChange={(e) => setNewFilter((f) => ({ ...f, field: e.target.value }))} aria-label="Field">
                    <option value="from">From contains</option><option value="subject">Subject contains</option><option value="body">Text contains</option>
                  </Select>
                  <input placeholder="e.g. github.com" value={newFilter.contains} onChange={(e) => setNewFilter((f) => ({ ...f, contains: e.target.value }))} />
                  <Select value={newFilter.category} onChange={(e) => setNewFilter((f) => ({ ...f, category: e.target.value }))} aria-label="Category">
                    {Object.entries(CATS).map(([k, l]) => <option key={k} value={k}>→ {l}</option>)}
                  </Select>
                  <button className="wf-btn primary" disabled={!newFilter.contains.trim()} onClick={async () => { try { await api.addEmailFilter(newFilter); setNewFilter((f) => ({ ...f, contains: "" })); setFilters(await api.emailFilters()); } catch (e) { setError(e.message); } }}>Add</button>
                </div>
                {filters.map((f) => (
                  <div key={f.id} className="cleanup-hist">
                    <span>{f.field} contains “{f.contains}” → {CATS[f.category]}</span>
                    <button className="cstate-del" onClick={async () => { await api.deleteEmailFilter(f.id); setFilters(await api.emailFilters()); }} aria-label="Delete filter"><Icon name="trash" size={13} /></button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="tasks-body">
                <ul className="tasks-list">
                  {mail === null && <li className="wf-muted" style={{ padding: 12 }}>Loading…</li>}
                  {tab === "drafts" ? drafts.map((d) => (
                    <li key={d.id}><button className={sel === d.message_id ? "is-on" : ""} onClick={() => openMsg({ id: d.message_id })}>
                      <span className="task-dot s-waiting" /><span className="task-text"><strong>{d.subject}</strong><em>to {d.to_addr}</em></span>
                    </button></li>
                  )) : rows.map((m) => (
                    <li key={m.id}><button className={sel === m.id ? "is-on" : ""} onClick={() => openMsg(m)}>
                      <span className={`task-dot mail-${m.category || "none"}`} />
                      <span className="task-text"><strong>{m.subject || "(no subject)"}</strong><em>{m.from} · {when(m.date)}{m.has_draft ? " · draft ready" : ""}</em></span>
                    </button></li>
                  ))}
                  {mail && rows.length === 0 && tab !== "drafts" && <li className="wf-muted" style={{ padding: 12 }}>Nothing here.</li>}
                </ul>
                <div className="tasks-detail">
                  {!sel ? <p className="wf-muted">Pick a message.</p> : !msg ? <p className="wf-muted">Opening…</p> : (
                    <>
                      <div className="tasks-detail-head">
                        {mail?.find((m) => m.id === sel)?.category && <span className="mb-badge">{CATS[mail.find((m) => m.id === sel).category]}</span>}
                        <div className="tasks-detail-actions">
                          <button className="wf-btn" onClick={async () => { setBusy("sum"); try { setSummary((await api.emailSummarize(sel)).summary); } finally { setBusy(""); } }} disabled={!!busy}>{busy === "sum" ? "Summarising…" : "Summarise"}</button>
                        </div>
                      </div>
                      <h3 className="mail-subject">{msg.subject}</h3>
                      <p className="wf-muted" style={{ margin: "0 0 10px" }}>{msg.from}</p>
                      {mail?.find((m) => m.id === sel)?.reason && <p className="wf-muted" style={{ margin: "0 0 10px" }}>Why: {mail.find((m) => m.id === sel).reason}</p>}
                      {summary && <div className="wf-alert review"><strong>Summary</strong><p>{summary}</p></div>}
                      <pre className="wf-out mail-body">{msg.body}</pre>
                      {draft ? (
                        <div className="mail-draft">
                          <h4 className="tasks-h4">Your reply — nothing is sent until you press Send</h4>
                          <input value={draft.to_addr} onChange={(e) => saveDraft({ to_addr: e.target.value })} aria-label="To" />
                          <input value={draft.subject} onChange={(e) => saveDraft({ subject: e.target.value })} aria-label="Subject" />
                          <textarea rows={8} value={draft.body} onChange={(e) => saveDraft({ body: e.target.value })} aria-label="Reply" />
                          <div className="pack-actions">
                            <button className="wf-btn danger" onClick={discard}>Discard</button>
                            <button className="wf-btn" onClick={async () => { await api.updateEmailDraft(draft.id, { to: draft.to_addr, subject: draft.subject, body: draft.body }); setDrafts(await api.emailDrafts()); }}>Save draft</button>
                            <button className="wf-btn primary" onClick={send} disabled={busy === "send"}>{busy === "send" ? "Sending…" : "Send"}</button>
                          </div>
                        </div>
                      ) : (
                        <div className="mail-draft-new">
                          <input value={instruction} placeholder="How should the reply go? (optional, e.g. 'say yes, ask for Thursday')" onChange={(e) => setInstruction(e.target.value)} />
                          <button className="wf-btn primary" onClick={makeDraft} disabled={!!busy}>{busy === "draft" ? "Drafting…" : "Draft a reply"}</button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
