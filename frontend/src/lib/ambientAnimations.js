// Ambient background animations — six restrained, canvas-drawn effects.
// Off by default; each theme only offers the ones that actually fit its
// mood (see THEME_ANIMATIONS below), rather than every animation under
// every theme.

export const ANIMATIONS = [
  { id: "none", name: "None" },
  { id: "stars", name: "Twinkling Stars" },
  { id: "bokeh", name: "Drifting Bokeh" },
  { id: "matrix", name: "Falling Code" },
  { id: "aurora", name: "Flowing Aurora" },
  { id: "rain", name: "Rain" },
  { id: "snow", name: "Snowfall" },
];

// Which ambient animations make sense under each theme. Themes not listed
// (e.g. brutalist-mono, zen-minimal) offer none — motion would undercut
// the point of those themes.
export const THEME_ANIMATIONS = {
  "midnight-glass": ["bokeh", "rain", "aurora"],
  "terminal-noir": ["matrix"],
  "command-center": ["stars"],
  "deep-space": ["stars", "aurora", "snow"],
  "cyber-grid": ["matrix", "rain"],
  slate: ["snow", "bokeh"],
  "brutalist-mono": [],
  "zen-minimal": [],
};

function initStars(W, H) {
  return Array.from({ length: 100 }, () => ({
    x: Math.random() * W(), y: Math.random() * H(),
    r: 0.6 + Math.random() * 1.6, phase: Math.random() * Math.PI * 2, speed: 0.015 + Math.random() * 0.03,
  }));
}
function drawStars(ctx, W, H, particles) {
  ctx.clearRect(0, 0, W(), H());
  particles.forEach((p) => {
    const tw = (Math.sin(p.phase) + 1) / 2;
    ctx.globalAlpha = 0.15 + tw * 0.6;
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fill();
    p.phase += p.speed;
  });
  ctx.globalAlpha = 1;
}

function initBokeh(W, H) {
  return Array.from({ length: 14 }, () => ({
    x: Math.random() * W(), y: Math.random() * H(),
    r: 20 + Math.random() * 46, vx: (Math.random() - 0.5) * 0.2, vy: (Math.random() - 0.5) * 0.2,
    hue: 200 + Math.random() * 160, opacity: 0.03 + Math.random() * 0.06,
  }));
}
function drawBokeh(ctx, W, H, particles) {
  ctx.clearRect(0, 0, W(), H());
  particles.forEach((p) => {
    const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
    grad.addColorStop(0, `hsla(${p.hue},90%,70%,${p.opacity})`);
    grad.addColorStop(1, `hsla(${p.hue},90%,70%,0)`);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fill();
    p.x += p.vx; p.y += p.vy;
    if (p.x < -p.r) p.x = W() + p.r;
    if (p.x > W() + p.r) p.x = -p.r;
    if (p.y < -p.r) p.y = H() + p.r;
    if (p.y > H() + p.r) p.y = -p.r;
  });
}

const MATRIX_CHARS = "アイウエオカキクケコ0123456789ABCDEF";
function initMatrix(W, H) {
  const colW = 16;
  const count = Math.ceil(W() / colW);
  return Array.from({ length: count }, (_, i) => ({ x: i * colW, y: Math.random() * -H(), speed: 3 + Math.random() * 5 }));
}
function drawMatrix(ctx, W, H, cols) {
  ctx.fillStyle = "rgba(0,0,0,0.08)";
  ctx.fillRect(0, 0, W(), H());
  ctx.font = "13px monospace";
  cols.forEach((c) => {
    ctx.fillStyle = "rgba(60,255,120,0.55)";
    const ch = MATRIX_CHARS[Math.floor(Math.random() * MATRIX_CHARS.length)];
    ctx.fillText(ch, c.x, c.y);
    c.y += c.speed;
    if (c.y > H() + 20) c.y = Math.random() * -100;
  });
}

