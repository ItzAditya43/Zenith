import Icon from "./Icon.jsx";

function wordDiff(a, b) {
  const wa = a.split(/(\s+)/);
  const wb = b.split(/(\s+)/);
  const n = wa.length, m = wb.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = wa[i] === wb[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const outA = [], outB = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (wa[i] === wb[j]) {
      outA.push({ text: wa[i], type: "same" });
      outB.push({ text: wb[j], type: "same" });
      i++; j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      outA.push({ text: wa[i], type: "removed" });
      i++;
    } else {
      outB.push({ text: wb[j], type: "added" });
      j++;
    }
  }
  while (i < n) outA.push({ text: wa[i++], type: "removed" });
  while (j < m) outB.push({ text: wb[j++], type: "added" });
  return { outA, outB };
}

/**
 * Regenerating a message keeps the old version as a sibling branch instead
 * of throwing it away — this makes that fact visible: pick any two versions
 * and see exactly which words changed, side by side, instead of blindly
 * flipping between "1/3" and "2/3".
 */
export default function RegenerationDiff({ siblings, initialLeftId, initialRightId, onClose }) {
  const left = siblings.find((s) => s.id === initialLeftId) || siblings[0];
  const right = siblings.find((s) => s.id === initialRightId) || siblings[siblings.length - 1];
  const { outA, outB } = wordDiff(left.content || "", right.content || "");

  return (
    <div className="regen-diff-overlay" onClick={onClose}>
      <div
        className="regen-diff-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="regen-diff-title"
      >
        <div className="regen-diff-header">
          <span id="regen-diff-title">Compare versions</span>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>
        <div className="regen-diff-panes">
          <div className="regen-diff-pane">
            <div className="regen-diff-pane-label">Version {siblings.indexOf(left) + 1}</div>
            <div className="regen-diff-text">
              {outA.map((tok, i) => (
                <span key={i} className={tok.type === "removed" ? "diff-removed" : ""}>
                  {tok.text}
                </span>
              ))}
            </div>
          </div>
          <div className="regen-diff-pane">
            <div className="regen-diff-pane-label">Version {siblings.indexOf(right) + 1}</div>
            <div className="regen-diff-text">
              {outB.map((tok, i) => (
                <span key={i} className={tok.type === "added" ? "diff-added" : ""}>
                  {tok.text}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
