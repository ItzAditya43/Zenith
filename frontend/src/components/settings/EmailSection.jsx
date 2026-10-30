import { useSettings } from "./SettingsContext.js";

/** Settings → "email" section. State lives in SettingsPanel (see SettingsContext). */
export default function EmailSection() {
  const {
    config,
    emailForm,
    setEmailForm,
    emailTestStatus,
    emailTesting,
    emailMessages,
    emailMessagesError,
    openEmailId,
    emailDetail,
    emailDraft,
    setEmailDraft,
    emailBusy,
    emailResearch,
    refreshEmailInbox,
    saveEmailConfig,
    testEmailConnection,
    openEmail,
    summarizeEmail,
    draftEmailReply,
    sendEmailReply,
  } = useSettings();

  return (
    <section className="settings-section">
      <h3 className="settings-section-title">Email</h3>
      <p className="settings-section-desc">
        Connect your own IMAP/SMTP account — no third-party mail API. Credentials are
        stored the same way as other local settings (plaintext in Zenith's own config
        file, not encrypted at rest — use an app password if your provider supports
        one). Summaries and reply drafts run on your local model; nothing sends until
        you review and hit send.
      </p>
      <div className="settings-row">
        <input
          className="settings-input"
          placeholder="IMAP host (e.g. imap.gmail.com)"
          aria-label="IMAP host"
          value={emailForm.email_imap_host}
          onChange={(e) => setEmailForm((f) => ({ ...f, email_imap_host: e.target.value }))}
        />
        <input
          className="settings-input"
          style={{ maxWidth: "90px" }}
          placeholder="Port"
          aria-label="IMAP port"
          type="number"
          value={emailForm.email_imap_port}
          onChange={(e) => setEmailForm((f) => ({ ...f, email_imap_port: Number(e.target.value) }))}
        />
      </div>
      <div className="settings-row" style={{ marginTop: "0.5rem" }}>
        <input
          className="settings-input"
          placeholder="SMTP host (e.g. smtp.gmail.com)"
          aria-label="SMTP host"
          value={emailForm.email_smtp_host}
          onChange={(e) => setEmailForm((f) => ({ ...f, email_smtp_host: e.target.value }))}
        />
        <input
          className="settings-input"
          style={{ maxWidth: "90px" }}
          placeholder="Port"
          aria-label="SMTP port"
          type="number"
          value={emailForm.email_smtp_port}
          onChange={(e) => setEmailForm((f) => ({ ...f, email_smtp_port: Number(e.target.value) }))}
        />
      </div>
      <div className="settings-row" style={{ marginTop: "0.5rem" }}>
        <input
          className="settings-input"
          placeholder="Email address"
          aria-label="Email address"
          value={emailForm.email_username}
          onChange={(e) => setEmailForm((f) => ({ ...f, email_username: e.target.value }))}
        />
        <input
          className="settings-input"
          placeholder="App password"
          aria-label="App password"
          type="password"
          value={emailForm.email_password}
          onChange={(e) => setEmailForm((f) => ({ ...f, email_password: e.target.value }))}
        />
      </div>
      <div className="settings-row" style={{ marginTop: "0.75rem" }}>
        <button className="settings-btn-primary" onClick={testEmailConnection} disabled={emailTesting}>
          {emailTesting ? "Testing…" : "Save & test connection"}
        </button>
        {config?.email_enabled && (
          <button className="text-btn" onClick={() => saveEmailConfig(false)}>
            Disconnect
          </button>
        )}
      </div>
      {emailTestStatus && (
        <p className={emailTestStatus.ok ? "setting-hint" : "settings-error"}>
          {emailTestStatus.message}
        </p>
      )}

      {config?.email_enabled && (
        <>
          <h3 className="settings-section-title" style={{ marginTop: "1.5rem" }}>
            Inbox
          </h3>
          {emailMessagesError && <p className="settings-error">{emailMessagesError}</p>}
          <button className="text-btn" onClick={refreshEmailInbox} style={{ marginBottom: "0.5rem" }}>
            Refresh
          </button>
          <ul className="model-list">
            {emailMessages.map((m) => (
              <li key={m.id} style={{ display: "block" }}>
                <div
                  className="settings-row"
                  style={{ cursor: "pointer", justifyContent: "space-between" }}
                  onClick={() => openEmail(openEmailId === m.id ? null : m.id)}
                >
                  <span className="model-name" style={{ flex: 1 }}>
                    {m.subject || "(no subject)"}
                    <span style={{ display: "block", fontSize: "0.75em", color: "var(--text-tertiary)" }}>
                      {m.from} — {m.snippet}
                    </span>
                  </span>
                </div>
                {openEmailId === m.id && emailDetail && (
                  <div style={{ padding: "0.5rem 0" }}>
                    <pre className="plan-card-body">{emailDetail.body}</pre>
                    <div className="settings-row">
                      <button className="text-btn" onClick={() => summarizeEmail(m.id)} disabled={emailBusy}>
                        Summarize
                      </button>
                      <button className="text-btn" onClick={() => draftEmailReply(m.id)} disabled={emailBusy}>
                        Draft reply
                      </button>
                    </div>
                    {emailDetail.summary && <p className="setting-hint">{emailDetail.summary}</p>}
                    {emailResearch && (
                      <p className="setting-hint">
                        Researched "{emailResearch.research_query}" before drafting
                        {emailResearch.research_sources?.length > 0 &&
                          ` — ${emailResearch.research_sources.length} source(s) used.`}
                      </p>
                    )}
                    {emailDraft && (
                      <>
                        <textarea
                          className="settings-input"
                          style={{ width: "100%", minHeight: "100px", marginTop: "0.5rem" }}
                          aria-label="Reply draft"
                          value={emailDraft}
                          onChange={(e) => setEmailDraft(e.target.value)}
                        />
                        <button
                          className="settings-btn-primary"
                          style={{ marginTop: "0.5rem" }}
                          onClick={sendEmailReply}
                          disabled={emailBusy}
                        >
                          Send
                        </button>
                      </>
                    )}
                  </div>
                )}
              </li>
            ))}
            {emailMessages.length === 0 && !emailMessagesError && (
              <li className="model-empty">No messages loaded yet.</li>
            )}
          </ul>
        </>
      )}
    </section>
  );
}
