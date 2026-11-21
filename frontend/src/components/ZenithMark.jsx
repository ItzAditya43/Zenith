/**
 * The Zenith logo, animated: the ring draws itself, the horizon extends,
 * and the sun rises from the horizon to its zenith, then glows softly.
 * Colours come from the theme; motion is skipped under reduced motion.
 */
export default function ZenithMark({ size = 72, className = "" }) {
  return (
    <svg
      className={`zenith-mark ${className}`}
      width={size}
      height={size}
      viewBox="0 0 1024 1024"
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="zm-glow">
          <stop offset="0" stopColor="var(--signal-general)" stopOpacity="0.55" />
          <stop offset="1" stopColor="var(--signal-general)" stopOpacity="0" />
        </radialGradient>
        <clipPath id="zm-above">
          <rect x="0" y="0" width="1024" height="672" />
        </clipPath>
      </defs>
      <circle className="zm-ring" cx="512" cy="560" r="300" pathLength="1" />
      <line className="zm-horizon" x1="150" y1="672" x2="874" y2="672" pathLength="1" />
      <g clipPath="url(#zm-above)">
        <g className="zm-sun">
          <circle className="zm-halo" cx="512" cy="260" r="230" fill="url(#zm-glow)" />
          <circle className="zm-gap" cx="512" cy="260" r="128" />
          <circle className="zm-dot" cx="512" cy="260" r="92" />
        </g>
      </g>
    </svg>
  );
}
