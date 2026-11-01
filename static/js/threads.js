// «Нити»: общие интересы нанизаны на вязаную нитку как бусины.
// Лайк — бусины стягиваются в сердце, пропуск — осыпаются вниз.
import { esc } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
const r1 = (v) => Math.round(v * 10) / 10;

function layout(n, W, CY) {
  const pts = [], top = n > 2 ? Math.ceil(n / 2) : n;
  const rows = n > 2 ? [[], []] : [[]];
  for (let i = 0; i < n; i++) (n > 2 ? rows[i < top ? 0 : 1] : rows[0]).push(i);
  rows.forEach((r, ri) => {
    const y = n > 2 ? (ri === 0 ? CY - 27 : CY + 28) : CY;
    r.forEach((ix, j) => (pts[ix] = { x: (W * (j + 1)) / (r.length + 1) + (n > 2 ? (ri === 0 ? -18 : 18) : 0), y }));
  });
  // бусины идут по нитке зигзагом: верх0, низ0, верх1, низ1…
  const order = [];
  if (n > 2) for (let i = 0; i < top; i++) { order.push(i); if (top + i < n) order.push(top + i); }
  else for (let i = 0; i < n; i++) order.push(i);
  return { pts, order };
}

// Плавная кривая через точки (Catmull-Rom → кубические Безье)
function curve(P) {
  let d = `M ${r1(P[0].x)} ${r1(P[0].y)}`;
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[i - 1] || P[i], p1 = P[i], p2 = P[i + 1], p3 = P[i + 2] || p2;
    d += ` C ${r1(p1.x + (p2.x - p0.x) / 6)} ${r1(p1.y + (p2.y - p0.y) / 6)} ${r1(p2.x - (p3.x - p1.x) / 6)} ${r1(p2.y - (p3.y - p1.y) / 6)} ${r1(p2.x)} ${r1(p2.y)}`;
  }
  return d;
}

const HEART = '<svg width="30" height="30" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.7 4.5c2.2 0 3.6 1.2 5.3 3.1 1.7-1.9 3.1-3.1 5.3-3.1 3.7 0 5.8 3.9 4.3 7.3C19.5 16.4 12 21 12 21z"/></svg>';

