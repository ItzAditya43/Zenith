import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
// Deliberately no Escape-to-close here, unlike the other panels: this
// one has a text editor with unsaved changes in it, and Escape closing
// the whole thing while you're mid-edit would be a data-loss trap.

// Same lazy-loaded Prism build + theme MarkdownRenderer.jsx uses for chat
// code blocks — reused here for visual consistency, no new dependency.
const SyntaxHighlighter = lazy(() =>
  import("react-syntax-highlighter").then((m) => ({ default: m.Prism }))
);
import { atomDark } from "react-syntax-highlighter/dist/esm/styles/prism";

// Extension -> Prism language id. Inverted from DocumentEditor.jsx's
// EXT_BY_LANG (lang -> ext) rather than importing it, since that map is
// keyed the other direction and owned by another component.
const LANG_BY_EXT = {
  py: "python", js: "javascript", mjs: "javascript", cjs: "javascript",
  jsx: "jsx", ts: "typescript", tsx: "tsx",
  sh: "bash", bash: "bash", json: "json", html: "html", htm: "html",
  css: "css", yaml: "yaml", yml: "yaml", sql: "sql", rs: "rust",
  go: "go", java: "java", c: "c", h: "c", cpp: "cpp", cc: "cpp", hpp: "cpp",
  md: "markdown", markdown: "markdown", rb: "ruby", php: "php",
  kt: "kotlin", swift: "swift", toml: "toml", xml: "xml",
};

function langForPath(path) {
  const ext = (path.split(".").pop() || "").toLowerCase();
  return LANG_BY_EXT[ext] || "text";
}

// Syntax highlighting a huge file every keystroke gets janky fast (Prism
// re-tokenizes the whole string on each render). Above this size we just
// fall back to the plain textarea with no highlight overlay — still fully
// editable, just not colorized. Well under the 2MB per-file cap enforced
// by app/api/files.py.
const HIGHLIGHT_SIZE_CUTOFF = 200 * 1024; // 200KB

