import { useEffect, useState } from "react";
import Icon from "./Icon.jsx";

/**
 * Select any text inside a message and a tiny toolbar appears above it —
 * "Explain" or "Ask about this" seed the composer with the exact quote
 * instead of forcing a copy/paste round trip.
 */
export default function SelectionPopover({ containerRef, onExplain, onAsk }) {
  const [state, setState] = useState(null); // { text, top, left }

  useEffect(() => {
    const handle = () => {
      const sel = window.getSelection();
      const text = sel?.toString().trim();
      if (!text || sel.rangeCount === 0) {
        setState(null);
        return;
      }
      const container = containerRef.current;
      const anchorNode = sel.anchorNode;
      if (!container || !anchorNode || !container.contains(anchorNode)) {
        setState(null);
        return;
      }
      const range = sel.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) {
        setState(null);
        return;
      }
      setState({
        text,
        top: rect.top - containerRect.top - 36,
        left: rect.left - containerRect.left + rect.width / 2,
      });
    };
    document.addEventListener("selectionchange", handle);
    return () => document.removeEventListener("selectionchange", handle);
  }, [containerRef]);

  if (!state) return null;

  return (
    <div className="selection-popover" style={{ top: state.top, left: state.left }}>
      <button
        onClick={() => {
          onExplain(state.text);
          window.getSelection()?.removeAllRanges();
          setState(null);
        }}
      >
        <Icon name="info" size={12} /> Explain
      </button>
      <button
        onClick={() => {
          onAsk(state.text);
          window.getSelection()?.removeAllRanges();
          setState(null);
        }}
      >
        <Icon name="pencil" size={12} /> Ask about this
      </button>
    </div>
  );
}
