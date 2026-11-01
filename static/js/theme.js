// Тема оформления: "dark" (по умолчанию), "light" или "system"
const KEY = "theme";
const media = matchMedia("(prefers-color-scheme: light)");

export function getThemePref() {
  try { return localStorage.getItem(KEY) || "dark"; } catch { return "dark"; }
}

export function resolvedTheme(pref = getThemePref()) {
  return pref === "system" ? (media.matches ? "light" : "dark") : pref;
}

export function applyTheme(pref = getThemePref()) {
  const t = resolvedTheme(pref);
  document.documentElement.dataset.theme = t;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", t === "light" ? "#f5eee6" : "#120c09");
}

export function setTheme(pref) {
  try { localStorage.setItem(KEY, pref); } catch { /* приватный режим */ }
  applyTheme(pref);
}

media.addEventListener("change", () => getThemePref() === "system" && applyTheme());
applyTheme();
