/** Unified diff with coloured lines. With `onToggleHunk`, each hunk gets a
 * keep/skip toggle (used by agent edit approval). Shared by the chat's
 * tool cards and the workspace Changes tab so diffs look the same in both. */
export default function DiffView({ diff, rejected, onToggleHunk }) {
  const lines = diff.split("\n");
  const hunkOf = [];
  for (let i = 0, n = -1; i < lines.length; i++) {
    if (lines[i].startsWith("@@")) n += 1;
    hunkOf.push(n);
  }
  return (
    <pre className="tool-call-diff">
      {lines.map((line, i) => {
        const h = hunkOf[i];
        const skipped = rejected?.has(h);
        const kind = line.startsWith("+") && !line.startsWith("+++")
          ? "add"
          : line.startsWith("-") && !line.startsWith("---")
          ? "del"
          : line.startsWith("@@")
          ? "hunk"
          : "ctx";
        return (
          <div key={i} className={`diff-line diff-line-${kind}${skipped ? " diff-line-skipped" : ""}`}>
            {line || " "}
            {kind === "hunk" && onToggleHunk && (
              <button
                type="button"
                className="diff-hunk-toggle"
                onClick={() => onToggleHunk(h)}
                aria-pressed={!skipped}
                aria-label={`${skipped ? "Keep" : "Skip"} change ${h + 1}`}
              >
                {skipped ? "skipped" : "keep"}
              </button>
            )}
          </div>
        );
      })}
    </pre>
  );
}
