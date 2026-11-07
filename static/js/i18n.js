// Языки интерфейса. Тексты пишутся по-русски, а в английском режиме страница переводится
// на лету: MutationObserver подменяет текстовые узлы и атрибуты по словарю (i18n-en.js).
// Пользовательский контент (сообщения, имена, описания) помечен translate="no" и не трогается.
import { EN, PATTERNS } from "./i18n-en.js";

const KEY = "lang";
const ATTRS = ["placeholder", "aria-label", "title", "alt"];
const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE"]);
const CYR = /[А-Яа-яЁё]/;
let lang = detect();
let observer = null;
export const missing = new Set(); // для разработки: какие строки ещё не переведены

function detect() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "ru" || saved === "en") return saved;
  } catch { /* приватный режим */ }
  return (navigator.language || "ru").toLowerCase().startsWith("ru") ? "ru" : "en";
}

export const getLang = () => lang;

export function setLang(value) {
  lang = value === "en" ? "en" : "ru";
  try { localStorage.setItem(KEY, lang); } catch { /* не страшно */ }
  apply();
}

/** Перевод строки (для кода, которому нужен текст до вставки в DOM). */
export function t(text) {
  return lang === "en" ? translate(text) : text;
}

function translate(text) {
  if (!text || !CYR.test(text)) return text;
  const lead = text.match(/^\s*/)[0], tail = text.match(/\s*$/)[0];
  const core = text.trim();
  let out = EN[core];
  if (out === undefined) {
    for (const [re, rep] of PATTERNS) {
      if (re.test(core)) {
        out = core.replace(re, rep);
        break;
      }
    }
  }
  if (out === undefined) {
    missing.add(core);
    return text;
  }
  return lead + out + tail;
}

function blocked(node) {
  const el = node.nodeType === 1 ? node : node.parentElement;
  return !el || el.closest('[translate="no"]') || SKIP.has(el.tagName);
}

function translateTree(root) {
  if (root.nodeType === 3) {
    if (!blocked(root)) {
      const v = translate(root.nodeValue);
      if (v !== root.nodeValue) root.nodeValue = v;
    }
    return;
  }
  if (root.nodeType !== 1 || blocked(root)) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let n = root; n; n = walker.nextNode()) {
    if (n.nodeType === 1) {
      if (n.getAttribute("translate") === "no") continue;
      for (const a of ATTRS) {
        const v = n.getAttribute(a);
        if (v && CYR.test(v)) {
          const tv = translate(v);
          if (tv !== v) n.setAttribute(a, tv); // писать только при изменении, иначе наблюдатель зациклится
        }
      }
    } else if (CYR.test(n.nodeValue) && !blocked(n)) {
      const tv = translate(n.nodeValue);
      if (tv !== n.nodeValue) n.nodeValue = tv;
    }
  }
}

function apply() {
  if (document.body.classList.contains("admin")) return; // админ-панель всегда на русском
  document.documentElement.lang = lang;
  if (lang === "en") {
    document.title = translate(document.title);
    translateTree(document.body);
    if (!observer) {
      observer = new MutationObserver((list) => {
        for (const m of list) {
          if (m.type === "characterData") translateTree(m.target);
          else if (m.type === "attributes") translateTree(m.target);
          else m.addedNodes.forEach(translateTree);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    }
  } else if (observer) {
    observer.disconnect();
    observer = null;
  }
}

if (document.body) apply();
else document.addEventListener("DOMContentLoaded", apply);
window.__i18nMissing = missing;
