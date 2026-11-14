import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import Icon from "../Icon.jsx";
import DiffView from "../DiffView.jsx";

const LETTER = { modified: "M", added: "A", deleted: "D", renamed: "R", copied: "C", untracked: "U", conflict: "!" };

function FileRow({ file, staged, selected, onSelect, onToggle, busy }) {
  return (
    <div className={`ws-change ${selected ? "is-selected" : ""}`}>
      <button className="ws-change-main" onClick={onSelect} title={file.from ? `${file.from} → ${file.path}` : file.path}>
        <span className={`ws-change-letter ws-st-${file.status}`} aria-label={file.status}>{LETTER[file.status] || "M"}</span>
        <span className="ws-change-name">{file.path.split("/").pop()}</span>
        <span className="ws-change-dir">{file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : ""}</span>
      </button>
      <button
        className="icon-btn ws-change-toggle"
        onClick={onToggle}
        disabled={busy}
        title={staged ? "Unstage" : "Stage"}
        aria-label={`${staged ? "Unstage" : "Stage"} ${file.path}`}
      >
        <Icon name={staged ? "minus" : "plus"} size={12} />
      </button>
    </div>
  );
}

/**
 * Git for the working folder: what changed, stage, commit, branch, push,
 * and GitHub issues / pull requests through the `gh` CLI.
 */
