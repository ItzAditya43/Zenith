// Ambient background animations — six restrained, canvas-drawn effects.
// Off by default; each theme only offers the ones that actually fit its
// mood (see THEME_ANIMATIONS below), rather than every animation under
// every theme.
//
// Motion is time-based (pixels per second), so it runs at the same speed
// on 60 Hz and 144 Hz screens; the canvas is drawn at device-pixel
// resolution so nothing is blurry on HiDPI; colours follow the theme's
// accent; and the loop pauses while the window is hidden.

export const ANIMATIONS = [
  { id: "none", name: "None" },
  { id: "stars", name: "Twinkling Stars" },
  { id: "bokeh", name: "Drifting Bokeh" },
  { id: "matrix", name: "Falling Code" },
  { id: "aurora", name: "Flowing Aurora" },
  { id: "rain", name: "Rain" },
  { id: "snow", name: "Snowfall" },
];

export const THEME_ANIMATIONS = {
  "midnight-glass": ["bokeh", "rain", "aurora"],
  "terminal-noir": ["matrix"],
  // Moving backgrounds light pixels and burn battery on OLED.
  "oled-ember": [],
  "command-center": ["stars"],
  "deep-space": ["stars", "aurora", "snow"],
  "cyber-grid": ["matrix", "rain"],
  slate: ["snow", "bokeh"],
  "brutalist-mono": [],
  "zen-minimal": [],
};

const rand = (a, b) => a + Math.random() * (b - a);

function accentRGB() {
  const probe = document.createElement("span");
  probe.style.color = "var(--signal-general)";
  probe.style.display = "none";
  document.body.appendChild(probe);
  const m = getComputedStyle(probe).color.match(/[\d.]+/g);
  probe.remove();
  return m ? m.slice(0, 3).map(Number) : [140, 180, 255];
}

