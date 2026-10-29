// Мелкие помощники интерфейса
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function toast(text, { error = false, image = null, onClick = null, timeout = 4000 } = {}) {
  const el = h(`<div class="toast ${error ? "error" : ""}" role="status">${image ? `<img src="${esc(image)}" alt="">` : ""}<div>${esc(text)}</div></div>`);
  el.onclick = () => { onClick?.(); el.remove(); };
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), timeout);
}

export function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function fmtDay(iso) {
  const d = new Date(iso);
  const today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Сегодня";
  if (d.toDateString() === y.toDateString()) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

export function fmtShort(iso) {
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString()
    ? fmtTime(iso)
    : d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

export function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export function confirmDialog(text, okLabel = "Да") {
  return new Promise((resolve) => {
    const el = h(`<div class="overlay"><div class="match-modal" style="gap:18px">
      <h2>${esc(text)}</h2>
      <button class="btn danger block" data-ok>${esc(okLabel)}</button>
      <button class="btn ghost block" data-no>Отмена</button></div></div>`);
    el.querySelector("[data-ok]").onclick = () => { el.remove(); resolve(true); };
    el.querySelector("[data-no]").onclick = () => { el.remove(); resolve(false); };
    document.body.append(el);
  });
}

export function pickMime(candidates) {
  if (!window.MediaRecorder) return null;
  return candidates.find((m) => MediaRecorder.isTypeSupported(m)) || "";
}
