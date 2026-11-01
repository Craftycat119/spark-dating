// Навигация по экранам. Обычно живёт в адресе страницы (#/feed, #/chat/5);
// в демо-странице, где адрес менять нельзя, — в памяти.
let memory = null;
let listener = null;

export function useMemoryRouting(start = "#/") {
  memory = start;
  document.addEventListener("click", (e) => {
    const a = e.target.closest?.('a[href^="#"]');
    if (!a) return;
    e.preventDefault();
    navigate(a.getAttribute("href"));
  });
}

export const currentHash = () => (memory !== null ? memory : location.hash);

export function onRoute(fn) {
  listener = fn;
  addEventListener("hashchange", () => memory === null && fn());
}

export function navigate(hash) {
  if (memory !== null) {
    memory = hash;
    listener?.();
  } else if (location.hash === hash) listener?.();
  else location.hash = hash;
}