const EFFECTS = {
  stars: {
    init: (w, h) =>
      Array.from({ length: Math.round((w * h) / 14000) }, () => ({
        x: rand(0, w), y: rand(0, h), r: rand(0.4, 1.3), phase: rand(0, 6.28), speed: rand(0.4, 1.4),
      })),
    draw(ctx, w, h, ps, dt, [r, g, b]) {
      ctx.clearRect(0, 0, w, h);
      for (const p of ps) {
        p.phase += p.speed * dt;
        const tw = (Math.sin(p.phase) + 1) / 2;
        ctx.globalAlpha = 0.12 + tw * tw * 0.6;
        ctx.fillStyle = p.r > 1.1 ? `rgb(${r},${g},${b})` : "#fff";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, 6.283);
        ctx.fill();
      }
    },
  },
  bokeh: {
    init: (w, h) =>
      Array.from({ length: 12 }, () => ({
        x: rand(0, w), y: rand(0, h), r: rand(40, 120), vx: rand(-6, 6), vy: rand(-5, 5),
        a: rand(0.04, 0.09), phase: rand(0, 6.28),
      })),
    draw(ctx, w, h, ps, dt, [r, g, b]) {
      ctx.clearRect(0, 0, w, h);
      for (const p of ps) {
        p.x += p.vx * dt; p.y += p.vy * dt; p.phase += 0.3 * dt;
        if (p.x < -p.r) p.x = w + p.r; else if (p.x > w + p.r) p.x = -p.r;
        if (p.y < -p.r) p.y = h + p.r; else if (p.y > h + p.r) p.y = -p.r;
        const a = p.a * (0.75 + 0.25 * Math.sin(p.phase));
        const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
        grad.addColorStop(0, `rgba(${r},${g},${b},${a})`);
        grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
        ctx.fillStyle = grad;
        ctx.fillRect(p.x - p.r, p.y - p.r, p.r * 2, p.r * 2);
      }
    },
  },
  matrix: {
    init: (w, h) =>
      Array.from({ length: Math.ceil(w / 22) }, (_, i) => ({
        x: i * 22 + 4, y: rand(-h, 0), speed: rand(40, 110), acc: 0, trail: [],
      })),
    draw(ctx, w, h, cols, dt, [r, g, b]) {
      const CH = "アイウエオカキクケコサシスセソ0123456789";
      ctx.clearRect(0, 0, w, h);
      ctx.font = "13px 'JetBrains Mono', monospace";
      for (const c of cols) {
        c.y += c.speed * dt;
        c.acc += c.speed * dt;
        if (c.acc >= 18) {
          c.acc = 0;
          c.trail.unshift({ y: c.y, ch: CH[(Math.random() * CH.length) | 0] });
          if (c.trail.length > 14) c.trail.pop();
        }
        c.trail.forEach((t, i) => {
          ctx.globalAlpha = i === 0 ? 0.55 : 0.32 * (1 - i / 14);
          ctx.fillStyle = i === 0 ? "#e8fff0" : `rgb(${r},${g},${b})`;
          ctx.fillText(t.ch, c.x, t.y);
        });
        if (c.y > h + 260) { c.y = rand(-200, 0); c.trail = []; c.speed = rand(40, 110); }
      }
    },
  },
  aurora: {
    init: () => ({ t: 0 }),
    draw(ctx, w, h, s, dt, [r, g, b]) {
      s.t += dt;
      ctx.clearRect(0, 0, w, h);
      const bands = [
        [`${r},${g},${b}`, 60, 0.0025, 0.18, 0],
        ["139,92,246", 80, 0.0018, 0.13, 2],
        ["34,211,196", 50, 0.003, 0.22, 4],
      ];
      for (const [col, amp, freq, speed, off] of bands) {
        const base = h * 0.22;
        const grad = ctx.createLinearGradient(0, 0, 0, base + amp * 2);
        grad.addColorStop(0, `rgba(${col},0)`);
        grad.addColorStop(0.7, `rgba(${col},0.07)`);
        grad.addColorStop(1, `rgba(${col},0)`);
        ctx.beginPath();
        ctx.moveTo(0, 0);
        for (let x = 0; x <= w + 12; x += 12) {
          ctx.lineTo(x, base + Math.sin(x * freq + s.t * speed + off) * amp + Math.sin(x * freq * 2.3 + s.t * speed * 1.7) * amp * 0.3);
        }
        ctx.lineTo(w, 0);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
      }
    },
  },
  rain: {
    init: (w, h) =>
      Array.from({ length: Math.round(w / 22) }, () => {
        const z = rand(0.3, 1); // depth: near drops are longer, faster and brighter
        return { x: rand(0, w), y: rand(-h, h), z };
      }),
    draw(ctx, w, h, ps, dt, [r, g, b]) {
      ctx.clearRect(0, 0, w, h);
      ctx.lineCap = "round";
      for (const p of ps) {
        const speed = 380 + 520 * p.z, len = 14 + 26 * p.z;
        p.y += speed * dt; p.x -= speed * 0.08 * dt;
        if (p.y - len > h) { p.y = rand(-80, -10); p.x = rand(0, w + 60); }
        const grad = ctx.createLinearGradient(p.x, p.y - len, p.x, p.y);
        grad.addColorStop(0, `rgba(${r},${g},${b},0)`);
        grad.addColorStop(1, `rgba(220,235,255,${0.08 + 0.22 * p.z})`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 0.6 + 0.7 * p.z;
        ctx.beginPath();
        ctx.moveTo(p.x + len * 0.08, p.y - len);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
      }
    },
  },
  snow: {
    init: (w, h) =>
      Array.from({ length: Math.round(w / 24) }, () => {
        const z = rand(0.3, 1);
        return { x: rand(0, w), y: rand(0, h), z, phase: rand(0, 6.28) };
      }),
    draw(ctx, w, h, ps, dt) {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fff";
      for (const p of ps) {
        p.y += (14 + 34 * p.z) * dt; p.phase += 0.6 * dt;
        if (p.y > h + 6) { p.y = -6; p.x = rand(0, w); }
        ctx.globalAlpha = 0.15 + 0.45 * p.z;
        ctx.beginPath();
        ctx.arc(p.x + Math.sin(p.phase) * 14 * p.z, p.y, 0.8 + 2 * p.z, 0, 6.283);
        ctx.fill();
      }
    },
  },
};

/** Runs one animation on a canvas until the returned stop() is called. */
export function runAnimation(canvas, id) {
  const fx = EFFECTS[id];
  if (!fx || !canvas) return () => {};
  const ctx = canvas.getContext("2d");
  let w = 0, h = 0, state, rafId = 0, last = 0;
  const color = accentRGB();
  const reduce =
    document.documentElement.hasAttribute("data-reduce-motion") ||
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.offsetWidth; h = canvas.offsetHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    state = fx.init(w, h);
  };
  resize();

  const frame = (now) => {
    const dt = last ? Math.min((now - last) / 1000, 0.05) : 0.016;
    last = now;
    ctx.globalAlpha = 1;
    fx.draw(ctx, w, h, state, dt, color);
    ctx.globalAlpha = 1;
    rafId = requestAnimationFrame(frame);
  };
  const start = () => { if (!rafId) { last = 0; rafId = requestAnimationFrame(frame); } };
  const stop = () => { cancelAnimationFrame(rafId); rafId = 0; };
  const onVis = () => (document.hidden ? stop() : start());
  const onResize = () => { resize(); if (reduce) fx.draw(ctx, w, h, state, 0, color); };

  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", onVis);
  if (reduce) fx.draw(ctx, w, h, state, 0, color); // one still frame, no motion
  else start();
  requestAnimationFrame(() => canvas.classList.add("is-on"));

  return () => {
    stop();
    window.removeEventListener("resize", onResize);
    document.removeEventListener("visibilitychange", onVis);
    ctx.clearRect(0, 0, w, h);
  };
}
