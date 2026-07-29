import { useEffect, useMemo, useRef, useState } from "react";
import Icon from "./Icon.jsx";

/**
 * Cmd/Ctrl+K power-user palette: jump to a conversation, run an action, switch a
 * persona, or open a specific Settings section — all from one input
 * instead of hunting through menus. Filters everything client-side
 * against a flat list of "commands" built fresh each open, so it always
 * reflects current conversations/personas without extra plumbing.
 */
export default function CommandPalette({ open, onClose, commands }) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q
      ? commands.filter(
          (c) => c.label.toLowerCase().includes(q) || c.group.toLowerCase().includes(q)
        )
      : commands;
    return list.slice(0, 50);
  }, [query, commands]);

  useEffect(() => setActiveIndex(0), [query]);

  if (!open) return null;

  const run = (cmd) => {
    onClose();
    cmd.action();
  };

  const handleKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[activeIndex]) run(filtered[activeIndex]);
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  let lastGroup = null;

  return (
    <div className="cmdk-overlay" onClick={onClose}>
      <div className="cmdk-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command palette">
        <div className="cmdk-input-row">
          <span className="cmdk-input-icon" aria-hidden="true">
            <Icon name="command" size={15} />
          </span>
          <input
            ref={inputRef}
            className="cmdk-input"
            placeholder="Jump to a conversation, switch persona, open a setting…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <span className="cmdk-hint">esc</span>
        </div>
        <div className="cmdk-list" role="listbox">
          {filtered.length === 0 && <p className="cmdk-empty">No matches.</p>}
          {filtered.map((cmd, i) => {
            const showGroup = cmd.group !== lastGroup;
            lastGroup = cmd.group;
            return (
              <div key={cmd.id}>
                {showGroup && <p className="cmdk-group-label">{cmd.group}</p>}
                <button
                  className={`cmdk-item ${i === activeIndex ? "is-active" : ""}`}
                  onMouseEnter={() => setActiveIndex(i)}
                  onClick={() => run(cmd)}
                >
                  <span className="cmdk-item-icon" aria-hidden="true">
                    <Icon name={cmd.icon || "chevron-right"} size={14} />
                  </span>
                  <span className="cmdk-item-label">{cmd.label}</span>
                  {cmd.hint && <span className="cmdk-item-hint">{cmd.hint}</span>}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
