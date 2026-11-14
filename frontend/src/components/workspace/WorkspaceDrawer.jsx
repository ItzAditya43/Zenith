import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import Icon from "../Icon.jsx";

// Heavy pieces load on first use, so opening a plain chat costs nothing.
const CodeEditor = lazy(() => import("./CodeEditor.jsx"));
const TerminalView = lazy(() => import("./TerminalView.jsx"));

const WIDTH_KEY = "zenith-workspace-width";
const TAB_KEY = "zenith-workspace-tab";
const MIN_WIDTH = 360;

function readStored(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function store(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* private mode etc. */
  }
}

function FileTreeNode({ conversationId, entry, depth, onOpen, activePath }) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState(null);

  const toggle = async () => {
    if (!entry.is_dir) {
      onOpen(entry.path);
      return;
    }
    if (!expanded && children === null) {
      try {
        const res = await api.listWorkspaceFiles(conversationId, entry.path);
        setChildren(res.entries);
      } catch {
        setChildren([]);
      }
    }
    setExpanded((v) => !v);
  };

  return (
    <div role="none">
      <button
        className={`ws-tree-row ${entry.path === activePath ? "is-active" : ""}`}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={toggle}
        role="treeitem"
        aria-expanded={entry.is_dir ? expanded : undefined}
        title={entry.path}
      >
        <Icon name={entry.is_dir ? (expanded ? "chevron-down" : "chevron-right") : "file-text"} size={12} />
        <span>{entry.name}</span>
      </button>
      {entry.is_dir && expanded && children != null && (
        <div role="group">
          {children.map((c) => (
            <FileTreeNode key={c.path} conversationId={conversationId} entry={c} depth={depth + 1} onOpen={onOpen} activePath={activePath} />
          ))}
          {children.length === 0 && (
            <div className="ws-tree-empty" style={{ paddingLeft: `${(depth + 1) * 12 + 8}px` }}>empty</div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The workspace drawer: the bound folder's files and a terminal, beside the
 * chat rather than over it. Chat stays the main surface; this is a view onto
 * the same folder the agent works in.
 */
export default function WorkspaceDrawer({ conversationId, workdir, onClose, openRequest, onAskAboutCode }) {
  const [tab, setTab] = useState(() => (readStored(TAB_KEY, "files") === "terminal" ? "terminal" : "files"));
  const [width, setWidth] = useState(() => Math.max(MIN_WIDTH, Number(readStored(WIDTH_KEY, 620)) || 620));
  const [treeOpen, setTreeOpen] = useState(true);
  const [rootEntries, setRootEntries] = useState([]);
  const [error, setError] = useState(null);
  const [tabs, setTabs] = useState([]); // { path, content, dirty, saving }
  const [activePath, setActivePath] = useState(null);
  const [selection, setSelection] = useState(null);
  const [output, setOutput] = useState(null); // { label, text, loading }
  const [terminalMounted, setTerminalMounted] = useState(tab === "terminal");
  const drawer = useRef(null);
  const loading = useRef(new Set()); // paths being fetched

  // The parent keys this component by conversation + folder, so a new
  // folder is a fresh mount and there's no stale state to reset here.
  useEffect(() => {
    api
      .listWorkspaceFiles(conversationId, "")
      .then((res) => setRootEntries(res.entries))
      .catch((err) => setError(err.message));
  }, [conversationId]);

  const switchTab = (next) => {
    setTab(next);
    store(TAB_KEY, next);
    if (next === "terminal") setTerminalMounted(true);
  };

  // Opening a file only adds a tab with no content yet; the effect below
  // fetches whatever tabs are still empty.
  const openFile = (path) => {
    setTab("files");
    setActivePath(path);
    setSelection(null);
    setTabs((prev) => (prev.some((t) => t.path === path) ? prev : [...prev, { path, content: null, dirty: false, saving: false }]));
  };

  // "Open in workspace" from a tool step in the chat: handled while
  // rendering (React's pattern for reacting to a changed prop).
  const [seenRequest, setSeenRequest] = useState(null);
  if (openRequest && openRequest !== seenRequest) {
    setSeenRequest(openRequest);
    if (openRequest.path) openFile(openRequest.path);
  }

  // Results are applied even if the tab list changed meanwhile: the update
  // only fills a tab that is still waiting for content.
  useEffect(() => {
    for (const t of tabs) {
      if (t.content !== null || loading.current.has(t.path)) continue;
      loading.current.add(t.path);
      api
        .readWorkspaceFile(conversationId, t.path)
        .then((res) => {
          setTabs((prev) => prev.map((x) => (x.path === t.path && x.content === null ? { ...x, content: res.content } : x)));
        })
        .catch((err) => {
          setError(err.message);
          setTabs((prev) => prev.filter((x) => !(x.path === t.path && x.content === null)));
        })
        .finally(() => loading.current.delete(t.path));
    }
  }, [tabs, conversationId]);

  const closeTab = (path) => {
    const t = tabs.find((x) => x.path === path);
    if (t?.dirty && !window.confirm(`Discard unsaved changes to ${path.split("/").pop()}?`)) return;
    const remaining = tabs.filter((x) => x.path !== path);
    setTabs(remaining);
    if (activePath === path) setActivePath(remaining.length ? remaining[remaining.length - 1].path : null);
  };

  const editContent = (path, content) => {
    setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, content, dirty: true } : t)));
  };

  const saveTab = async (path) => {
    const t = tabs.find((x) => x.path === path);
    if (!t || t.content == null) return;
    setTabs((prev) => prev.map((x) => (x.path === path ? { ...x, saving: true } : x)));
    try {
      await api.writeWorkspaceFile(conversationId, path, t.content);
      setTabs((prev) => prev.map((x) => (x.path === path ? { ...x, dirty: false, saving: false } : x)));
    } catch (err) {
      setError(err.message);
      setTabs((prev) => prev.map((x) => (x.path === path ? { ...x, saving: false } : x)));
    }
  };

  const run = async (label, fn) => {
    setOutput({ label, text: "", loading: true });
    try {
      const res = await fn();
      setOutput({ label, text: res.output, loading: false });
    } catch (err) {
      setOutput({ label, text: err.message, loading: false });
    }
  };

  const tryClose = () => {
    const dirty = tabs.filter((t) => t.dirty);
    if (dirty.length && !window.confirm(`You have ${dirty.length} unsaved file${dirty.length > 1 ? "s" : ""}. Close anyway?`)) return;
    onClose();
  };

  // Drag the left edge to resize; the width is remembered.
  const startResize = (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = width;
    const max = Math.max(MIN_WIDTH, window.innerWidth - 420);
    const move = (ev) => setWidth(Math.min(max, Math.max(MIN_WIDTH, startW + (startX - ev.clientX))));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.classList.remove("is-resizing");
      setWidth((w) => {
        store(WIDTH_KEY, w);
        return w;
      });
    };
    document.body.classList.add("is-resizing");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const activeTab = tabs.find((t) => t.path === activePath);
  const folderName = workdir.split(/[\\/]/).filter(Boolean).pop() || workdir;

  const askAboutSelection = () => {
    if (!activeTab || !selection) return;
    const ext = (activeTab.path.split(".").pop() || "").toLowerCase();
    const lines = selection.fromLine === selection.toLine ? `L${selection.fromLine}` : `L${selection.fromLine}-${selection.toLine}`;
    onAskAboutCode?.(`\`${activeTab.path}:${lines}\`\n\`\`\`${ext}\n${selection.text}\n\`\`\`\n`);
  };

  return (
    <aside
      className="workspace-drawer"
      ref={drawer}
      style={{ "--ws-width": `${width}px` }}
      aria-label={`Workspace: ${workdir}`}
    >
      <div className="ws-resize-handle" onPointerDown={startResize} role="separator" aria-orientation="vertical" aria-label="Resize workspace" />
      <header className="ws-header">
        <div className="ws-tabs" role="tablist" aria-label="Workspace views">
          <button role="tab" aria-selected={tab === "files"} className={`ws-tab ${tab === "files" ? "is-active" : ""}`} onClick={() => switchTab("files")}>
            <Icon name="file-text" size={13} /> Files
          </button>
          <button role="tab" aria-selected={tab === "terminal"} className={`ws-tab ${tab === "terminal" ? "is-active" : ""}`} onClick={() => switchTab("terminal")}>
            <Icon name="terminal" size={13} /> Terminal
          </button>
        </div>
        <span className="ws-folder" title={workdir}>
          <Icon name="folder" size={12} /> {folderName}
        </span>
        <button className="icon-btn" onClick={tryClose} title="Close workspace" aria-label="Close workspace">
          <Icon name="x" size={14} />
        </button>
      </header>

      {error && (
        <div className="ws-error" role="alert">
          <span>{error}</span>
          <button className="icon-btn" onClick={() => setError(null)} aria-label="Dismiss"><Icon name="x" size={12} /></button>
        </div>
      )}

      <div className="ws-body" hidden={tab !== "files"}>
        {treeOpen && (
          <nav className="ws-tree" role="tree" aria-label="Files">
            {rootEntries.map((e) => (
              <FileTreeNode key={e.path} conversationId={conversationId} entry={e} depth={0} onOpen={openFile} activePath={activePath} />
            ))}
            {!rootEntries.length && !error && <div className="ws-tree-empty">Loading…</div>}
          </nav>
        )}
        <section className="ws-main">
          <div className="ws-filebar">
            <button
              className="icon-btn ws-tree-toggle"
              onClick={() => setTreeOpen((v) => !v)}
              title={treeOpen ? "Hide file tree" : "Show file tree"}
              aria-pressed={treeOpen}
            >
              <Icon name="layers" size={13} />
            </button>
            <div className="ws-filetabs" role="tablist" aria-label="Open files">
              {tabs.map((t) => (
                <div key={t.path} className={`ws-filetab ${t.path === activePath ? "is-active" : ""}`} title={t.path}>
                  <button className="ws-filetab-label" role="tab" aria-selected={t.path === activePath} onClick={() => { setActivePath(t.path); setSelection(null); }}>
                    {t.path.split("/").pop()}
                    {t.dirty && <span className="ws-dirty" aria-label="unsaved">●</span>}
                  </button>
                  <button className="ws-filetab-close" onClick={() => closeTab(t.path)} aria-label={`Close ${t.path.split("/").pop()}`}>
                    <Icon name="x" size={10} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {activeTab ? (
            activeTab.content == null ? (
              <div className="ws-empty">Opening…</div>
            ) : (
              <Suspense fallback={<div className="ws-empty">Loading editor…</div>}>
                <CodeEditor
                  key={activeTab.path}
                  path={activeTab.path}
                  value={activeTab.content}
                  onChange={(c) => editContent(activeTab.path, c)}
                  onSave={() => saveTab(activeTab.path)}
                  onSelectionChange={setSelection}
                />
              </Suspense>
            )
          ) : (
            <div className="ws-empty">
              <p>Open a file from the tree, or click a file in an agent step in the chat.</p>
            </div>
          )}

          <footer className="ws-statusbar">
            {activeTab ? <span className="ws-path">{activeTab.path}</span> : <span className="ws-path">{workdir}</span>}
            <div className="ws-actions">
              {selection && onAskAboutCode && (
                <button className="ws-action ws-action-accent" onClick={askAboutSelection} title="Put the selected lines in the message box">
                  <Icon name="message-square" size={12} /> Ask about selection
                </button>
              )}
              <button className="ws-action" onClick={() => run("git diff", () => api.gitDiff(conversationId, activeTab?.path || ""))}>
                Diff
              </button>
              <button className="ws-action" onClick={() => run("checks", () => api.runChecks(conversationId))} title="Run the check command from Settings → Agent tools">
                Run checks
              </button>
              {activeTab && (
                <button className="ws-action ws-action-primary" disabled={!activeTab.dirty || activeTab.saving} onClick={() => saveTab(activeTab.path)}>
                  {activeTab.saving ? "Saving…" : "Save"} <kbd className="keycap">⌘S</kbd>
                </button>
              )}
            </div>
          </footer>

          {output && (
            <div className="ws-output">
              <div className="ws-output-header">
                <span>{output.label}</span>
                <button className="icon-btn" onClick={() => setOutput(null)} aria-label="Close output"><Icon name="x" size={12} /></button>
              </div>
              <pre className="ws-output-body">{output.loading ? "Running…" : output.text || "(no output)"}</pre>
            </div>
          )}
        </section>
      </div>

      {terminalMounted && (
        <div className="ws-body ws-body-terminal" hidden={tab !== "terminal"}>
          <Suspense fallback={<div className="ws-empty">Loading terminal…</div>}>
            <TerminalView conversationId={conversationId} active={tab === "terminal"} />
          </Suspense>
        </div>
      )}
    </aside>
  );
}