function drawAurora(ctx, W, H, state) {
  ctx.clearRect(0, 0, W(), H());
  const bands = [
    { color: "rgba(139,92,246,0.08)", amp: 40, freq: 0.004, offset: 0 },
    { color: "rgba(34,211,196,0.07)", amp: 55, freq: 0.003, offset: 2 },
    { color: "rgba(255,110,199,0.06)", amp: 35, freq: 0.005, offset: 4 },
  ];
  bands.forEach((b) => {
    ctx.beginPath();
    ctx.moveTo(0, H() * 0.3);
    for (let x = 0; x <= W(); x += 8) {
      const y = H() * 0.3 + Math.sin(x * b.freq + state.t * 0.01 + b.offset) * b.amp;
      ctx.lineTo(x, y);
    }
    ctx.lineTo(W(), 0);
    ctx.lineTo(0, 0);
    ctx.closePath();
    ctx.fillStyle = b.color;
    ctx.fill();
  });
  state.t += 1;
}

function initRain(W, H) {
  return Array.from({ length: 90 }, () => ({
    x: Math.random() * W(), y: Math.random() * H(),
    len: 10 + Math.random() * 14, speed: 6 + Math.random() * 8, opacity: 0.1 + Math.random() * 0.18,
  }));
}
function drawRain(ctx, W, H, particles) {
  ctx.clearRect(0, 0, W(), H());
  ctx.strokeStyle = "rgba(180,210,255,0.5)";
  particles.forEach((p) => {
    ctx.beginPath();
    ctx.globalAlpha = p.opacity;
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x - 2, p.y + p.len);
    ctx.lineWidth = 1;
    ctx.stroke();
    p.y += p.speed; p.x -= 0.6;
    if (p.y > H()) { p.y = -20; p.x = Math.random() * W(); }
  });
  ctx.globalAlpha = 1;
}

function initSnow(W, H) {
  return Array.from({ length: 60 }, () => ({
    x: Math.random() * W(), y: Math.random() * H(),
    r: 1.5 + Math.random() * 3, speed: 0.5 + Math.random() * 1.4,
    opacity: 0.3 + Math.random() * 0.4, phase: Math.random() * Math.PI * 2,
  }));
}
function drawSnow(ctx, W, H, particles) {
  ctx.clearRect(0, 0, W(), H());
  ctx.fillStyle = "#fff";
  particles.forEach((p) => {
    ctx.globalAlpha = p.opacity;
    ctx.beginPath();
    ctx.arc(p.x + Math.sin(p.phase) * 8, p.y, p.r, 0, Math.PI * 2);
    ctx.fill();
    p.y += p.speed; p.phase += 0.01;
    if (p.y > H()) { p.y = -10; p.x = Math.random() * W(); }
  });
  ctx.globalAlpha = 1;
}

/** Runs one animation on a canvas until the returned stop() is called. */
export function runAnimation(canvas, id) {
  if (id === "none" || !canvas) return () => {};
  const ctx = canvas.getContext("2d");
  const resize = () => {
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
  };
  resize();
  const onResize = () => resize();
  window.addEventListener("resize", onResize);

  const W = () => canvas.width, H = () => canvas.height;
  let particles = [];
  const auroraState = { t: 0 };

  if (id === "stars") particles = initStars(W, H);
  else if (id === "bokeh") particles = initBokeh(W, H);
  else if (id === "matrix") particles = initMatrix(W, H);
  else if (id === "rain") particles = initRain(W, H);
  else if (id === "snow") particles = initSnow(W, H);

  let rafId;
  const loop = () => {
    if (id === "stars") drawStars(ctx, W, H, particles);
    else if (id === "bokeh") drawBokeh(ctx, W, H, particles);
    else if (id === "matrix") drawMatrix(ctx, W, H, particles);
    else if (id === "aurora") drawAurora(ctx, W, H, auroraState);
    else if (id === "rain") drawRain(ctx, W, H, particles);
    else if (id === "snow") drawSnow(ctx, W, H, particles);
    rafId = requestAnimationFrame(loop);
  };
  loop();

  return () => {
    cancelAnimationFrame(rafId);
    window.removeEventListener("resize", onResize);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  };
}
