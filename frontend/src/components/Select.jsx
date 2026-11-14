import { Children, Fragment, isValidElement, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon.jsx";

/** Flatten <option> children (through fragments, arrays and conditionals)
 * into [{ value, label, disabled }]. */
function readOptions(children) {
  const out = [];
  const walk = (nodes) =>
    Children.forEach(nodes, (child) => {
      if (!isValidElement(child)) return;
      if (child.type === Fragment) return walk(child.props.children);
      if (child.type === "option") {
        const label = Children.toArray(child.props.children).join("");
        out.push({
          value: child.props.value !== undefined ? String(child.props.value) : label,
          label,
          disabled: !!child.props.disabled,
        });
      }
    });
  walk(children);
  return out;
}

const SEARCH_THRESHOLD = 9;

/**
 * Themed drop-in for <select>. Same props and children as the native one:
 *
 *   <Select value={v} onChange={(e) => set(e.target.value)} aria-label="…">
 *     <option value="a">A</option>
 *   </Select>
 *
 * The native control is drawn by the OS (GTK inside the Linux desktop app),
 * so its open list ignores the app's theme. This one renders the list in a
 * portal so it isn't clipped by scrolling panels, and adds a filter box for
 * long lists. onChange receives { target: { value } } with a string value,
 * exactly like a native change event.
 */
export default function Select({
  value, onChange, children, disabled = false, className = "", style, id, title,
  "aria-label": ariaLabel, ...rest
}) {
  const options = useMemo(() => readOptions(children), [children]);
  const current = options.find((o) => o.value === String(value ?? "")) || null;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [query, setQuery] = useState("");
  const [pos, setPos] = useState(null);
  const btn = useRef(null);
  const list = useRef(null);
  const search = useRef(null);
  const typed = useRef({ text: "", at: 0 });
  const listId = useId();

  const filtered = query.trim()
    ? options.filter((o) => o.label.toLowerCase().includes(query.trim().toLowerCase()))
    : options;

  const place = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const below = window.innerHeight - r.bottom;
    const want = Math.min(320, 44 + options.length * 34);
    const up = below < Math.min(want, 220) && r.top > below;
    setPos({
      left: Math.max(8, Math.min(r.left, window.innerWidth - Math.max(r.width, 200) - 8)),
      width: Math.max(r.width, 200),
      top: up ? undefined : r.bottom + 4,
      bottom: up ? window.innerHeight - r.top + 4 : undefined,
      maxHeight: Math.max(160, (up ? r.top : below) - 16),
    });
  };

  const openList = () => {
    if (disabled) return;
    place();
    setQuery("");
    setActive(Math.max(0, options.findIndex((o) => o.value === current?.value)));
    setOpen(true);
  };
  const closeList = (refocus = true) => {
    setOpen(false);
    if (refocus) btn.current?.focus();
  };
  const choose = (o) => {
    if (!o || o.disabled) return;
    closeList();
    if (o.value !== current?.value) onChange?.({ target: { value: o.value }, currentTarget: { value: o.value } });
  };

  useLayoutEffect(() => {
    if (!open) return;
    if (options.length >= SEARCH_THRESHOLD) search.current?.focus();
    else list.current?.focus();
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (btn.current?.contains(e.target) || list.current?.parentElement?.contains(e.target)) return;
      closeList(false);
    };
    const onMove = (e) => {
      if (list.current?.parentElement?.contains(e.target)) return;
      place();
    };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
  });

  useEffect(() => {
    if (!open) return;
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const move = (delta) => {
    if (!filtered.length) return;
    let i = active;
    for (let n = 0; n < filtered.length; n++) {
      i = (i + delta + filtered.length) % filtered.length;
      if (!filtered[i].disabled) break;
    }
    setActive(i);
  };

  const onListKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(filtered.length - 1); }
    else if (e.key === "Enter") { e.preventDefault(); choose(filtered[active]); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeList(); }
    else if (e.key === "Tab") { closeList(false); }
    else if (e.key.length === 1 && e.target === list.current) {
      // Type to jump, as in a native select.
      const now = Date.now();
      typed.current = { text: (now - typed.current.at < 700 ? typed.current.text : "") + e.key.toLowerCase(), at: now };
      const i = filtered.findIndex((o) => o.label.toLowerCase().startsWith(typed.current.text));
      if (i >= 0) setActive(i);
    }
  };

  const onButtonKey = (e) => {
    if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
      e.preventDefault();
      openList();
    }
  };

  return (
    <>
      <button
        type="button"
        ref={btn}
        id={id}
        className={`ui-select ${className} ${open ? "is-open" : ""}`}
        style={style}
        title={title}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={ariaLabel}
        onClick={() => (open ? closeList() : openList())}
        onKeyDown={onButtonKey}
        {...rest}
      >
        <span className="ui-select-value">{current ? current.label : <span className="ui-select-placeholder">Choose…</span>}</span>
        <Icon name="chevron-down" size={13} />
      </button>
      {open && pos && createPortal(
        <div
          className="ui-select-pop"
          style={{ left: pos.left, width: pos.width, top: pos.top, bottom: pos.bottom, maxHeight: Math.min(320, pos.maxHeight) }}
        >
          {options.length >= SEARCH_THRESHOLD && (
            <input
              ref={search}
              className="ui-select-search"
              placeholder="Filter…"
              value={query}
              onChange={(e) => { setQuery(e.target.value); setActive(0); }}
              onKeyDown={onListKey}
              aria-label="Filter options"
              aria-controls={listId}
            />
          )}
          <ul
            ref={list}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            aria-activedescendant={filtered[active] ? `${listId}-${active}` : undefined}
            className="ui-select-list"
            onKeyDown={onListKey}
          >
            {filtered.map((o, i) => (
              <li
                key={`${o.value}-${i}`}
                id={`${listId}-${i}`}
                data-index={i}
                role="option"
                aria-selected={o.value === current?.value}
                aria-disabled={o.disabled || undefined}
                className={`ui-select-option ${i === active ? "is-active" : ""} ${o.value === current?.value ? "is-selected" : ""} ${o.disabled ? "is-disabled" : ""}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(o)}
              >
                <span className="ui-select-option-label">{o.label}</span>
                {o.value === current?.value && <Icon name="check" size={13} />}
              </li>
            ))}
            {!filtered.length && <li className="ui-select-empty">No matches</li>}
          </ul>
        </div>,
        document.body,
      )}
    </>
  );
}
