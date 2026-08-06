import { useEffect, useState } from "react";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";

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

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal code-editor-modal"
        style={{ width: "min(1100px, calc(100vw - 3rem))", height: "min(720px, calc(100vh - 3rem))" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="notes-header">
          <span>Code editor — {workdir}</span>
          <button className="icon-btn" onClick={onClose} title="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        {error && <div className="settings-error">{error}</div>}
        <div className="code-editor-body">
          <div className="code-editor-tree">
            {rootEntries.map((e) => (
              <FileTreeNode key={e.path} conversationId={conversationId} entry={e} depth={0} onOpen={openFile} />
            ))}
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
                    <button className="code-editor-tab-close" onClick={() => closeTab(t.path)} title="Close">
                      <Icon name="x" size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {activeTab ? (
              <>
                <textarea
                  className="code-editor-textarea"
                  value={activeTab.content}
                  onChange={(e) => editContent(activeTab.path, e.target.value)}
                  spellCheck={false}
                  onKeyDown={(e) => {
                    if ((e.metaKey || e.ctrlKey) && e.key === "s") {
                      e.preventDefault();
                      saveTab(activeTab.path);
                    }
                  }}
                />
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
      </div>
    </div>
  );
}
