import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * Signature visual: a sparse field of drifting nodes with faint connective
 * lines between neighbors — a "local nervous system" quietly idling behind
 * the glass panels. It reacts to conversation state instead of just looping:
 *
 *   status: "idle"      -> slow drift, dim
 *   status: "thinking"  -> nodes brighten and pulse toward the signal color
 *   status: "speaking"  -> gentle wave ripples outward (voice output)
 *
 * `role` picks which capability color the pulse takes (teal/violet/coral/amber),
 * so the background itself confirms which model just answered.
 */
const ROLE_COLORS = {
  general: 0x4dd9c0,
  small_fast: 0x4dd9c0,
  vision: 0x8b7fe8,
  code: 0xef8b6f,
  reasoning: 0x6fb1ef,
  voice: 0xe8b23d,
};

const NODE_COUNT = 90;

export default function AmbientField({ status = "idle", role = "general" }) {
  const mountRef = useRef(null);
  const stateRef = useRef({ status, role });

  useEffect(() => {
    stateRef.current = { status, role };
  }, [status, role]);

  useEffect(() => {
    const mount = mountRef.current;
    const width = mount.clientWidth;
    const height = mount.clientHeight;

    // Tier 6 #12 — respect reduced-motion preference.
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 100);
    camera.position.z = 18;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);
    // Tier 6 #11 — fade in on first paint instead of a blank void.
    renderer.domElement.style.opacity = "0";
    renderer.domElement.style.transition = "opacity 0.8s ease";
    requestAnimationFrame(() => {
      renderer.domElement.style.opacity = "1";
    });

    // --- nodes ---
    const positions = new Float32Array(NODE_COUNT * 3);
    const basePositions = new Float32Array(NODE_COUNT * 3);
    const speeds = new Float32Array(NODE_COUNT);
    for (let i = 0; i < NODE_COUNT; i++) {
      const x = (Math.random() - 0.5) * 34;
      const y = (Math.random() - 0.5) * 20;
      const z = (Math.random() - 0.5) * 14;
      positions.set([x, y, z], i * 3);
      basePositions.set([x, y, z], i * 3);
      speeds[i] = 0.15 + Math.random() * 0.35;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

    const material = new THREE.PointsMaterial({
      color: ROLE_COLORS.general,
      size: 0.16,
      transparent: true,
      opacity: 0.55,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const points = new THREE.Points(geometry, material);
    scene.add(points);

    // --- connective lines between nearby nodes (computed once, static topology) ---
    const linePositions = [];
    const maxDist = 6.5;
    for (let i = 0; i < NODE_COUNT; i++) {
      for (let j = i + 1; j < NODE_COUNT; j++) {
        const dx = basePositions[i * 3] - basePositions[j * 3];
        const dy = basePositions[i * 3 + 1] - basePositions[j * 3 + 1];
        const dz = basePositions[i * 3 + 2] - basePositions[j * 3 + 2];
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < maxDist) {
          linePositions.push(
            basePositions[i * 3], basePositions[i * 3 + 1], basePositions[i * 3 + 2],
            basePositions[j * 3], basePositions[j * 3 + 1], basePositions[j * 3 + 2]
          );
        }
      }
    }
    const lineGeometry = new THREE.BufferGeometry();
    lineGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(new Float32Array(linePositions), 3)
    );
    const lineMaterial = new THREE.LineBasicMaterial({
      color: ROLE_COLORS.general,
      transparent: true,
      opacity: 0.06,
      blending: THREE.AdditiveBlending,
    });
    const lines = new THREE.LineSegments(lineGeometry, lineMaterial);
    scene.add(lines);

    let raf;
    let clock = new THREE.Clock();
    let currentColor = new THREE.Color(ROLE_COLORS.general);
    let targetColor = new THREE.Color(ROLE_COLORS.general);

    const animate = () => {
      const t = clock.getElapsedTime();
      const { status: liveStatus, role: liveRole } = stateRef.current;
      targetColor.set(ROLE_COLORS[liveRole] ?? ROLE_COLORS.general);
      currentColor.lerp(targetColor, 0.04);
      material.color.copy(currentColor);
      lineMaterial.color.copy(currentColor);

      const activity = liveStatus === "thinking" ? 1 : liveStatus === "speaking" ? 0.7 : 0.25;
      const pulse = 0.45 + activity * (0.3 + 0.25 * Math.sin(t * (liveStatus === "thinking" ? 4 : 1.4)));
      material.opacity = pulse;
      lineMaterial.opacity = 0.04 + activity * 0.05;
      material.size = 0.16 + activity * 0.05;

      if (!reduceMotion) {
        const posAttr = geometry.attributes.position;
        for (let i = 0; i < NODE_COUNT; i++) {
          const idx = i * 3;
          const speed = speeds[i] * (0.4 + activity * 0.8);
          posAttr.array[idx] = basePositions[idx] + Math.sin(t * speed + i) * 0.6;
          posAttr.array[idx + 1] = basePositions[idx + 1] + Math.cos(t * speed * 0.8 + i) * 0.6;
          posAttr.array[idx + 2] = basePositions[idx + 2] + Math.sin(t * speed * 0.6 + i * 2) * 0.4;
        }
        posAttr.needsUpdate = true;

        points.rotation.y = t * 0.015;
        lines.rotation.y = t * 0.015;
        points.rotation.x = Math.sin(t * 0.05) * 0.05;
        lines.rotation.x = points.rotation.x;
      }

      renderer.render(scene, camera);
      raf = requestAnimationFrame(animate);
    };
    animate();

    const onResize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      geometry.dispose();
      material.dispose();
      lineGeometry.dispose();
      lineMaterial.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div
      ref={mountRef}
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 0,
        pointerEvents: "none",
      }}
    />
  );
}