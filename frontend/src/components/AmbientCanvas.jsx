import { useEffect, useRef } from "react";
import { runAnimation } from "../lib/ambientAnimations";

/** Full-bleed canvas behind the chat surface. Mounts/tears down the
 * animation loop whenever the selected animation (or theme, which can
 * invalidate the current pick) changes. */
export default function AmbientCanvas({ animationId }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || animationId === "none") return;
    const stop = runAnimation(canvasRef.current, animationId);
    return stop;
  }, [animationId]);

  if (animationId === "none") return null;
  return <canvas ref={canvasRef} className="ambient-canvas" aria-hidden="true" />;
}
