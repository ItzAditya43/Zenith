import { useState, useEffect, useCallback } from "react";
import { api } from "../lib/api";
import { useEscapeToClose } from "../hooks/useEscapeToClose";
import { pickNativeDirectory, isDesktopApp } from "../lib/directoryPicker";
import Icon from "./Icon.jsx";

/**
 * Structured Working Directory selector modal.
 *
 * Replaces the primitive `window.prompt` with:
 *   1. Native OS directory picker dialog (GTK/Finder/Explorer via Tauri)
 *   2. Interactive directory browser with breadcrumb navigation
 *   3. Quick location shortcuts (Home, Desktop, Documents, Downloads, etc.)
 *   4. Recent working directories from other conversations and projects
 *   5. Manual text path entry with clear validation and unbinding
 */
export default function WorkdirModal({
  currentWorkdir = "",
  recentWorkdirs = [],
  onClose,
  onSave,
}) {
  useEscapeToClose(onClose);

  const [pathInput, setPathInput] = useState(currentWorkdir || "");
  const [browserState, setBrowserState] = useState({
    current: "",
    parent: null,
    directories: [],
    quickPaths: [],
    loading: true,
    error: null,
  });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const isDesktop = isDesktopApp();

  // Load filesystem directories from backend for structured browsing
  const loadDirectory = useCallback(async (dirPath = "") => {
    setBrowserState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await api.listDirectories(dirPath);
      setBrowserState({
        current: data.current,
        parent: data.parent,
        directories: data.directories || [],
        quickPaths: data.quick_paths || [],
        loading: false,
        error: null,
      });
    } catch (err) {
      setBrowserState((s) => ({
        ...s,
        loading: false,
        error: err?.message || "Could not read directory",
      }));
    }
  }, []);

  // Initial load
  useEffect(() => {
    let active = true;
    api
      .listDirectories(currentWorkdir || "")
      .then((data) => {
        if (!active) return;
        setBrowserState({
          current: data.current,
          parent: data.parent,
          directories: data.directories || [],
          quickPaths: data.quick_paths || [],
          loading: false,
          error: null,
        });
      })
      .catch((err) => {
        if (!active) return;
        setBrowserState((s) => ({
          ...s,
          loading: false,
          error: err?.message || "Could not read directory",
        }));
      });
    return () => {
      active = false;
    };
  }, [currentWorkdir]);

  // Native folder picker button handler
  const handleNativeBrowse = async () => {
    try {
      const selected = await pickNativeDirectory({
        defaultPath: pathInput.trim() || currentWorkdir || undefined,
        title: "Select Working Directory for Agent Mode",
      });
      if (selected) {
        setPathInput(selected);
        loadDirectory(selected);
      }
    } catch (err) {
      console.warn("Browse failed:", err);
    }
  };

  const handleSelectSubdir = (dirPath) => {
    setPathInput(dirPath);
    loadDirectory(dirPath);
  };

  const handleSelectQuick = (p) => {
    setPathInput(p);
    loadDirectory(p);
  };

  const handleSave = async (pathToSave = pathInput) => {
    setSaving(true);
    setSaveError(null);
    try {
      const trimmed = (pathToSave || "").trim();
      await onSave(trimmed ? trimmed : null);
      onClose();
    } catch (err) {
      setSaveError(err?.message || "Failed to set working directory");
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    await handleSave("");
  };

  // Build breadcrumb segments from browserState.current
  const currentPath = browserState.current || pathInput;
  const pathParts = currentPath
    ? currentPath.split("/").filter(Boolean)
    : [];

  return (
    <div className="notes-overlay" onClick={onClose}>
      <div
        className="notes-modal workdir-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Set Working Directory"
      >
        <div className="notes-header">
          <h2>
            <Icon name="folder" size={16} /> Set Working Directory
          </h2>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div className="workdir-body">
          <p className="setting-hint workdir-hint">
            Agent mode's bash cwd and relative file paths resolve against this directory.
            Set it once to work seamlessly inside your project repository.
          </p>

          {currentWorkdir ? (
            <div className="workdir-current-bar">
              <span className="workdir-current-label">Currently bound:</span>
              <code className="workdir-current-path" title={currentWorkdir}>
                {currentWorkdir}
              </code>
              <button
                type="button"
                className="text-btn workdir-clear-btn"
                onClick={handleClear}
                disabled={saving}
                title="Unbind working directory from this conversation"
              >
                Clear
              </button>
            </div>
          ) : (
            <div className="workdir-current-bar is-unbound">
              <span className="workdir-current-label">No directory bound</span>
              <span className="setting-hint">— bash runs in default backend environment</span>
            </div>
          )}

          {/* Path input with native browse button */}
          <div className="workdir-input-row">
            <div className="workdir-input-wrap">
              <Icon name="folder" size={14} className="workdir-input-icon" />
              <input
                className="settings-input workdir-input"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    if (pathInput.trim() !== browserState.current) {
                      loadDirectory(pathInput.trim());
                    } else {
                      handleSave();
                    }
                  }
                }}
                placeholder="/path/to/project"
                aria-label="Working directory path"
                autoFocus
              />
            </div>
            <button
              type="button"
              className="settings-btn workdir-browse-btn"
              onClick={handleNativeBrowse}
              title={
                isDesktop
                  ? "Open system folder chooser"
                  : "Browse directory"
              }
            >
              <Icon name="folder-open" size={14} /> Browse…
            </button>
          </div>

          {/* Quick shortcuts / bookmarks */}
          {browserState.quickPaths.length > 0 && (
            <div className="workdir-shortcuts-section">
              <span className="workdir-section-label">Quick locations:</span>
              <div className="workdir-chips">
                {browserState.quickPaths.map((qp) => (
                  <button
                    key={qp.path}
                    type="button"
                    className={`workdir-chip ${pathInput === qp.path ? "is-active" : ""}`}
                    onClick={() => handleSelectQuick(qp.path)}
                    title={qp.path}
                  >
                    {qp.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Recent locations if available */}
          {recentWorkdirs.length > 0 && (
            <div className="workdir-shortcuts-section">
              <span className="workdir-section-label">Recent projects:</span>
              <div className="workdir-chips">
                {recentWorkdirs.slice(0, 5).map((r) => (
                  <button
                    key={r}
                    type="button"
                    className={`workdir-chip recent ${pathInput === r ? "is-active" : ""}`}
                    onClick={() => handleSelectQuick(r)}
                    title={r}
                  >
                    {r.split("/").pop() || r}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Interactive directory browser */}
          <div className="workdir-browser-card">
            <div className="workdir-browser-header">
              <div className="workdir-breadcrumbs">
                <button
                  type="button"
                  className="workdir-breadcrumb-btn root"
                  onClick={() => handleSelectQuick("/")}
                  title="Root directory (/)"
                >
                  /
                </button>
                {pathParts.map((part, idx) => {
                  const subPath = "/" + pathParts.slice(0, idx + 1).join("/");
                  const isLast = idx === pathParts.length - 1;
                  return (
                    <span key={subPath} className="workdir-breadcrumb-segment">
                      <span className="workdir-breadcrumb-sep">/</span>
                      <button
                        type="button"
                        className={`workdir-breadcrumb-btn ${isLast ? "is-current" : ""}`}
                        onClick={() => handleSelectQuick(subPath)}
                        title={subPath}
                      >
                        {part}
                      </button>
                    </span>
                  );
                })}
              </div>
              {browserState.parent && (
                <button
                  type="button"
                  className="workdir-up-btn"
                  onClick={() => handleSelectQuick(browserState.parent)}
                  title={`Up to ${browserState.parent}`}
                >
                  <Icon name="arrow-up" size={12} /> Up
                </button>
              )}
            </div>

            <div className="workdir-folder-list">
              {browserState.loading && (
                <div className="workdir-browser-loading">Loading folders…</div>
              )}
              {browserState.error && (
                <div className="workdir-browser-error">{browserState.error}</div>
              )}
              {!browserState.loading &&
                !browserState.error &&
                browserState.directories.length === 0 && (
                  <div className="workdir-browser-empty">No subdirectories found</div>
                )}
              {!browserState.loading &&
                browserState.directories.map((d) => (
                  <button
                    key={d.path}
                    type="button"
                    className={`workdir-folder-row ${pathInput === d.path ? "is-selected" : ""}`}
                    onClick={() => handleSelectSubdir(d.path)}
                    title={d.path}
                  >
                    <Icon name="folder" size={14} className="workdir-folder-row-icon" />
                    <span className="workdir-folder-row-name">{d.name}</span>
                  </button>
                ))}
            </div>
          </div>

          {saveError && <p className="settings-error workdir-error">{saveError}</p>}
        </div>

        <div className="workdir-footer">
          <button type="button" className="settings-btn" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            type="button"
            className="settings-btn-primary"
            onClick={() => handleSave()}
            disabled={saving}
          >
            {saving ? "Saving…" : pathInput ? "Set Working Directory" : "Save (Unbound)"}
          </button>
        </div>
      </div>
    </div>
  );
}