export default function ChangesView({ conversationId, active, onOpenFile, onStartIssue, onOpenConversation }) {
  const [st, setSt] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null); // { path, staged }
  const [diff, setDiff] = useState(null);
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState(null);
  const [branchMenu, setBranchMenu] = useState(null); // { current, branches } | null
  const [newBranch, setNewBranch] = useState("");
  const [gh, setGh] = useState(null);
  const [ghTab, setGhTab] = useState("issues");
  const [ghItems, setGhItems] = useState(null);
  const [prForm, setPrForm] = useState(null); // { title, body, draft }
  const [copies, setCopies] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.gitState(conversationId);
      setSt(s);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, [conversationId]);

  // Keep the list current while the tab is visible: the agent edits files
  // in this folder from the chat.
  useEffect(() => {
    if (!active) return undefined;
    let stop = false;
    const tick = () => { if (!stop && document.visibilityState === "visible") refresh(); };
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [active, refresh]);

  useEffect(() => {
    if (!selected) return undefined;
    let cancelled = false;
    api
      .gitFileDiff(conversationId, selected.path, selected.staged)
      .then((r) => { if (!cancelled) setDiff(r.diff || ""); })
      .catch((err) => { if (!cancelled) setDiff(`(${err.message})`); });
    return () => { cancelled = true; };
  }, [selected, conversationId, st]);

  useEffect(() => {
    if (!st?.github || !active) return undefined;
    let cancelled = false;
    api.githubState(conversationId).then((g) => { if (!cancelled) setGh(g); }).catch(() => {});
    return () => { cancelled = true; };
  }, [st?.github, active, conversationId]);

  useEffect(() => {
    if (!gh?.logged_in) return undefined;
    let cancelled = false;
    const load = ghTab === "issues" ? api.githubIssues(conversationId).then((r) => r.issues) : api.githubPulls(conversationId).then((r) => r.pulls);
    load.then((items) => { if (!cancelled) setGhItems(items); }).catch((err) => { if (!cancelled) setGhItems({ error: err.message }); });
    return () => { cancelled = true; };
  }, [gh?.logged_in, ghTab, conversationId]);

  useEffect(() => {
    if (!st?.is_repo || !active) return undefined;
    let cancelled = false;
    api.gitWorktrees(conversationId).then((r) => { if (!cancelled) setCopies(r.worktrees); }).catch(() => {});
    return () => { cancelled = true; };
  }, [st?.is_repo, active, conversationId]);

  const newCopy = async () => {
    const name = window.prompt("What's the task? It becomes the branch and chat name.", "");
    if (!name || !name.trim()) return;
    setBusy(true);
    try {
      const r = await api.gitNewWorktree(conversationId, name.trim());
      setNotice(`Created ${r.branch} in ${r.path}`);
      onOpenConversation?.(r.conversation_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const removeCopy = async (path) => {
    if (!window.confirm(`Remove the separate copy at ${path}? Its branch stays.`)) return;
    setBusy(true);
    try {
      await api.gitRemoveWorktree(conversationId, path);
      setCopies((c) => (c || []).filter((w) => w.path !== path));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const act = async (fn, after) => {
    setBusy(true);
    setNotice(null);
    try {
      const r = await fn();
      if (r?.is_repo !== undefined) setSt(r);
      else if (r?.status) setSt(r.status);
      after?.(r);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (file, staged) =>
    act(() => (staged ? api.gitUnstage(conversationId, [file.path]) : api.gitStage(conversationId, [file.path])), () => {
      if (selected?.path === file.path) setSelected({ path: file.path, staged: !staged });
    });

  const commit = () =>
    act(() => api.gitCommit(conversationId, message), (r) => {
      setMessage("");
      setSelected(null);
      setNotice(`Committed ${r.commit}`);
    });

  const push = () => {
    if (!window.confirm(`Push ${st.branch} to ${st.upstream || "origin"}?`)) return;
    act(() => api.gitPush(conversationId), () => setNotice("Pushed."));
  };

  const openBranches = async () => {
    if (branchMenu) { setBranchMenu(null); return; }
    try { setBranchMenu(await api.gitBranches(conversationId)); } catch (err) { setError(err.message); }
  };
  const switchTo = (name, create) =>
    act(() => api.gitSwitch(conversationId, name, create), () => { setBranchMenu(null); setNewBranch(""); setSelected(null); });

  const startIssue = async (n) => {
    try {
      const issue = await api.githubIssue(conversationId, n);
      onStartIssue?.(issue, st?.branch);
    } catch (err) {
      setError(err.message);
    }
  };

  const openPrForm = async () => {
    let title = "";
    try {
      const { commits } = await api.gitLog(conversationId, 1);
      title = commits[0]?.subject || "";
    } catch { /* leave empty */ }
    setPrForm({ title, body: "", draft: false });
  };
  const createPr = () =>
    act(() => api.githubCreatePull(conversationId, prForm), (r) => {
      setPrForm(null);
      setNotice(`Opened ${r.url}`);
      setGhTab("pulls");
    });

  if (error && !st) return <div className="ws-empty">{error}</div>;
  if (!st) return <div className="ws-empty">Loading…</div>;
  if (!st.is_repo) {
    return (
      <div className="ws-empty">
        <p>This folder isn&apos;t a git repository. Run <code>git init</code> in the Terminal tab to start tracking it.</p>
      </div>
    );
  }

  const total = st.staged.length + st.unstaged.length;

  return (
    <div className="ws-changes">
      <div className="ws-git-bar">
        <button className="ws-branch" onClick={openBranches} aria-expanded={!!branchMenu} title="Switch or create a branch">
          <Icon name="git-branch" size={13} /> {st.branch}
          <Icon name="chevron-down" size={11} />
        </button>
        {st.upstream ? (
          <span className="ws-sync" title={`Tracking ${st.upstream}`}>
            {st.ahead > 0 && <span>↑{st.ahead}</span>}
            {st.behind > 0 && <span>↓{st.behind}</span>}
            {!st.ahead && !st.behind && <span>up to date</span>}
          </span>
        ) : st.remote ? (
          <span className="ws-sync">not pushed</span>
        ) : (
          <span className="ws-sync">no remote</span>
        )}
        <div className="ws-git-actions">
          {st.remote && (st.ahead > 0 || !st.upstream) && (
            <button className="ws-action ws-action-primary" onClick={push} disabled={busy}>Push</button>
          )}
          {st.github && gh?.logged_in && !st.detached && (
            <button className="ws-action" onClick={openPrForm} disabled={busy}>Open PR</button>
          )}
          <button className="icon-btn" onClick={refresh} title="Refresh" aria-label="Refresh"><Icon name="rotate-ccw" size={12} /></button>
        </div>
      </div>

      {branchMenu && (
        <div className="ws-branch-menu">
          {branchMenu.branches.map((b) => (
            <button key={b} className={`ws-branch-item ${b === branchMenu.current ? "is-current" : ""}`} disabled={b === branchMenu.current || busy} onClick={() => switchTo(b, false)}>
              {b}
            </button>
          ))}
          <form className="ws-branch-new" onSubmit={(e) => { e.preventDefault(); if (newBranch.trim()) switchTo(newBranch.trim(), true); }}>
            <input className="settings-input" placeholder="new-branch-name" value={newBranch} onChange={(e) => setNewBranch(e.target.value)} aria-label="New branch name" />
            <button className="ws-action" type="submit" disabled={!newBranch.trim() || busy}>Create</button>
          </form>
        </div>
      )}

      {(error || notice) && (
        <div className={error ? "ws-error" : "ws-notice"} role={error ? "alert" : "status"}>
          <span>{error || notice}</span>
          <button className="icon-btn" onClick={() => { setError(null); setNotice(null); }} aria-label="Dismiss"><Icon name="x" size={12} /></button>
        </div>
      )}

      {prForm && (
        <form className="ws-pr-form" onSubmit={(e) => { e.preventDefault(); createPr(); }}>
          <input className="settings-input" placeholder="Pull request title" value={prForm.title} onChange={(e) => setPrForm({ ...prForm, title: e.target.value })} aria-label="Pull request title" />
          <textarea className="settings-input" rows={4} placeholder="What changed and why" value={prForm.body} onChange={(e) => setPrForm({ ...prForm, body: e.target.value })} aria-label="Pull request description" />
          <div className="ws-pr-row">
            <label className="ws-check"><input type="checkbox" checked={prForm.draft} onChange={(e) => setPrForm({ ...prForm, draft: e.target.checked })} /> Draft</label>
            <span className="ws-hint">Pushes {st.branch} first if needed.</span>
            <button type="button" className="ws-action" onClick={() => setPrForm(null)}>Cancel</button>
            <button type="submit" className="ws-action ws-action-primary" disabled={!prForm.title.trim() || busy}>Create pull request</button>
          </div>
        </form>
      )}

      <div className="ws-changes-scroll">
        <div className="ws-commit">
          <textarea
            className="settings-input ws-commit-msg"
            rows={2}
            placeholder={st.staged.length ? `Message for ${st.staged.length} staged file${st.staged.length > 1 ? "s" : ""} (⌘↵ to commit)` : "Stage files below, then write a commit message"}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && message.trim() && st.staged.length) { e.preventDefault(); commit(); } }}
            aria-label="Commit message"
          />
          <button className="ws-action ws-action-primary" onClick={commit} disabled={busy || !message.trim() || !st.staged.length}>
            Commit
          </button>
        </div>

        {total === 0 && <p className="ws-hint ws-clean">No changes. Edits you or the agent make in this folder show up here.</p>}

        {st.staged.length > 0 && (
          <section className="ws-change-group">
            <header>
              <span>Staged <span className="ws-count">{st.staged.length}</span></span>
              <button className="text-btn" disabled={busy} onClick={() => act(() => api.gitUnstage(conversationId, st.staged.map((f) => f.path)))}>Unstage all</button>
            </header>
            {st.staged.map((f) => (
              <FileRow key={`s:${f.path}`} file={f} staged busy={busy}
                selected={selected?.path === f.path && selected.staged}
                onSelect={() => setSelected({ path: f.path, staged: true })}
                onToggle={() => toggle(f, true)} />
            ))}
          </section>
        )}
        {st.unstaged.length > 0 && (
          <section className="ws-change-group">
            <header>
              <span>Changes <span className="ws-count">{st.unstaged.length}</span></span>
              <button className="text-btn" disabled={busy} onClick={() => act(() => api.gitStage(conversationId, st.unstaged.map((f) => f.path)))}>Stage all</button>
            </header>
            {st.unstaged.map((f) => (
              <FileRow key={`u:${f.path}`} file={f} staged={false} busy={busy}
                selected={selected?.path === f.path && !selected.staged}
                onSelect={() => setSelected({ path: f.path, staged: false })}
                onToggle={() => toggle(f, false)} />
            ))}
          </section>
        )}

        {selected && diff != null && (
          <section className="ws-diff">
            <header>
              <span className="ws-path">{selected.path}{selected.staged ? " (staged)" : ""}</span>
              <div>
                {onOpenFile && <button className="text-btn" onClick={() => onOpenFile(selected.path)}>Open file</button>}
                <button className="icon-btn" onClick={() => setSelected(null)} aria-label="Close diff"><Icon name="x" size={12} /></button>
              </div>
            </header>
            {diff ? <DiffView diff={diff} /> : <p className="ws-hint">No textual changes (binary or mode change).</p>}
          </section>
        )}

        <section className="ws-change-group ws-copies">
          <header>
            <span>Separate copies {copies?.length ? <span className="ws-count">{copies.length}</span> : null}</span>
            <button className="text-btn" onClick={newCopy} disabled={busy} title="A new branch in its own folder, with its own chat, so the agent can work without touching this checkout">
              New task in a separate copy
            </button>
          </header>
          {!copies?.length && (
            <p className="ws-hint">Give the agent a task on its own branch and folder, then review it here and open a pull request.</p>
          )}
          {copies?.map((w) => (
            <div className="ws-gh-item" key={w.path}>
              <span className="ws-gh-title" title={w.path}><Icon name="git-branch" size={11} /> {w.branch || w.path}</span>
              <button className="text-btn" onClick={() => removeCopy(w.path)} disabled={busy}>Remove</button>
            </div>
          ))}
        </section>

        {st.github && (
          <section className="ws-change-group ws-github">
            <header>
              <span className="ws-gh-tabs" role="tablist">
                <button role="tab" aria-selected={ghTab === "issues"} className={ghTab === "issues" ? "is-active" : ""} onClick={() => { setGhTab("issues"); setGhItems(null); }}>Issues</button>
                <button role="tab" aria-selected={ghTab === "pulls"} className={ghTab === "pulls" ? "is-active" : ""} onClick={() => { setGhTab("pulls"); setGhItems(null); }}>Pull requests</button>
              </span>
            </header>
            {gh && !gh.installed && <p className="ws-hint">Install the GitHub CLI (<code>gh</code>) and run <code>gh auth login</code> to see issues and open pull requests here.</p>}
            {gh?.installed && !gh.logged_in && <p className="ws-hint">Run <code>gh auth login</code> in the Terminal tab to connect GitHub.</p>}
            {gh?.logged_in && ghItems == null && <p className="ws-hint">Loading…</p>}
            {ghItems?.error && <p className="ws-hint">{ghItems.error}</p>}
            {Array.isArray(ghItems) && ghItems.length === 0 && <p className="ws-hint">Nothing open.</p>}
            {Array.isArray(ghItems) && ghItems.map((it) => (
              <div className="ws-gh-item" key={it.number}>
                <a href={it.url} target="_blank" rel="noreferrer" className="ws-gh-title">
                  <span className="ws-count">#{it.number}</span> {it.title}
                </a>
                {ghTab === "issues" && onStartIssue && (
                  <button className="text-btn" onClick={() => startIssue(it.number)} title="Start a chat message to work on this issue">Work on it</button>
                )}
                {ghTab === "pulls" && <span className="ws-hint">{it.headRefName}{it.isDraft ? " · draft" : ""}</span>}
              </div>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}