/** Рисует нитку в контейнере. Возвращает { play("like" | "skip") → Promise }. */
export function mountThread(box, labels) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  box.innerHTML = `
    <svg class="yarn" aria-hidden="true">
      <defs><filter id="yarn-soft" x="-10%" y="-50%" width="120%" height="200%"><feGaussianBlur stdDeviation="2.2"/></filter></defs>
      <path class="guide" fill="none" stroke="none"/>
      <g class="gT">
        <path class="shadow" transform="translate(0 4)" fill="none" stroke="#000" stroke-opacity=".5" stroke-width="7" stroke-linecap="round" filter="url(#yarn-soft)"/>
        <path class="core" fill="none" stroke="#8E3210" stroke-width="7" stroke-linecap="round"/>
        <path class="ply0" fill="none" stroke="#E8561A" stroke-width="3" stroke-linecap="round"/>
        <path class="ply1" fill="none" stroke="#C2440F" stroke-width="3" stroke-linecap="round"/>
        <path class="ply2" fill="none" stroke="#FF8A4C" stroke-width="3" stroke-linecap="round"/>
        <path class="gloss" fill="none" stroke="#FFD2B0" stroke-width="1" stroke-linecap="round" stroke-opacity=".7"/>
        <path class="fuzz" fill="none" stroke="#FFB07A" stroke-width=".8" stroke-linecap="round" stroke-opacity=".55"/>
      </g>
    </svg>
    <div class="beads">${labels.map((l) => `<div class="bead">${esc(l)}</div>`).join("")}</div>
    <div class="yarn-heart" aria-hidden="true">${HEART}</div>`;
  const svg = box.querySelector("svg");
  const q = (c) => box.querySelector("." + c);
  const guide = q("guide"), heart = q("yarn-heart"), group = q("gT");
  const beadEls = [...box.querySelectorAll(".bead")];
  const fuzzSeeds = Array.from({ length: 60 }, () => ({ a: Math.random(), side: Math.random() < 0.5 ? -1 : 1, len: 2 + Math.random() * 3.5, tilt: (Math.random() - 0.5) * 1.4 }));

  let W = 0, H = 0, CY = 0, L = { pts: [], order: [] };
  const measure = () => {
    W = box.clientWidth; H = box.clientHeight; CY = H / 2;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    L = layout(labels.length, W, CY);
  };
  measure();
  const ro = new ResizeObserver(measure);
  ro.observe(box);

  function yarn(d, t) {
    guide.setAttribute("d", d);
    q("shadow").setAttribute("d", d);
    q("core").setAttribute("d", d);
    const len = guide.getTotalLength(), n = Math.max(2, Math.ceil(len / 4)), S = [];
    for (let i = 0; i <= n; i++) { const p = guide.getPointAtLength((len * i) / n); S.push({ x: p.x, y: p.y, s: (len * i) / n }); }
    for (let i = 0; i < S.length; i++) {
      const a = S[Math.max(0, i - 1)], b = S[Math.min(S.length - 1, i + 1)];
      const dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1;
      S[i].nx = -dy / l; S[i].ny = dx / l;
    }
    const R = 2.2, TW = 0.42, spin = -t * 1.2;
    for (let k = 0; k < 3; k++) {
      let p = "";
      for (let i = 0; i < S.length; i++) { const o = R * Math.sin(S[i].s * TW + spin + k * 2.094); p += `${i ? " L " : "M "}${r1(S[i].x + S[i].nx * o)} ${r1(S[i].y + S[i].ny * o)}`; }
      q("ply" + k).setAttribute("d", p);
    }
    let gp = "";
    for (let i = 0; i < S.length; i++) { const o = R * Math.sin(S[i].s * TW + spin + 2.094) - 0.9; gp += `${i ? " L " : "M "}${r1(S[i].x + S[i].nx * o)} ${r1(S[i].y + S[i].ny * o)}`; }
    q("gloss").setAttribute("d", gp);
    let fz = "";
    for (const f of fuzzSeeds) {
      const P = S[Math.floor(f.a * (S.length - 1))], bx = P.x + P.nx * 3.2 * f.side, by = P.y + P.ny * 3.2 * f.side;
      fz += `M ${r1(bx)} ${r1(by)} L ${r1(bx + (P.nx * f.side + P.ny * f.tilt) * f.len)} ${r1(by + (P.ny * f.side - P.nx * f.tilt) * f.len)} `;
    }
    q("fuzz").setAttribute("d", fz);
  }

  let phase = "idle", k = 0, done = null, raf = 0;
  function frame(now) {
    if (!box.isConnected) { ro.disconnect(); return; }
    // в фоне (вкладка скрыта или поверх открыта анкета) не тратим батарею
    if (phase === "idle" && (document.hidden || document.querySelector(".profile-view"))) {
      raf = requestAnimationFrame(frame);
      return;
    }
    const t = reduce ? 0 : now / 1000;
    if (phase === "like") { k += (1 - k) * 0.09 + 0.004; if (k >= 0.99) { k = 1; phase = "end"; done?.(); } }
    if (phase === "skip") { k += 0.035; if (k >= 1) { k = 1; phase = "end"; done?.(); } }
    const like = phase === "like" || (phase === "end" && box.dataset.result === "like") ? k : 0;
    const skip = phase === "skip" || (phase === "end" && box.dataset.result === "skip") ? k : 0;
    const ease = like * like * (3 - 2 * like), fall = skip * skip, cx = W / 2;

    const pos = L.pts.map((b, i) => {
      const w = Math.sin(t * 1.6 + i * 1.3) * 4 * (1 - ease);
      return { x: b.x + (cx - b.x) * ease, y: b.y + w + (CY - b.y) * ease + fall * (260 + i * 40) };
    });
    beadEls.forEach((el, i) => {
      el.style.left = r1(pos[i].x) + "px";
      el.style.top = r1(pos[i].y) + "px";
      el.style.transform = `translate(-50%,-50%) rotate(${r1(skip * (i % 2 ? -1 : 1) * 25)}deg) scale(${r1(1 - ease * 0.25)})`;
      el.style.opacity = r1(1 - skip);
    });
    const pts = [{ x: -20 + ease * (cx + 20), y: CY - 45 + Math.sin(t) * 3 * (1 - ease) + fall * 120 }];
    L.order.forEach((ix) => pts.push(pos[ix]));
    pts.push({ x: W + 20 - ease * (cx + 20), y: CY + 45 + Math.sin(t + 1) * 3 * (1 - ease) + fall * 120 });
    if (pts.length === 2) pts.splice(1, 0, { x: cx, y: CY + Math.sin(t * 1.5) * 6 });
    yarn(curve(pts), t);
    group.style.opacity = r1(1 - skip);
    heart.style.opacity = r1(Math.max(0, (ease - 0.6) / 0.4));
    heart.style.transform = `translate(-50%,-50%) scale(${r1(0.4 + ease * 0.6)})`;
    if (!reduce || phase !== "idle") raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return {
    play(kind) {
      if (phase !== "idle") return Promise.resolve();
      box.dataset.result = kind;
      phase = kind; k = 0;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(frame);
      return new Promise((res) => (done = res));
    },
  };
}
