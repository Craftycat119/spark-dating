// Языки интерфейса: русский, украинский, английский. Тексты пишутся по-русски, а в украинском и английском режиме
// страница переводится на лету: MutationObserver подменяет текстовые узлы и атрибуты по словарю (i18n-uk.js, i18n-en.js).
// Пользовательский контент (сообщения, имена, описания) помечен translate="no" и не трогается.
import { EN, PATTERNS as PATTERNS_EN, cityEn } from "./i18n-en.js";
import { UK, PATTERNS as PATTERNS_UK, cityUk } from "./i18n-uk.js";

export const LANGS = ["ru", "uk", "en"];
const DICTS = { en: [EN, PATTERNS_EN], uk: [UK, PATTERNS_UK] };

const KEY = "lang";
const ATTRS = ["placeholder", "aria-label", "title", "alt"];
const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE"]);
const CYR = /[А-Яа-яЁё]/;
let lang = detect();
let observer = null;
export const missing = new Set(); // для разработки: какие строки ещё не переведены

/** Язык по умолчанию: выбранный раньше → язык Telegram → языки телефона/браузера по порядку.
 *  Украинский телефон или Telegram — украинский; русский и соседние языки — русский; остальные — английский. */
function detect() {
  try {
    const saved = localStorage.getItem(KEY);
    if (LANGS.includes(saved)) return saved;
  } catch { /* приватный режим */ }
  const tg = window.Telegram?.WebApp?.initDataUnsafe?.user?.language_code;
  const list = [tg, ...(navigator.languages || []), navigator.language].filter(Boolean).map((x) => x.toLowerCase());
  for (const l of list) {
    if (l.startsWith("uk")) return "uk";
    if (/^(ru|be|kk|ky|uz|tg|hy|az|ka|tk)\b/.test(l)) return "ru";
    if (l.startsWith("en")) return "en";
  }
  return list.length ? "en" : "ru";
}

export const getLang = () => lang;

export function setLang(value) {
  lang = LANGS.includes(value) ? value : "ru";
  try { localStorage.setItem(KEY, lang); } catch { /* не страшно */ }
  apply();
}

/** Название города на языке интерфейса: Нячанг → Nha Trang, Киев → Київ. */
export function cityLabel(name) {
  if (!name) return name;
  return lang === "en" ? cityEn(name) : lang === "uk" ? cityUk(name) : name;
}

/** Локаль для дат и чисел. */
export const locale = () => ({ en: "en-GB", uk: "uk-UA" })[lang] || "ru-RU";

/** Перевод строки (для кода, которому нужен текст до вставки в DOM). */
export function t(text) {
  return lang === "ru" ? text : translate(text);
}

function translate(text) {
  if (!text || !CYR.test(text)) return text;
  const lead = text.match(/^\s*/)[0], tail = text.match(/\s*$/)[0];
  const core = text.trim();
  const [DICT, PATTERNS] = DICTS[lang] || DICTS.en;
  let out = DICT[core];
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
  if (lang !== "ru") {
    if (!document.documentElement.dataset.title) document.documentElement.dataset.title = document.title;
    document.title = translate(document.documentElement.dataset.title);
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
  } else {
    if (document.documentElement.dataset.title) document.title = document.documentElement.dataset.title;
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  }
}

if (document.body) apply();
else document.addEventListener("DOMContentLoaded", apply);
window.__i18nMissing = missing;
