import { useEffect, useRef } from "react";
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { HighlightStyle, syntaxHighlighting, bracketMatching, indentOnInput, foldGutter, LanguageDescription } from "@codemirror/language";
import { languages } from "@codemirror/language-data";
import { tags as t } from "@lezer/highlight";

// Colours come from the app's theme tokens, so the editor follows whichever
// of Zenith's themes is active instead of bringing its own look.
const theme = EditorView.theme(
  {
    "&": { height: "100%", fontSize: "var(--text-sm)", backgroundColor: "var(--bg-inset)", color: "var(--text-primary)" },
    ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.55" },
    ".cm-content": { caretColor: "var(--signal-general)", padding: "var(--space-2) 0" },
    ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--signal-general)" },
    "&.cm-focused": { outline: "none" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
      backgroundColor: "var(--signal-general-dim) !important",
    },
    ".cm-gutters": {
      backgroundColor: "var(--bg-inset)",
      color: "var(--text-tertiary)",
      border: "none",
      borderRight: "1px solid var(--border-hairline)",
    },
    ".cm-activeLine": { backgroundColor: "rgba(148, 163, 184, 0.04)" },
    ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--text-secondary)" },
    ".cm-matchingBracket": { backgroundColor: "var(--signal-general-dim)", outline: "none" },
    ".cm-searchMatch": { backgroundColor: "var(--signal-voice-dim)" },
    ".cm-panels": { backgroundColor: "var(--bg-panel)", color: "var(--text-primary)", borderColor: "var(--border-hairline)" },
    ".cm-panels input, .cm-panels button": { fontFamily: "var(--font-body)", fontSize: "var(--text-xs)" },
    ".cm-foldPlaceholder": { backgroundColor: "var(--bg-panel-raised)", border: "none", color: "var(--text-secondary)" },
  },
  { dark: true },
);

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.moduleKeyword, t.operatorKeyword], color: "var(--signal-reasoning)" },
  { tag: [t.string, t.special(t.string), t.regexp], color: "var(--signal-general)" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "var(--signal-voice)" },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: "var(--signal-code)" },
  { tag: [t.definition(t.variableName), t.className, t.typeName], color: "var(--signal-vision)" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--text-tertiary)", fontStyle: "italic" },
  { tag: [t.propertyName, t.attributeName], color: "var(--text-primary)" },
  { tag: [t.tagName], color: "var(--signal-code)" },
  { tag: [t.heading], color: "var(--text-primary)", fontWeight: "600" },
  { tag: [t.link, t.url], color: "var(--signal-reasoning)", textDecoration: "underline" },
  { tag: t.invalid, color: "var(--signal-danger)" },
]);

/**
 * CodeMirror 6 editor for one open file.
 *
 * Uncontrolled after mount: `value` seeds the document, edits flow out
 * through onChange. Switching files remounts (keyed by path in the parent),
 * so each tab keeps clean undo history.
 */
export default function CodeEditor({ path, value, onChange, onSave, onSelectionChange, apiRef }) {
  const host = useRef(null);
  const view = useRef(null);
  const handlers = useRef({ onChange, onSave, onSelectionChange });
  handlers.current = { onChange, onSave, onSelectionChange };

  useEffect(() => {
    const language = new Compartment();
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        foldGutter(),
        history(),
        drawSelection(),
        indentOnInput(),
        bracketMatching(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        syntaxHighlighting(highlight),
        theme,
        language.of([]),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => { handlers.current.onSave?.(); return true; } },
          indentWithTab,
          ...defaultKeymap,
          ...historyKeymap,
          ...searchKeymap,
        ]),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) handlers.current.onChange?.(u.state.doc.toString());
          if (u.selectionSet || u.docChanged) {
            const sel = u.state.selection.main;
            if (sel.empty) {
              handlers.current.onSelectionChange?.(null);
            } else {
              const doc = u.state.doc;
              handlers.current.onSelectionChange?.({
                text: doc.sliceString(sel.from, sel.to),
                fromLine: doc.lineAt(sel.from).number,
                toLine: doc.lineAt(sel.to).number,
              });
            }
          }
        }),
      ],
    });
    const v = new EditorView({ state, parent: host.current });
    view.current = v;
    if (apiRef) {
      apiRef.current = {
        // Replace whole lines from..to (1-based, inclusive) as one undoable change.
        replaceLines(from, to, text) {
          const doc = v.state.doc;
          if (from < 1 || to > doc.lines || from > to) return false;
          const start = doc.line(from).from;
          const end = doc.line(to).to;
          v.dispatch({ changes: { from: start, to: end, insert: text }, selection: { anchor: start, head: start + text.length }, scrollIntoView: true });
          v.focus();
          return true;
        },
        text: () => v.state.doc.toString(),
      };
    }

    // Load the grammar for this file type on demand (each is its own chunk).
    let cancelled = false;
    const desc = LanguageDescription.matchFilename(languages, path.split("/").pop() || path);
    if (desc) {
      desc.load().then((support) => {
        if (!cancelled) v.dispatch({ effects: language.reconfigure(support) });
      }).catch(() => {});
    }
    return () => {
      cancelled = true;
      v.destroy();
      view.current = null;
      if (apiRef) apiRef.current = null;
    };
    // Mount once per file; `value` only seeds the document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  return <div className="ws-editor" ref={host} />;
}