function FileTreeNode({ conversationId, entry, depth, onOpen }) {
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
    <div>
      <button className="file-tree-row" style={{ paddingLeft: `${depth * 14 + 8}px` }} onClick={toggle}>
        <Icon name={entry.is_dir ? (expanded ? "chevron-down" : "chevron-right") : "file-text"} size={13} />
        <span>{entry.name}</span>
      </button>
      {entry.is_dir && expanded && children != null && (
        <div>
          {children.map((c) => (
            <FileTreeNode key={c.path} conversationId={conversationId} entry={c} depth={depth + 1} onOpen={onOpen} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function CodeEditorPanel({ conversationId, workdir, onClose }) {
  const [rootEntries, setRootEntries] = useState([]);
  const [error, setError] = useState(null);
  const [tabs, setTabs] = useState([]); // { path, content, dirty, saving }
  const [activePath, setActivePath] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState(null);
  const [searching, setSearching] = useState(false);

  const runSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      const res = await api.searchLocalFiles(workdir, searchQuery.trim());
      setSearchResults(res.matches);
    } catch (err) {
      setError(err.message);
    } finally {
      setSearching(false);
    }
  };

  useEffect(() => {
    api
      .listWorkspaceFiles(conversationId, "")
      .then((res) => setRootEntries(res.entries))
      .catch((err) => setError(err.message));
  }, [conversationId]);

  const openFile = async (path) => {
    const existing = tabs.find((t) => t.path === path);
    if (existing) {
      setActivePath(path);
      return;
    }
    try {
      const res = await api.readWorkspaceFile(conversationId, path);
      setTabs((prev) => [...prev, { path, content: res.content, dirty: false, saving: false }]);
      setActivePath(path);
    } catch (err) {
      setError(err.message);
    }
  };

  const closeTab = (path) => {
    setTabs((prev) => prev.filter((t) => t.path !== path));
    if (activePath === path) {
      const remaining = tabs.filter((t) => t.path !== path);
      setActivePath(remaining.length ? remaining[remaining.length - 1].path : null);
    }
  };

  const editContent = (path, content) => {
    setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, content, dirty: true } : t)));
  };

  const saveTab = async (path) => {
    const tab = tabs.find((t) => t.path === path);
    if (!tab) return;
    setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, saving: true } : t)));
    try {
      await api.writeWorkspaceFile(conversationId, path, tab.content);
      setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, dirty: false, saving: false } : t)));
    } catch (err) {
      setError(err.message);
      setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, saving: false } : t)));
    }
  };

  const activeTab = tabs.find((t) => t.path === activePath);
  const highlightRef = useRef(null);
  const syncHighlightScroll = (e) => {
    if (highlightRef.current) {
      highlightRef.current.scrollTop = e.target.scrollTop;
      highlightRef.current.scrollLeft = e.target.scrollLeft;
    }
  };

  const [output, setOutput] = useState(null); // { label, text, loading }

  const runGitStatus = async () => {
    setOutput({ label: "git status", text: "", loading: true });
    try {
      const res = await api.gitStatus(conversationId);
      setOutput({ label: "git status", text: res.output, loading: false });
    } catch (err) {
      setOutput({ label: "git status", text: err.message, loading: false });
    }
  };

  const runGitDiff = async () => {
    setOutput({ label: "git diff", text: "", loading: true });
    try {
      const res = await api.gitDiff(conversationId, activeTab?.path || "");
      setOutput({ label: "git diff", text: res.output, loading: false });
    } catch (err) {
      setOutput({ label: "git diff", text: err.message, loading: false });
    }
  };

  const runCheckCommand = async () => {
    setOutput({ label: "run", text: "", loading: true });
    try {
      const res = await api.runChecks(conversationId);
      setOutput({ label: "run", text: res.output, loading: false });
    } catch (err) {
      setOutput({ label: "run", text: err.message, loading: false });
    }
  };

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal code-editor-modal"
        style={{ width: "min(1100px, calc(100vw - 3rem))", height: "min(720px, calc(100vh - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Code editor — ${workdir}`}
      >
        <div className="notes-header code-editor-header">
          <span className="code-editor-header-title" title={workdir}>Code editor — {workdir}</span>
          <div className="code-editor-toolbar">
            <button className="code-editor-toolbar-btn" onClick={runGitStatus} title="git status">
              <Icon name="grid" size={14} />
              <span>Status</span>
            </button>
            <button className="code-editor-toolbar-btn" onClick={runGitDiff} title="git diff (active file, or whole repo if none open)">
              <Icon name="layers" size={14} />
              <span>Diff</span>
            </button>
            <button className="code-editor-toolbar-btn" onClick={runCheckCommand} title="Run the configured check command (Settings -> Agent tools)">
              <Icon name="bolt" size={14} />
              <span>Run</span>
            </button>
            <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
              <Icon name="x" size={14} />
            </button>
          </div>
        </div>
        {error && <div className="settings-error">{error}</div>}
        <div className="code-editor-body">
          <div className="code-editor-tree">
            <div className="code-editor-search">
              <input
                className="settings-input"
                placeholder="Search files…"
                aria-label="Search files"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runSearch()}
              />
            </div>
            {searchResults != null ? (
              <div className="code-editor-search-results">
                <button className="text-btn" onClick={() => { setSearchResults(null); setSearchQuery(""); }} style={{ margin: "0 0 0.5rem 0.5rem" }}>
                  ← Back to tree
                </button>
                {searching && <div className="code-editor-empty">Searching…</div>}
                {!searching && searchResults.length === 0 && (
                  <div className="code-editor-empty" style={{ padding: "1rem" }}>No matches.</div>
                )}
                {searchResults.map((m) => (
                  <button
                    key={m.path}
                    className="file-tree-row"
                    style={{ flexDirection: "column", alignItems: "flex-start", paddingLeft: "0.5rem" }}
                    onClick={() => openFile(m.path.startsWith(workdir) ? m.path.slice(workdir.length + 1) : m.path)}
                    title={m.path}
                  >
                    <span style={{ fontWeight: 600 }}>{m.path.split("/").pop()}</span>
                    {m.snippet && (
                      <span style={{ fontSize: "0.7em", color: "var(--text-tertiary)", whiteSpace: "normal" }}>…{m.snippet}…</span>
                    )}
                  </button>
                ))}
              </div>
            ) : (
              rootEntries.map((e) => (
                <FileTreeNode key={e.path} conversationId={conversationId} entry={e} depth={0} onOpen={openFile} />
              ))
            )}
          </div>
          <div className="code-editor-main">
            {tabs.length > 0 && (
              <div className="code-editor-tabs">
                {tabs.map((t) => (
                  <div key={t.path} className={`code-editor-tab ${t.path === activePath ? "is-active" : ""}`}>
                    <button className="code-editor-tab-label" onClick={() => setActivePath(t.path)}>
                      {t.path.split("/").pop()}
                      {t.dirty ? " •" : ""}
                    </button>
                    <button className="code-editor-tab-close" onClick={() => closeTab(t.path)} title="Close" aria-label={`Close tab ${t.path.split("/").pop()}`}>
                      <Icon name="x" size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {activeTab ? (
              <>
                {(() => {
                  const lang = langForPath(activeTab.path);
                  const canHighlight =
                    lang !== "text" && activeTab.content.length <= HIGHLIGHT_SIZE_CUTOFF;
                  return (
                    <div className="code-editor-editor-wrap">
                      {canHighlight && (
                        <div className="code-editor-highlight-layer" ref={highlightRef} aria-hidden="true">
                          <Suspense fallback={null}>
                            <SyntaxHighlighter
                              style={atomDark}
                              language={lang}
                              PreTag="div"
                              customStyle={{
                                margin: 0,
                                background: "transparent",
                                padding: "var(--space-3)",
                                fontFamily: "var(--font-mono)",
                                fontSize: "var(--text-sm)",
                                lineHeight: 1.5,
                              }}
                              codeTagProps={{ style: { fontFamily: "var(--font-mono)" } }}
                            >
                              {activeTab.content.replace(/\n$/, "") + "\n"}
                            </SyntaxHighlighter>
                          </Suspense>
                        </div>
                      )}
                      <textarea
                        className={`code-editor-textarea ${canHighlight ? "code-editor-textarea-overlay" : ""}`}
                        value={activeTab.content}
                        onChange={(e) => editContent(activeTab.path, e.target.value)}
                        onScroll={canHighlight ? syncHighlightScroll : undefined}
                        spellCheck={false}
                        onKeyDown={(e) => {
                          if ((e.metaKey || e.ctrlKey) && e.key === "s") {
                            e.preventDefault();
                            saveTab(activeTab.path);
                          }
                        }}
                      />
                    </div>
                  );
                })()}
                <div className="code-editor-statusbar">
                  <span>{activeTab.path}</span>
                  <button
                    className="settings-btn-primary"
                    disabled={!activeTab.dirty || activeTab.saving}
                    onClick={() => saveTab(activeTab.path)}
                  >
                    {activeTab.saving ? "Saving…" : "Save (⌘S)"}
                  </button>
                </div>
              </>
            ) : (
              <div className="code-editor-empty">Pick a file from the tree to open it.</div>
            )}
          </div>
        </div>
        {output && (
          <div className="code-editor-output">
            <div className="code-editor-output-header">
              <span>{output.label}</span>
              <button className="icon-btn" onClick={() => setOutput(null)} title="Close" aria-label="Close output">
                <Icon name="x" size={12} />
              </button>
            </div>
            <pre className="code-editor-output-body">{output.loading ? "Running…" : output.text || "(no output)"}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
