import { api, ApiError, connectSocket, disconnectSocket, on, send } from "./api.js";
import { initCalls, joinPendingCall, startCall } from "./call.js";
import { icons } from "./icons.js";
import { recordCircle, VoiceRecorder } from "./recorder.js";
import { runScanner } from "./scanner.js";
import { PACKS } from "./stickers.js";
import { mountThread } from "./threads.js";
import { renderGuide } from "./guide.js";
import { feedTabs, renderAnimals } from "./animals.js";
import { shrinkImage, takePhoto } from "./camera.js";
import { openAttachSheet } from "./attach.js";
import { createUploader } from "./uploads.js";
import { mountCaptcha } from "./captcha.js";
import { LEGAL_DOCS, renderTerms } from "./terms.js";
import { renderAds, renderSupportHub, renderThread, reportUser } from "./support.js";
import { currentHash, navigate, onRoute } from "./router.js";
import { getThemePref, resolvedTheme, setTheme } from "./theme.js";
import { getLang, setLang, t } from "./i18n.js";
import { $, $$, confirmDialog, esc, fmtDay, fmtDur, fmtShort, fmtTime, h, toast, wordmark } from "./ui.js";

const app = document.getElementById("app");

const state = {
  config: null,
  me: null,
  unread: 0,
  openChat: null, // id открытого чата
  shownMatches: new Set(),
};

// ---------------- 3D ----------------

/** Подгружает three.js только когда нужен объёмный объект; без WebGL остаётся SVG-логотип. */
function mount3d(el, shape) {
  if (!el) return;
  import("./puff3d.js")
    .then(({ mountPuff }) => {
      // Экран меняется через View Transition: новый экран попадает на страницу не сразу.
      // Ждём, пока он появится, иначе 3D не встанет и останется плоский логотип поверх текста.
      const tryMount = (frames = 0) => {
        if (!el.isConnected || !el.clientWidth) {
          if (frames < 120) requestAnimationFrame(() => tryMount(frames + 1));
          return;
        }
        const fallback = el.querySelector(".wordmark");
        if (mountPuff(el, { shape }) && fallback) fallback.remove();
      };
      tryMount();
    })
    .catch(() => { /* без 3D всё работает */ });
}

// ---------------- Запуск и маршрутизация ----------------

async function boot() {
  window.__cofiBooted = true; // для boot-guard.js: модули загрузились и приложение запустилось
  // Сразу говорим Telegram «загрузилось» и включаем меню (⋯ → «Настройки» → «Открыть в браузере»):
  // раньше это происходило только после ответа сервера, и при плохой связи висела заглушка с квадратами
  if (tgApp()?.initData) {
    try { tgApp().ready(); tgApp().expand(); } catch { /* старый Telegram */ }
    setupTelegramMenu();
    setupTgTab();
  }
  try {
    state.config = await api.get("/api/config", 15000);
  } catch {
    return offlineScreen();
  }
  try {
    state.me = await api.get("/api/auth/me", 15000);
  } catch (ex) {
    if (ex.status === 0) return offlineScreen();
    state.me = null;
  }
  await enterFromTelegram();
  if (state.me) afterLogin();
  // ссылки из уведомлений бота: /?chat=ID открывает чат, /?call=ID — входящий звонок
  const params = new URLSearchParams(location.search);
  if (params.has("chat") || params.has("call")) {
    history.replaceState(null, "", location.pathname + (location.hash || "#/"));
    if (state.me && params.get("chat")) navigate(`#/chat/${Number(params.get("chat"))}`);
    if (state.me && params.get("call") && state.config.calls_enabled) joinPendingCall(params.get("call"));
  }
  onRoute(route);
  route();
}

/** Открыли COFI как мини-приложение Telegram: Telegram кладёт подписанные данные в адрес (#tgWebAppData=…), входим по ним. */
/**
 * Открыли COFI как мини-приложение Telegram. Сразу не входим: человек видит стартовый экран и сам выбирает
 * «Войти через Telegram» (вход мгновенный, без перехода в бота). Сразу входим только по кнопкам из уведомлений
 * бота (?chat=, ?call=): это уже зарегистрированный человек, лишний экран ему не нужен.
 */
async function enterFromTelegram() {
  tgInitData = telegramInitData(); // запоминаем до очистки адреса
  if (location.hash.includes("tgWebAppData=")) history.replaceState(null, "", location.pathname + location.search + "#/");
  if (!tgInitData) return;
  try { tgApp()?.ready(); tgApp()?.expand(); } catch { /* старый Telegram */ }
  setupTelegramMenu();
  watchHomeScreen();
  const fromNotification = /[?&](chat|call)=/.test(location.search);
  if (state.me && !state.me.birth_date && !state.me.is_admin && !fromNotification) {
    // анкета даже не начата (вход случился сам, как в прошлой версии): показываем стартовый экран
    try { await api.post("/api/auth/logout"); } catch { /* всё равно покажем стартовый экран */ }
    state.me = null;
  }
  if (state.me || !fromNotification) return;
  try {
    state.me = await api.post("/api/auth/telegram/webapp", { init_data: tgInitData });
  } catch (ex) {
    toast(`Вход из Telegram не удался: ${ex.message}`, { error: true, timeout: 7000 });
  }
}

let tgInitData = "";

/** Открыть COFI обычным сайтом в Chrome / Safari. Там можно войти через Telegram или почту. */
function openInBrowser() {
  const url = location.origin + "/";
  try { tgApp().openLink(url, { try_instant_view: false }); } catch { window.open(url, "_blank"); }
}

// Ярлык Telegram на экране телефона. Он открывает «главное мини-приложение» бота (BotFather → Bot Settings →
// Configure Mini App): без него ярлык создаётся, но по нажатию ничего не запускается.
let homeStatus = "unknown"; // unsupported | unknown | added | missed
function watchHomeScreen() {
  const wa = tgApp();
  if (!wa?.checkHomeScreenStatus) return;
  try {
    wa.checkHomeScreenStatus((s) => (homeStatus = s || "unknown"));
    wa.onEvent?.("homeScreenAdded", () => {
      homeStatus = "added";
      toast("Ярлык добавлен. Если он не открывает COFI, откройте COFI в Safari или Chrome и добавьте ярлык оттуда", { timeout: 8000 });
    });
    wa.onEvent?.("homeScreenFailed", () => shortcutHelp());
  } catch { /* старый Telegram */ }
}
const canShortcut = () => tgApp()?.platform === "ios" || (!!tgApp()?.addToHomeScreen && homeStatus !== "unsupported");

function shortcutHelp() {
  toast("Telegram не смог добавить ярлык. Откройте COFI в браузере (меню ⋯ → «Настройки» → «Открыть в браузере») и добавьте на экран оттуда", { error: true, timeout: 9000 });
}

function addShortcut() {
  if (homeStatus === "added") return toast("Ярлык COFI уже есть на экране телефона");
  // На iPhone ярлык Telegram часто не запускает мини-приложение. Надёжный путь — ярлык из Safari: он открывает COFI сразу
  if (tgApp()?.platform === "ios") return iphoneShortcut();
  try { tgApp().addToHomeScreen(); } catch { shortcutHelp(); }
}

function iphoneShortcut() {
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Ярлык на iPhone">
    <div class="bottom-sheet stack">
      <h2>Ярлык COFI на iPhone</h2>
      <p class="muted">Ярлык будет открывать COFI сразу в Telegram</p>
      <ol class="howto">
        <li>Нажмите «Открыть в Safari» ниже</li>
        <li>В Safari нажмите «Поделиться» (квадрат со стрелкой вверх)</li>
        <li>Выберите «На экран „Домой“» → «Добавить»</li>
      </ol>
      <button class="btn block" data-a="safari">${icons.globe} Открыть в Safari</button>
      <button class="btn quiet block" data-a="close">Закрыть</button>
    </div></div>`);
  document.body.append(el);
  el.onclick = (e) => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (!a && e.target !== el) return;
    el.remove();
    if (a === "safari") {
      const url = location.origin + "/tg";
      try { tgApp().openLink(url, { try_instant_view: false }); } catch { window.open(url, "_blank"); }
    }
  };
}

/**
 * Пункт «Настройки» во всплывающем меню Telegram (⋯ в правом верхнем углу). Свои пункты туда добавить нельзя,
 * Telegram разрешает только этот, поэтому по нажатию показываем своё меню. Работает на любом шаге, даже до входа.
 */
let tgMenuReady = false;
function setupTelegramMenu() {
  const wa = tgApp();
  if (!wa?.SettingsButton || tgMenuReady) return;
  tgMenuReady = true;
  try {
    wa.SettingsButton.show();
    wa.SettingsButton.onClick(openTgMenu);
  } catch { /* старый Telegram без кнопки настроек */ }
}

/** Свой язычок в правом верхнем углу (в Telegram): «Открыть в браузере» видно сразу, без ⋯ → «Настройки». */
function setupTgTab() {
  if ($(".tg-tab")) return;
  document.documentElement.classList.add("in-tg");
  const tab = h(`<button class="tg-tab" aria-label="Открыть в браузере и другое">${icons.globe}</button>`);
  tab.onclick = openTgMenu;
  document.body.append(tab);
}

function openTgMenu() {
  const wa = tgApp();
  if ($(".tg-menu")) return;
  // меню выпадает из правого верхнего угла — прямо под кнопкой ⋯ Telegram, откуда его вызвали
  const el = h(`<div class="tg-menu" role="dialog" aria-label="Меню COFI">
    <div class="tg-drop" role="menu">
      <button class="tg-item main" role="menuitem" data-a="browser">${icons.globe}<span>Открыть в браузере</span></button>
      ${canShortcut() ? `<button class="tg-item" role="menuitem" data-a="home">${icons.phoneApp}<span>Ярлык на экран</span></button>` : ""}
      ${state.me ? `<a class="tg-item" role="menuitem" href="#/settings" data-a="settings">${icons.user}<span>Профиль и настройки</span></a>` : ""}
      ${state.me ? `<a class="tg-item" role="menuitem" href="#/support" data-a="support">${icons.headset}<span>Поддержка</span></a>` : ""}
    </div></div>`);
  document.body.append(el);
  requestAnimationFrame(() => el.classList.add("show"));
  const close = () => { el.classList.remove("show"); setTimeout(() => el.remove(), 180); };
  el.onclick = (e) => {
    const a = e.target.closest("[data-a]")?.dataset.a;
    if (!a && e.target !== el) return;
    close();
    if (a === "browser") openInBrowser();
    else if (a === "home") addShortcut();
  };
  const onKey = (e) => { if (e.key === "Escape") { close(); removeEventListener("keydown", onKey); } };
  addEventListener("keydown", onKey);
}

const tgApp = () => window.Telegram?.WebApp;

/** Открывает бота сразу в приложении Telegram, страница при этом остаётся и ждёт подтверждения. */
function openTelegram(url) {
  if (url.startsWith("#")) return; // демо: имитация бота
  if (tgApp()?.initData !== undefined && tgApp()?.platform && tgApp().platform !== "unknown") {
    try { return tgApp().openTelegramLink(url); } catch { /* ниже обычный способ */ }
  }
  const m = url.match(/t\.me\/([^?]+)\?start=(.+)$/);
  if (m) location.href = `tg://resolve?domain=${m[1]}&start=${m[2]}`; // приложение Telegram, без ухода со страницы
}

/** Подписанные данные Telegram, если COFI открыт как мини-приложение (скрипт Telegram или адрес #tgWebAppData=…). */
function telegramInitData() {
  if (tgInitData) return tgInitData;
  if (tgApp()?.initData) return tgApp().initData;
  const hash = location.hash.slice(1);
  return hash.includes("tgWebAppData=") ? new URLSearchParams(hash).get("tgWebAppData") : "";
}

let presenceBound = false;

function afterLogin() {
  connectSocket();
  // Сообщаем серверу, видна ли страница: свёрнутое мини-приложение держит соединение,
  // но человек ничего не видит, и тогда сообщения и звонки нужно присылать в Telegram
  if (!presenceBound) {
    presenceBound = true;
    const presence = () => send({ type: "presence", visible: document.visibilityState === "visible" });
    on("socket:open", presence);
    document.addEventListener("visibilitychange", presence);
    window.addEventListener("pagehide", () => send({ type: "presence", visible: false }));
  }
  if (state.config.calls_enabled) initCalls(state.config, async (convId) => {
    try {
      const c = await api.get(`/api/chats/${convId}?limit=1`);
      return c.user;
    } catch { return null; }
  });
  refreshLocationSilently();
  refreshUnread();
}

const go = navigate;

/** Перерисовать экран с нуля (после смены языка: тексты собираются заново). */
function rerender() {
  app.replaceChildren();
  route();
}

function onboardingStep(me) {
  if (me.is_admin) return me.name ? null : "admin"; // администратору анкета не нужна, только имя
  if (!me.name || !me.birth_date || !me.terms_accepted) return "about";
  if (!me.gender || !me.looking_for) return "identity";
  if (!me.survey_done && !me.extras_done) return "extras"; // рост, вес, знак — только при первой регистрации
  if (!me.survey_done) return "survey";
  if (!me.photo_url) return "photo";
  if (!me.photo_verified) return "scan";
  if (!me.has_location) return "location";
  return null;
}

let nextAuthMode = "login"; // какую вкладку открыть на экране входа при следующем показе

function route() {
  closeChat();
  $(".profile-view")?.remove();
  const page = currentHash().split("/")[1];
  if (page === "guide") return showGuide();
  if (page === "terms") return renderTerms({ screen, go });
  if (page === "legal") return renderTerms({ screen, go, doc: currentHash().split("/")[2] });
  if (page === "ads") return renderAds({ screen, go, loggedIn: !!state.me });
  if (!state.me) { const m = nextAuthMode; nextAuthMode = "login"; return renderAuth(m); }
  const step = onboardingStep(state.me);
  const [, name, arg] = currentHash().split("/");
  if (step && !["settings", "support"].includes(name)) return renderOnboarding(step);
  const ctx = { screen, state, go };
  switch (name) {
    case "animals": return renderAnimals(ctx);
    case "support": return arg ? renderThread({ screen, threadId: Number(arg) }) : renderSupportHub(ctx);
    case "chats": return renderChats();
    case "likes": return renderLikes();
    case "chat": return renderChats().then(() => openChat(Number(arg)));
    case "settings": return arg === "interests" ? renderSurvey({ editing: true }) : renderSettings();
    default: return renderFeed();
  }
}

function screen(html, { nav = true, cls = "" } = {}) {
  const main = h(`<main class="screen ${nav ? "" : "no-nav"} ${cls}">${html}</main>`);
  const swap = () => {
    app.replaceChildren(main);
    if (nav) app.append(navBar());
  };
  // Плавная смена экранов там, где браузер умеет View Transitions
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches && app.firstElementChild) {
    document.startViewTransition(swap);
  } else swap();
  return main;
}

function navBar() {
  const cur = currentHash().split("/")[1] || "feed";
  const item = (key, label, icon) =>
    `<a href="#/${key}" class="${cur === key || (key === "chats" && cur === "chat") || (key === "feed" && cur === "animals") ? "on" : ""}">${icon}<span>${label}</span>${
      key === "chats" && state.unread ? `<b class="badge">${state.unread}</b>` : ""}</a>`;
  return h(`<nav class="nav" aria-label="Разделы">${item("feed", "Ленты", icons.flame)}${item("chats", "Чаты", icons.chat)}${item("likes", "Отклики", icons.heartLine)}${item("settings", "Профиль", icons.user)}</nav>`);
}

function updateNavBadge() {
  const nav = $(".nav");
  if (nav) nav.replaceWith(navBar());
}

async function refreshUnread() {
  try {
    const chats = await api.get("/api/chats");
    state.unread = chats.reduce((s, c) => s + c.unread, 0);
    updateNavBadge();
  } catch { /* не критично */ }
}

async function reloadMe() {
  state.me = await api.get("/api/auth/me");
  return state.me;
}

// ---------------- Инструкция и демо ----------------

let stopGuide = null;

function showGuide() {
  stopGuide?.();
  const main = screen("", { nav: false, cls: "guide" });
  stopGuide = renderGuide(main, { loggedIn: !!state.me, onDemo: state.config.demo_enabled ? startDemo : null, calls: !!state.config.calls_enabled });
}

function startDemo() {
  // в демо две отдельные ленты: взрослая и подростковая, как в настоящем приложении
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Демо">
    <div class="bottom-sheet">
      <h2>Какое демо открыть</h2>
      <p class="muted">Подростки и взрослые в COFI никогда не пересекаются, поэтому ленты разные.</p>
      <button class="row-link" data-age="adult"><span><b>Мне 18 или больше</b><br><span class="muted small">Знакомства и питомцы, 10 анкет</span></span>${icons.arrow}</button>
      <button class="row-link" data-age="teen"><span><b>Мне 14–17</b><br><span class="muted small">Лента «Дружба», 6 анкет</span></span>${icons.arrow}</button>
      <button class="btn ghost block" data-close>Отмена</button>
    </div></div>`);
  $("[data-close]", el).onclick = () => el.remove();
  el.addEventListener("click", (e) => e.target === el && el.remove());
  $$("[data-age]", el).forEach((b) => (b.onclick = async () => {
    const teen = b.dataset.age === "teen";
    try {
      state.me = await api.post("/api/auth/demo", { teen });
    } catch (ex) {
      return toast(ex.message, { error: true });
    }
    el.remove();
    afterLogin();
    go("#/feed");
    toast(teen ? "Это демо ленты «Дружба»: свайп по нитке вниз, чтобы добавить в друзья" : "Это демо: свайп по нитке вниз, чтобы лайкнуть. Некоторые боты уже лайкнули вас", { timeout: 6000 });
  }));
  document.body.append(el);
}

function themeIcon() {
  return resolvedTheme() === "light" ? icons.moon : icons.sun;
}

// ---------------- Вход и регистрация ----------------

function renderAuth(mode = "login") {
  const sheet = `
    <div class="panel stack sheet">
      <div class="tabs" role="tablist">
        <button role="tab" data-mode="login" class="${mode === "login" ? "on" : ""}">Вход</button>
        <button role="tab" data-mode="register" class="${mode === "register" ? "on" : ""}">Регистрация</button>
      </div>
      <form class="stack" novalidate>
        <label class="field"><span>Почта</span><input class="input" type="email" name="email" autocomplete="email" required></label>
        <label class="field"><span>Пароль</span><input class="input" type="password" name="password" autocomplete="${mode === "login" ? "current-password" : "new-password"}" required></label>
        ${mode === "register" ? `<ul class="checklist" id="pw-rules">
          <li data-rule="len">Не меньше 8 символов</li><li data-rule="upper">Хотя бы одна заглавная буква</li><li data-rule="digit">Хотя бы одна цифра</li></ul>` : ""}
        <div data-captcha></div>
        <p class="error-text" id="auth-error" hidden></p>
        <button class="btn block" type="submit">${mode === "login" ? "Войти" : "Создать аккаунт"}</button>
        ${mode === "register" ? `<p class="auth-legal">COFI в режиме бесплатного тестирования. Знакомства с 18 лет, с 14 до 17 только «Дружба». Создавая аккаунт, вы принимаете <a href="#/legal/terms" data-doc="terms">Пользовательское соглашение</a> и <a href="#/legal/rules" data-doc="rules">Правила</a></p>` : ""}
        ${mode === "login" ? `<button type="button" class="link" id="forgot" style="align-self:flex-start">Забыли пароль?</button>` : ""}
      </form>
      <div class="divider">или</div>
      <button type="button" class="btn tg block" id="tg-login">${icons.send} Войти через Telegram</button>
      <p class="hint" style="text-align:center">Через Telegram почта и пароль не нужны, только подтверждение фото.</p>
    </div>`;
  // Повторный вызов (переключение вкладок) меняет только панель, 3D-сцена остаётся
  let root = $(".screen.auth");
  if (root) {
    const fresh = h(sheet);
    fresh.style.animation = "none";
    $(".sheet", root).replaceWith(fresh);
  } else {
    root = screen(`
    <section class="hero3d">
      <div class="stage" aria-hidden="true">${wordmark("COFI")}</div>
      <span class="brand">cofi<sup>°</sup></span>
      <button class="icon-btn theme-toggle" aria-label="Сменить тему">${themeIcon()}</button>
      <div class="hero-copy">
        <h1>Знакомства, где общее находится сразу</h1>
        <p>Отметьте, что любите, и мы покажем людей рядом с похожими интересами.</p>
        <div class="hero-links">
          ${state.config.demo_enabled ? `<button class="chip hot" data-demo>Демо без регистрации</button>` : ""}
          <a class="chip" href="#/guide">Как это работает</a>
        </div>
        <div class="hero-foot"><a href="#/ads">Реклама в COFI</a><button class="lang-toggle" data-lang-toggle>${getLang() === "en" ? "RU" : "EN"}</button></div>
      </div>
    </section>
${sheet}`, { nav: false, cls: "auth" });
    mount3d($(".stage", root), "knot");
    $("[data-demo]", root)?.addEventListener("click", startDemo);
    $("[data-lang-toggle]", root).onclick = () => { setLang(getLang() === "en" ? "ru" : "en"); rerender(); };
    $(".theme-toggle", root).onclick = (e) => {
      setTheme(resolvedTheme() === "light" ? "dark" : "light");
      e.currentTarget.innerHTML = themeIcon();
    };
  }
  $$("[data-mode]", root).forEach((b) => (b.onclick = () => renderAuth(b.dataset.mode)));
  const form = $("form", root);
  const err = $("#auth-error", root);
  const robot = mountCaptcha($("[data-captcha]", root), state.config.captcha);
  const showErr = (m) => { err.textContent = m; err.hidden = !m; };

  if (mode === "register") {
    form.password.addEventListener("input", () => {
      const v = form.password.value;
      const ok = { len: v.length >= 8, upper: /\p{Lu}/u.test(v), digit: /\d/.test(v) };
      $$("#pw-rules li", root).forEach((li) => li.classList.toggle("ok", ok[li.dataset.rule]));
    });
  }

  form.onsubmit = async (e) => {
    e.preventDefault();
    showErr("");
    const email = form.email.value.trim();
    const password = form.password.value;
    if (!email || !password) return showErr("Введите почту и пароль");
    const btn = $("button[type=submit]", form);
    btn.disabled = true;
    try {
      if (mode === "register") {
        const r = await api.post("/api/auth/register", { email, password, ...robot.values() });
        renderCode(email, r.dev_code);
        if (r.status === "code_pending") toast(`Код уже отправлен на эту почту. ${r.detail}`);
      } else {
        state.me = await api.post("/api/auth/login", { email, password, ...robot.values() });
        afterLogin();
        go("#/feed");
      }
    } catch (ex) {
      if (ex.code === "email_not_verified") return renderCode(email, ex.detail.dev_code);
      showErr(ex.message);
      robot.refresh(); // картинка одноразовая: после любой неудачи — новая
    } finally {
      btn.disabled = false;
    }
  };

  $("#forgot", root)?.addEventListener("click", () => renderForgot(form.email.value.trim()));

  $("#tg-login", root).onclick = telegramLogin;
}

/** Вход через бота: ссылка t.me/<бот>?start=login_…, человек жмёт «Войти» в Telegram, страница ждёт подтверждения. */
async function telegramLogin() {
  // Внутри мини-приложения Telegram уже знает, кто вы: входим сразу, без перехода в бота
  const initData = telegramInitData();
  if (initData) {
    try {
      state.me = await api.post("/api/auth/telegram/webapp", { init_data: initData });
      afterLogin();
      go("#/feed");
      return;
    } catch (ex) {
      toast(ex.message, { error: true });
    }
  }
  let start;
  try {
    start = await api.post("/api/auth/telegram/start");
  } catch (ex) {
    return toast(ex.message, { error: true, timeout: 6000 });
  }
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Вход через Telegram">
    <div class="bottom-sheet tg-sheet">
      <div class="tg-head"><span class="tg-logo">${icons.send}</span><b>Telegram</b></div>
      <h2>Подтвердите вход в Telegram</h2>
      <p class="muted">Откройте бота COFI, нажмите «Запустить», затем «Войти». Эта страница войдёт сама.</p>
      <a class="btn tg block" href="${esc(start.url)}" target="_blank" rel="noopener">${icons.send} Открыть Telegram</a>
      <p class="hint tg-wait"><span class="spinner"></span> Ждём подтверждения…</p>
      <button class="btn ghost block" data-close>Отмена</button>
    </div></div>`);
  let active = true;
  const close = () => { active = false; el.remove(); };
  $("[data-close]", el).onclick = close;
  document.body.append(el);
  openTelegram(start.url);
  $("a.btn.tg", el).onclick = (e) => { e.preventDefault(); openTelegram(start.url); };
  const deadline = Date.now() + start.expires_in * 1000;
  while (active && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 2000));
    if (!active) return;
    try {
      const r = await api.post("/api/auth/telegram/poll", { token: start.token });
      if (r.status === "ok") {
        close();
        state.me = r.user;
        afterLogin();
        go("#/feed");
        return;
      }
    } catch (ex) {
      close();
      return toast(ex.message, { error: true });
    }
  }
  if (active) { close(); toast("Время на подтверждение вышло, попробуйте ещё раз", { error: true }); }
}

function codeInputs(container, onComplete) {
  const boxes = $$("input", container);
  const value = () => boxes.map((b) => b.value).join("");
  boxes.forEach((box, i) => {
    box.addEventListener("input", () => {
      box.value = box.value.replace(/\D/g, "").slice(-1);
      if (box.value && i < boxes.length - 1) boxes[i + 1].focus();
      if (value().length === boxes.length) onComplete(value());
    });
    box.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !box.value && i > 0) boxes[i - 1].focus();
    });
    box.addEventListener("paste", (e) => {
      const digits = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, boxes.length);
      if (!digits) return;
      e.preventDefault();
      digits.split("").forEach((d, j) => (boxes[j].value = d));
      boxes[Math.min(digits.length, boxes.length - 1)].focus();
      if (digits.length === boxes.length) onComplete(digits);
    });
  });
  boxes[0].focus();
  return { clear: () => { boxes.forEach((b) => (b.value = "")); boxes[0].focus(); } };
}

const codeBoxesHtml = `<div class="code-boxes">${'<input class="input" inputmode="numeric" maxlength="1" autocomplete="one-time-code" aria-label="Цифра кода">'.repeat(6)}</div>`;

function renderCode(email, devCode) {
  const root = screen(`
    ${backBtn()}
    <div class="stack">
      <h1>Проверьте почту</h1>
      <p class="muted">Мы отправили 6-значный код на <b style="color:var(--text)">${esc(email)}</b>. Если письма нет пару минут, проверьте папку «Спам».</p>
      ${devCode ? `<p class="hint">Режим разработки, почта не настроена. Код: <b>${esc(devCode)}</b></p>` : ""}
      ${codeBoxesHtml}
      <p class="error-text" id="code-error" hidden></p>
      <button class="btn ghost" id="resend">Отправить код ещё раз</button>
      <button class="link" id="back" style="align-self:flex-start">Изменить почту</button>
    </div>`, { nav: false });
  const err = $("#code-error", root);
  const inputs = codeInputs($(".code-boxes", root), async (code) => {
    err.hidden = true;
    try {
      state.me = await api.post("/api/auth/verify-email", { email, code });
      afterLogin();
      go("#/feed");
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
      inputs.clear();
    }
  });
  $("#resend", root).onclick = async () => {
    try {
      const r = await api.post("/api/auth/resend-code", { email });
      toast("Новый код отправлен" + (r.dev_code ? `: ${r.dev_code}` : ""));
    } catch (ex) { toast(ex.message, { error: true }); }
  };
  $("#back", root).onclick = () => renderAuth("register");
  bindBack(root, () => renderAuth("register"));
}

function renderForgot(prefill = "") {
  const root = screen(`
    ${backBtn()}
    <div class="stack">
      <h1>Новый пароль</h1>
      <p class="muted">Пришлём код на почту, после чего вы зададите новый пароль.</p>
      <form class="stack" id="f1">
        <label class="field"><span>Почта</span><input class="input" type="email" name="email" value="${esc(prefill)}" required></label>
        <div data-captcha></div>
        <button class="btn block">Получить код</button>
      </form>
      <form class="stack" id="f2" hidden>
        <p class="hint" id="dev-hint" hidden></p>
        <label class="field"><span>Код из письма</span><input class="input" name="code" inputmode="numeric" maxlength="6" required></label>
        <label class="field"><span>Новый пароль</span><input class="input" type="password" name="password" autocomplete="new-password" required></label>
        <p class="hint">Не меньше 8 символов, заглавная буква и цифра.</p>
        <button class="btn block">Сохранить пароль и войти</button>
      </form>
      <button class="link" id="back" style="align-self:flex-start">Вернуться ко входу</button>
    </div>`, { nav: false });
  const f1 = $("#f1", root), f2 = $("#f2", root);
  const robot = mountCaptcha($("[data-captcha]", f1), state.config.captcha);
  f1.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api.post("/api/auth/forgot-password", { email: f1.email.value.trim(), ...robot.values() });
      f2.hidden = false;
      if (r.dev_code) { $("#dev-hint", root).hidden = false; $("#dev-hint", root).textContent = `Режим разработки: код ${r.dev_code}`; }
      f2.code.focus();
    } catch (ex) { toast(ex.message, { error: true }); robot.refresh(); }
  };
  f2.onsubmit = async (e) => {
    e.preventDefault();
    try {
      state.me = await api.post("/api/auth/reset-password", { email: f1.email.value.trim(), code: f2.code.value.trim(), password: f2.password.value });
      afterLogin();
      go("#/feed");
    } catch (ex) { toast(ex.message, { error: true }); }
  };
  $("#back", root).onclick = () => renderAuth("login");
  bindBack(root, () => renderAuth("login"));
}

// ---------------- Онбординг ----------------

const STEP_ORDER = ["about", "identity", "extras", "survey", "photo", "scan", "location"];

/** Кнопка «Назад» над шагом регистрации. */
const backBtn = (label = "Назад") => `<button type="button" class="back-btn" data-step-back>${icons.back}<span>${label}</span></button>`;

function bindBack(root, fn) {
  $("[data-step-back]", root)?.addEventListener("click", fn);
}

/** Выйти из незавершённой регистрации и вернуться к выбору способа: почта или Telegram. */
async function changeSignupMethod() {
  try { await api.post("/api/auth/logout"); } catch {}
  disconnectSocket();
  state.me = null;
  nextAuthMode = "register";
  go("#/");
}

const STEP_BACK = {
  about: changeSignupMethod,
  identity: () => stepAbout(),
  extras: () => stepIdentity(),
  survey: () => stepExtras({ fromEnd: true }),
  photo: () => renderSurvey({ fromEnd: true }),
  scan: () => stepPhoto(),
  location: () => stepScan(),
};

function stepsBar(step) {
  const i = STEP_ORDER.indexOf(step);
  return `${backBtn(step === "about" ? "Сменить способ входа" : "Назад")}<div class="steps" aria-label="Шаг ${i + 1} из ${STEP_ORDER.length}">${STEP_ORDER.map((_, j) => `<i class="${j <= i ? "done" : ""}"></i>`).join("")}</div>`;
}

async function nextStep() {
  await reloadMe();
  route();
}

function renderOnboarding(step) {
  ({ admin: stepAdminName, about: stepAbout, identity: stepIdentity, extras: () => stepExtras(), survey: () => renderSurvey(), photo: stepPhoto, scan: stepScan, location: stepLocation })[step]();
}

function choiceGroup(name, options, value, cols = Object.keys(options).length) {
  return `<div class="choice-grid" style="grid-template-columns:repeat(${cols},1fr)" role="radiogroup">${Object.entries(options).map(([k, label]) =>
    `<button type="button" class="chip" data-name="${name}" data-value="${k}" aria-pressed="${k === value}">${esc(label)}</button>`).join("")}</div>`;
}

function bindChoice(root, name, onPick) {
  $$(`[data-name="${name}"]`, root).forEach((b) => (b.onclick = () => {
    $$(`[data-name="${name}"]`, root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    onPick(b.dataset.value);
  }));
}

function ageOf(birth) {
  if (!birth) return null;
  const b = new Date(birth), now = new Date();
  return now.getFullYear() - b.getFullYear() - (now < new Date(now.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0);
}

/** Текст плашки о возрасте: взрослым — «мне есть 18», подросткам — согласие родителя. */
function ageConsentText(birth) {
  const age = ageOf(birth);
  if (age !== null && age < 18) {
    return "Мне от 14 до 17 лет. Мой законный представитель ознакомлен с документами COFI и согласен с регистрацией. Мне будет доступна только лента «Дружба»";
  }
  return "Подтверждаю, что мне исполнилось 18 лет";
}

/** Варианты сексуальности под выбранный пол: девушке — «лесби», парню — «гей», небинарным — оба. */
function orientationsFor(gender) {
  const all = state.config.orientations || {};
  const keys = state.config.orientations_by_gender?.[gender] || Object.keys(all);
  return Object.fromEntries(keys.filter((k) => k in all).map((k) => [k, all[k]]));
}

/**
 * Пол, сексуальность (с 18 лет) и два отдельных переключателя «показывать в анкете».
 * Всё в одном спокойном блоке: сексуальность свёрнута и необязательна.
 */
function identityFields(box, pick, age) {
  const adult = age === null || age >= 18;
  const genders = adult ? state.config.genders : state.config.teen_genders || state.config.genders;
  if (!(pick.gender in genders)) pick.gender = null;
  if (!adult) pick.orientation = null;
  const withSexuality = adult && !!state.config.orientations;
  const draw = () => {
    const opts = orientationsFor(pick.gender);
    if (pick.orientation && !(pick.orientation in opts)) pick.orientation = "";
    const current = pick.orientation ? opts[pick.orientation] : "не указана";
    box.innerHTML = `
      <div class="field"><span>Пол</span>${choiceGroup("gender", genders, pick.gender, 3)}</div>
      <div class="identity-box">
        ${withSexuality ? `<details class="soft-details" ${box.dataset.open ? "open" : ""}>
          <summary><span>Сексуальность</span><span class="muted">${esc(current)}</span></summary>
          <div class="chips small-chips">${Object.entries(opts).map(([k, l]) =>
            `<button type="button" class="chip" data-name="orientation" data-value="${k}" aria-pressed="${k === pick.orientation}">${esc(l)}</button>`).join("")}</div>
          <p class="hint">Необязательно. Нажмите ещё раз, чтобы снять выбор</p>
        </details>` : ""}
        ${withSexuality && pick.orientation && !state.me.consent_sexuality ? `<label class="check consent small"><input type="checkbox" data-sex-consent ${pick.consent_sexuality ? "checked" : ""}>
          <span>Даю <a href="#/legal/sexuality" data-doc="sexuality">согласие на обработку сведений о сексуальности</a></span></label>` : ""}
        <label class="switch compact"><input type="checkbox" data-show="show_identity" ${pick.show_identity !== false ? "checked" : ""}>
          <span class="label">Показывать пол в анкете</span></label>
        ${withSexuality ? `<label class="switch compact"><input type="checkbox" data-show="show_orientation" ${pick.show_orientation !== false ? "checked" : ""}>
          <span class="label">Показывать сексуальность</span></label>` : ""}
        <p class="hint">Скрытое не видно другим. Подбор по «кого ищу» работает всё равно</p>
      </div>`;
    bindChoice(box, "gender", (v) => { pick.gender = v; draw(); });
    $$('[data-name="orientation"]', box).forEach((b) => (b.onclick = () => {
      pick.orientation = pick.orientation === b.dataset.value ? "" : b.dataset.value;
      box.dataset.open = "1";
      draw();
    }));
    $("details", box)?.addEventListener("toggle", (e) => (e.target.open ? (box.dataset.open = "1") : delete box.dataset.open));
    $$("[data-show]", box).forEach((x) => (x.onchange = () => (pick[x.dataset.show] = x.checked)));
    $("[data-sex-consent]", box)?.addEventListener("change", (e) => (pick.consent_sexuality = e.target.checked));
  };
  draw();
}

const identityPick = (me) => ({
  gender: me.gender, looking_for: me.looking_for, orientation: me.orientation || "",
  show_identity: me.show_identity !== false, show_orientation: me.show_orientation !== false,
});

const ZODIAC_SIGNS = { aries: "♈", taurus: "♉", gemini: "♊", cancer: "♋", leo: "♌", virgo: "♍", libra: "♎", scorpio: "♏", sagittarius: "♐", capricorn: "♑", aquarius: "♒", pisces: "♓" };

/** Знак зодиака по дате рождения — подсказка, человек может выбрать другой или пропустить. */
function zodiacOf(birth) {
  if (!birth) return null;
  const d = new Date(birth), md = (d.getMonth() + 1) * 100 + d.getDate();
  const edges = [[120, "capricorn"], [219, "aquarius"], [321, "pisces"], [420, "aries"], [521, "taurus"], [621, "gemini"],
    [723, "cancer"], [823, "leo"], [923, "virgo"], [1023, "libra"], [1122, "scorpio"], [1222, "sagittarius"], [1232, "capricorn"]];
  return edges.find(([edge]) => md < edge)[1];
}

/** Рост, вес и знак зодиака: по экрану на каждый, всё можно пропустить. Подросткам вес не предлагаем. */
function stepExtras({ fromEnd = false } = {}) {
  const me = state.me;
  const parts = me.age_group === "teen" ? ["height", "zodiac"] : ["height", "weight", "zodiac"];
  const vals = { height_cm: me.height_cm || 170, weight_kg: me.weight_kg || 65, zodiac: me.zodiac || zodiacOf(me.birth_date) };
  const chosen = { height_cm: !!me.height_cm, weight_kg: !!me.weight_kg, zodiac: !!me.zodiac };
  let i = fromEnd ? parts.length - 1 : 0;
  const finish = async () => {
    const data = { extras_done: true };
    for (const k of ["height_cm", "weight_kg", "zodiac"]) data[k] = chosen[k] ? vals[k] : 0;
    data.zodiac = chosen.zodiac ? vals.zodiac : "";
    try { state.me = await api.put("/api/profile", data); nextStep(); } catch (ex) { toast(ex.message, { error: true }); }
  };
  const next = () => (i < parts.length - 1 ? (i++, draw()) : finish());
  const slider = (key, min, max, unit) => `
    <div class="big-value"><b data-val>${vals[key]}</b><span>${unit}</span></div>
    <input type="range" class="big-range" min="${min}" max="${max}" value="${vals[key]}" data-range="${key}" aria-label="${unit}">
    <div class="range-ends muted small"><span>${min}</span><span>${max}</span></div>`;
  const draw = () => {
    const part = parts[i];
    const body = {
      height: `<h1>Ваш рост</h1>${slider("height_cm", 120, 230, "см")}`,
      weight: `<h1>Ваш вес</h1>${slider("weight_kg", 35, 200, "кг")}`,
      zodiac: `<h1>Знак зодиака</h1>${!me.zodiac && vals.zodiac ? `<p class="muted">Подсказали по дате рождения</p>` : ""}
        <div class="zodiac-grid">${Object.entries(state.config.zodiac || {}).map(([k, l]) =>
          `<button type="button" class="chip zodiac" data-z="${k}" aria-pressed="${k === vals.zodiac}"><span aria-hidden="true">${ZODIAC_SIGNS[k] || ""}</span>${esc(l)}</button>`).join("")}</div>`,
    }[part];
    const root = screen(`${stepsBar("extras")}
      <div class="stack" style="gap:18px">
        <div class="survey-head"><span class="muted small">Необязательно, можно пропустить</span><span class="survey-count">${i + 1}/${parts.length}</span></div>
        ${body}
        <div class="row" style="margin-top:8px">
          ${i > 0 ? `<button class="btn ghost" data-prev>Назад</button>` : ""}
          <button class="btn" data-next style="flex:1">Дальше</button>
        </div>
        <button class="link" data-skip style="align-self:center">Пропустить</button>
      </div>`, { nav: false });
    const range = $("[data-range]", root);
    if (range) range.oninput = () => { vals[range.dataset.range] = Number(range.value); $("[data-val]", root).textContent = range.value; };
    $$("[data-z]", root).forEach((b) => (b.onclick = () => {
      vals.zodiac = b.dataset.z;
      $$("[data-z]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    }));
    const key = { height: "height_cm", weight: "weight_kg", zodiac: "zodiac" }[part];
    $("[data-next]", root).onclick = () => { chosen[key] = !!vals[key]; next(); };
    $("[data-skip]", root).onclick = () => { chosen[key] = false; next(); };
    $("[data-prev]", root)?.addEventListener("click", () => { i--; draw(); });
    bindBack(root, () => (i > 0 ? (i--, draw()) : STEP_BACK.extras()));
  };
  draw();
}

/** Администратор: только имя, остальное не нужно. */
function stepAdminName() {
  const root = screen(`
    <form class="stack" style="margin-top:24px">
      <span class="admin-badge big">${icons.shield} Администрация COFI</span>
      <h1>Как вас подписывать</h1>
      <p class="muted">Имя видят пользователи в ответах поддержки рядом со значком «Администрация». Анкету заполнять не нужно.</p>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" required autocomplete="given-name"></label>
      <p class="error-text" hidden></p>
      <button class="btn block">Готово</button>
    </form>`, { nav: false });
  $("form", root).onsubmit = async (e) => {
    e.preventDefault();
    try {
      state.me = await api.put("/api/profile", { name: e.target.name.value });
      route();
    } catch (ex) { const err = $(".error-text", root); err.textContent = ex.message; err.hidden = false; }
  };
}

/** Экран ленты для администратора без анкеты: его самого в ленте нет, а смотреть есть что в админ-панели. */
function adminHome(root) {
  $(".deck", root).replaceChildren(h(`<div class="empty">
    <span class="admin-badge big">${icons.shield} Администрация COFI</span>
    <h2>Вы вошли как администратор</h2>
    <p class="muted">Анкеты, обращения, жалобы, питомцы и рассылки — в админ-панели. Свою анкету заполнять не нужно, в ленте вас никто не видит.</p>
    <a class="btn" href="/admin">Открыть админ-панель</a>
    <a class="btn ghost" href="#/animals">Посмотреть ленту «Питомцы»</a>
  </div>`));
}

/** Шаг 1: имя, дата рождения и согласия. Пол и сексуальность — только на следующем шаге,
 *  когда возраст уже известен: подросток не увидит вариантов для «Знакомств». */
function stepAbout() {
  const me = state.me;
  const root = screen(`${stepsBar("about")}
    <form class="stack">
      <h1>Знакомимся</h1>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(me.name)}" autocomplete="given-name" required></label>
      <label class="field"><span>Дата рождения</span><input class="input" name="birth" type="date" value="${me.birth_date ?? ""}" ${me.birth_date ? "disabled" : ""} required max="${new Date().toISOString().slice(0, 10)}"></label>
      <p class="hint">COFI доступен с 14 лет. До 18 лет доступна только лента «Дружба». Дату нельзя будет изменить самостоятельно.</p>
      <p class="legal-note small">COFI работает в режиме бесплатного некоммерческого тестирования.</p>
      <div class="consent">
        <label class="check"><input type="checkbox" name="confirm_age" ${me.terms_accepted ? "checked" : ""}><span data-age-text>${ageConsentText(me.birth_date)}</span></label>
        <label class="check"><input type="checkbox" name="accept_terms" ${me.terms_accepted ? "checked" : ""}><span>Принимаю <a href="#/legal/terms" data-doc="terms">Пользовательское соглашение</a> и <a href="#/legal/rules" data-doc="rules">Правила сообщества</a>, ознакомлен(а) с <a href="#/legal/privacy" data-doc="privacy">Политикой обработки персональных данных</a></span></label>
        <label class="check"><input type="checkbox" name="consent_pd" ${me.terms_accepted ? "checked" : ""}><span>Даю <a href="#/legal/consent" data-doc="consent">согласие на обработку персональных данных</a></span></label>
      </div>
      <p class="error-text" hidden></p>
      <button class="btn block">Дальше</button>
    </form>`, { nav: false });
  const birthInput = $("input[name=birth]", root);
  birthInput.addEventListener("input", () => ($("[data-age-text]", root).textContent = ageConsentText(birthInput.value)));
  bindBack(root, STEP_BACK.about);
  $("form", root).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const err = $(".error-text", root);
    const fail = (m) => { err.textContent = m; err.hidden = false; };
    if (!f.name.value.trim()) return fail("Укажите имя");
    if (!f.birth.value) return fail("Укажите дату рождения");
    const age = ageOf(f.birth.value);
    if (age < 14) return fail("COFI доступен с 14 лет");
    if (!f.confirm_age.checked) return fail(age >= 18 ? "Подтвердите, что вам есть 18 лет" : "Нужно согласие родителя или законного представителя");
    if (!f.accept_terms.checked) return fail("Чтобы продолжить, примите Пользовательское соглашение и Правила");
    if (!f.consent_pd.checked) return fail("Чтобы продолжить, дайте согласие на обработку персональных данных");
    if (!state.me.birth_date && !(await confirmDialog(`Вам ${age} ${plural(age, "год", "года", "лет")}? Дату рождения потом нельзя будет изменить самостоятельно`, "Да, всё верно"))) return;
    try {
      const data = { name: f.name.value, confirm_age: true, accept_terms: true, consent_pd: true };
      if (!state.me.birth_date) data.birth_date = f.birth.value;
      state.me = await api.put("/api/profile", data);
      nextStep();
    } catch (ex) { fail(ex.message); }
  };
}

/** Шаг 2: пол, сексуальность (с 18 лет), кого ищу и пара слов о себе. Варианты уже по возрасту. */
function stepIdentity() {
  const me = state.me;
  const pick = identityPick(me);
  const root = screen(`${stepsBar("identity")}
    <form class="stack">
      <h1>О себе</h1>
      ${me.age_group === "teen" ? `<p class="muted">Вам доступна лента «Дружба»: здесь ищут друзей и компанию по интересам.</p>` : ""}
      <div class="stack" data-identity></div>
      <div class="field"><span>${me.age_group === "teen" ? "С кем хочу дружить" : "Кого ищу"}</span>${choiceGroup("looking_for", state.config.looking_for, me.looking_for)}</div>
      <label class="field"><span>Коротко о себе</span><textarea class="input" name="bio" maxlength="500" placeholder="Например: варю фильтр-кофе, по субботам бегаю в парке">${esc(me.bio)}</textarea></label>
      <p class="error-text" hidden></p>
      <button class="btn block">Дальше</button>
    </form>`, { nav: false });
  identityFields($("[data-identity]", root), pick, me.age);
  bindBack(root, STEP_BACK.identity);
  bindChoice(root, "looking_for", (v) => (pick.looking_for = v));
  $("form", root).onsubmit = async (e) => {
    e.preventDefault();
    const err = $(".error-text", root);
    if (!pick.gender || !pick.looking_for) { err.textContent = "Выберите пол и кого ищете"; err.hidden = false; return; }
    try {
      state.me = await api.put("/api/profile", { bio: e.target.bio.value, ...pick });
      nextStep();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
}

/** Опрос: по вопросу на экран, можно выбирать несколько вариантов. */
function renderSurvey({ editing = false, fromEnd = false } = {}) {
  const survey = state.config.survey;
  const answers = { goals: new Set(state.me.goals), interests: new Set(state.me.interests) };
  let i = fromEnd ? survey.length - 1 : 0;

  const draw = () => {
    let q = survey[i];
    if (q.key === "goals" && state.me.age_group === "teen") {
      q = { ...q, options: state.config.teen_goals, hint: "До 18 лет COFI только для дружбы" };
    }
    const set = q.key === "goals" ? answers.goals : answers.interests;
    const last = i === survey.length - 1;
    const root = screen(`${editing ? "" : stepsBar("survey")}
      <div class="stack" style="gap:18px">
        <div class="survey-head"><span class="muted small">${editing ? "Интересы" : "Пара вопросов о вас"}</span><span class="survey-count">${i + 1}/${survey.length}</span></div>
        <h1>${esc(q.title)}</h1>
        ${q.hint ? `<p class="muted">${esc(q.hint)}</p>` : ""}
        ${q.key !== "goals" ? `<p class="hint">Если ваших интересов здесь нет, напишите их в описании анкеты</p>` : ""}
        <div class="chips">${q.options.map((o, k) => `<button type="button" class="chip" style="--i:${k}" aria-pressed="${set.has(o)}">${esc(o)}</button>`).join("")}</div>
        <p class="error-text" hidden></p>
        <div class="row" style="margin-top:8px">
          ${i > 0 ? `<button class="btn ghost" data-back>Назад</button>` : editing ? `<a class="btn ghost" href="#/settings">Отмена</a>` : ""}
          <button class="btn" data-next style="flex:1">${last ? "Готово" : "Дальше"}</button>
        </div>
        ${!last && q.key !== "goals" ? `<button class="link" data-skip style="align-self:center">Пропустить вопрос</button>` : ""}
      </div>`, { nav: false });
    $$(".chips .chip", root).forEach((b) => (b.onclick = () => {
      const v = b.textContent;
      set.has(v) ? set.delete(v) : set.add(v);
      b.setAttribute("aria-pressed", String(set.has(v)));
    }));
    const err = $(".error-text", root);
    const fail = (m) => { err.textContent = m; err.hidden = false; };
    $("[data-back]", root)?.addEventListener("click", () => { i--; draw(); });
    bindBack(root, () => (i > 0 ? (i--, draw()) : STEP_BACK.survey()));
    $("[data-skip]", root)?.addEventListener("click", () => { i++; draw(); });
    $("[data-next]", root).onclick = async () => {
      if (q.key === "goals" && !answers.goals.size) return fail("Выберите хотя бы один вариант");
      if (!last) { i++; return draw(); }
      if (answers.interests.size < state.config.min_interests) {
        return fail(`Отметьте ещё ${state.config.min_interests - answers.interests.size}, чтобы мы могли подбирать пары`);
      }
      try {
        state.me = await api.put("/api/profile", { goals: [...answers.goals], interests: [...answers.interests] });
        if (editing) { toast("Интересы сохранены"); go("#/settings"); } else nextStep();
      } catch (ex) { fail(ex.message); }
    };
    window.scrollTo(0, 0);
  };
  draw();
}

function photoPicker(root, onUploaded) {
  const drop = $(".photo-drop", root);
  const input = $("input[type=file]", root);
  const err = $(".error-text", root);
  const upload = async (file) => {
    if (!file) return;
    drop.style.backgroundImage = `url(${URL.createObjectURL(file)})`;
    drop.classList.add("has");
    drop.innerHTML = `<div class="skeleton"></div>`;
    err.hidden = true;
    const fd = new FormData();
    fd.append("file", await shrinkImage(file));
    try {
      await api.post("/api/profile/photo", fd);
      drop.innerHTML = "";
      onUploaded();
    } catch (ex) {
      drop.innerHTML = "";
      err.textContent = ex.message;
      err.hidden = false;
    }
  };
  drop.onclick = () => input.click();
  drop.onkeydown = (e) => (e.key === "Enter" || e.key === " ") && input.click();
  input.onchange = () => { upload(input.files[0]); input.value = ""; };
  $("[data-camera]", root).onclick = async () => upload(await takePhoto());
}

function stepPhoto() {
  const root = screen(`${stepsBar("photo")}
    <div class="stack">
      <h1>Ваше фото</h1>
      <p class="muted">Нужно фото, где хорошо видно лицо, и только ваше. Следующим шагом сверим его с камерой.</p>
      <div class="photo-drop" role="button" tabindex="0"><div>${icons.image}Загрузить из галереи</div></div>
      <button type="button" class="btn ghost block" data-camera>${icons.camera} Сделать фото сейчас</button>
      <input type="file" accept="image/*" hidden>
      <p class="error-text" hidden></p>
    </div>`, { nav: false });
  bindBack(root, STEP_BACK.photo);
  photoPicker(root, nextStep);
}

function stepScan() {
  const root = screen(`${stepsBar("scan")}
    <div class="stack">
      <h1>Проверка, что это вы</h1>
      <p class="muted">Камера покажет овал. Держите лицо в нём и следуйте подсказкам: смотрите прямо, затем поверните голову влево и вправо. Это защищает от чужих фото.</p>
      <div class="profile-hero"><img src="${esc(state.me.photo_url)}" alt="Ваше фото"><p class="small muted">Сверяем с этим фото</p></div>
      <div id="scan-area"></div>
      ${state.me.consent_bio ? `<p class="small muted">${icons.check} Вы уже дали <a href="#/legal/biometric" data-doc="biometric">согласие на обработку биометрических данных</a> при первой попытке, повторно отмечать не нужно. Отозвать: письмо на craftycat119@mail.ru</p>` : `<label class="check consent" data-bio><input type="checkbox" name="consent_bio"><span>Даю <a href="#/legal/biometric" data-doc="biometric">согласие на обработку биометрических персональных данных</a> (изображение лица) для проверки фото и ручной проверки при жалобах</span></label>`}
      <p class="error-text" id="scan-error" hidden></p>
      <button class="btn block" id="start">${icons.shield} Начать проверку</button>
      <button class="btn ghost block" id="change">Выбрать другое фото</button>
      <input type="file" accept="image/*" hidden>
    </div>`, { nav: false });
  bindBack(root, STEP_BACK.scan);
  const startBtn = $("#start", root);
  const err = $("#scan-error", root);
  startBtn.onclick = async () => {
    const bio = $("[name=consent_bio]", root);
    if (bio && !bio.checked) { err.textContent = "Для проверки нужно согласие на обработку биометрических данных"; err.hidden = false; return; }
    if (bio) $("[data-bio]", root).hidden = true;
    startBtn.hidden = true;
    err.hidden = true;
    $(".profile-hero", root).hidden = true;
    const res = await runScanner($("#scan-area", root), { consent: true });
    if (res.ok) {
      toast("Фото подтверждено");
      return nextStep();
    }
    err.textContent = res.reason || "Проверка не пройдена";
    err.hidden = false;
    startBtn.hidden = false;
    startBtn.innerHTML = `${icons.shield} Попробовать ещё раз`;
  };
  const input = $("input[type=file]", root);
  $("#change", root).onclick = () => input.click();
  input.onchange = async () => {
    const fd = new FormData();
    fd.append("file", input.files[0]);
    try {
      await api.post("/api/profile/photo", fd);
      nextStep();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
}

function getPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("Браузер не поддерживает геопозицию"));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      (e) => reject(new Error(e.code === 1
        ? "Доступ к геопозиции запрещён. Разрешите его для этого сайта в настройках браузера."
        : "Не удалось определить местоположение. Проверьте, включена ли геолокация.")),
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 },
    );
  });
}

function stepLocation() {
  const root = screen(`${stepsBar("location")}
    <div class="stack">
      <h1>Люди рядом</h1>
      <p class="muted">Мы показываем тех, кто недалеко от вас. Другие видят только расстояние в километрах, точный адрес никто не узнает.</p>
      <p class="error-text" hidden></p>
      <button class="btn block">${icons.pin} Разрешить геопозицию</button>
    </div>`, { nav: false });
  bindBack(root, STEP_BACK.location);
  const btn = $(".btn.block", root);
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      await api.post("/api/profile/location", await getPosition());
      nextStep();
    } catch (ex) {
      const err = $(".error-text", root);
      err.textContent = ex.message;
      err.hidden = false;
    } finally { btn.disabled = false; }
  };
}

async function refreshLocationSilently() {
  try {
    const perm = await navigator.permissions?.query({ name: "geolocation" });
    if (perm?.state !== "granted") return;
    await api.post("/api/profile/location", await getPosition());
  } catch { /* тихо */ }
}

// ---------------- Лента «Нити» ----------------

function plural(n, one, few, many) {
  const a = n % 10, b = n % 100;
  if (a === 1 && b !== 11) return one;
  if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
  return many;
}

const kmText = (km) => (km == null ? "" : km < 1 ? "меньше 1 км от вас" : `${Math.round(km)} км от вас`);

async function renderFeed() {
  const root = screen(`
    <div class="topbar"><span class="row" style="gap:8px"><span class="logo">cofi<span>°</span></span>${state.me.is_demo ? '<span class="demo-pill">демо</span>' : ""}</span><span class="counter"></span></div>
    ${feedTabs("people", state.me)}
    <div class="deck" aria-live="polite"><div class="skeleton" style="position:relative;height:420px"></div></div>
    <p class="swipe-hint" hidden>Свайп по нитке вниз: нравится, вверх: дальше. Нажмите на фото, чтобы открыть анкету</p>
    <div class="btns" hidden>
      <div class="bw undo-wrap"><button class="undo" aria-label="Вернуть" disabled>${icons.undo}</button><span class="undo-label">Вернуть</span></div>
      <div class="bw"><button class="skip" aria-label="Дальше">${icons.x}</button><span>Дальше</span></div>
      <div class="bw"><button class="like" aria-label="${teenLike()}">${icons.heart}</button><span>${teenLike()}</span></div>
    </div>`, { cls: "feed" });
  const deck = $(".deck", root);
  const btns = $(".btns", root);
  if (state.me.is_admin && !state.me.is_complete) return adminHome(root);
  const hint = $(".swipe-hint", root);
  const counter = $(".counter", root);
  let cards = [], total = 0, seen = 0, busy = false, loading = false, thread = null;
  const history = []; // последние решения, чтобы вернуть случайно пролистанную анкету или отменить лайк
  const undoBtn = () => $(".undo", btns);
  const syncUndo = () => {
    const last = history[history.length - 1];
    undoBtn().disabled = !last || busy;
    $(".undo-label", btns).textContent = last?.like ? "Отменить лайк" : "Вернуть";
  };

  const empty = (title, text, btnLabel, fn) => {
    btns.hidden = hint.hidden = true;
    counter.textContent = "";
    deck.replaceChildren(h(`<div class="empty"><h1>${title}</h1><p class="lead">${text}</p>${btnLabel ? `<button class="btn">${btnLabel}</button>` : ""}</div>`));
    if (fn) $(".btn", deck).onclick = fn;
    if (history.length) {
      const back = h(`<button class="btn ghost">${icons.undo} Вернуть последнюю анкету</button>`);
      back.onclick = undo;
      $(".empty", deck).append(back);
    }
  };

  let skipped = 0, restarting = false;
  async function load() {
    if (loading) return;
    loading = true;
    try {
      const res = await api.get("/api/feed?limit=10");
      total = seen + res.total;
      skipped = res.skipped || 0;
      const known = new Set(cards.map((c) => c.id));
      cards.push(...res.cards.filter((c) => !known.has(c.id)));
      if (!thread) draw();
    } catch (ex) {
      if (ex.code === "need_location") {
        empty("Нужна геопозиция", "Без неё не получится найти людей рядом.", "Разрешить", async () => {
          try { await api.post("/api/profile/location", await getPosition()); renderFeed(); } catch (e) { toast(e.message, { error: true }); }
        });
      } else empty("Лента не загрузилась", ex.message, "Повторить", renderFeed);
    } finally { loading = false; }
  }

  function draw() {
    const c = cards[0];
    if (!c) {
      thread = null;
      if (skipped && !restarting) {
        // анкеты закончились — сами идём на второй круг: пропущенные показываются снова (лайкнутые — нет, они ждут ответа)
        restarting = true;
        api.post("/api/feed/restart").then(() => {
          skipped = 0;
          toast("Новые анкеты закончились — показываем всех по второму кругу", { timeout: 5000 });
          return load();
        }).catch((ex) => toast(ex.message, { error: true })).finally(() => (restarting = false));
        deck.replaceChildren(h(`<div class="empty"><p class="lead">Начинаем второй круг…</p></div>`));
        return;
      }
      return state.me.max_distance_km >= 7000
        ? empty("Пока никого", "Новых анкет пока нет. Загляните позже: люди регистрируются каждый день.", "Открыть профиль", () => go("#/settings"))
        : empty("Рядом пока никого", `В радиусе ${fmtKm(state.me.max_distance_km)} км новых анкет нет. Увеличьте радиус в профиле или добавьте интересов.`, "Открыть профиль", () => go("#/settings"));
    }
    btns.hidden = hint.hidden = false;
    counter.textContent = `${seen + 1} из ${Math.max(total, seen + 1)} рядом`;
    deck.replaceChildren(h(`<div>
      <article class="person enter">
        <button class="ava" aria-label="Открыть анкету: ${esc(c.name)}">
          ${c.photo_url ? `<img src="${esc(c.photo_url)}" alt="">` : esc(c.name.charAt(0))}
          ${c.photos_count ? `<span class="more">+${c.photos_count} фото</span>` : ""}
        </button>
        <div class="pname" translate="no">${esc(c.name)}<span>, ${c.age}</span></div>
        <div class="meta">${[c.city ? esc(c.city) : "", kmText(c.distance_km), c.verified ? "фото подтверждено" : ""].filter(Boolean).join(" · ")}</div>
        ${c.liked_before ? `<span class="liked-before">${icons.heart} Вы уже лайкали — ждём ответа</span>` : ""}
        ${c.bio ? `<p class="pbio" translate="no">${esc(c.bio)}</p>` : ""}
      </article>
      <div class="shared-lbl">${c.common.length
        ? `У вас общего: <b>${c.common.length} ${plural(c.common.length, "интерес", "интереса", "интересов")}</b> · совпадение ${c.match}%`
        : "Общих интересов пока нет, но можно познакомиться"}</div>
      <div class="thread"></div>
    </div>`));
    $(".ava", deck).onclick = () => { if (!swiped) openProfile(c.id, { onDecide: decide }); };
    thread = mountThread($(".thread", deck), c.common.slice(0, 5));
  }

  async function decide(like, { silent = false } = {}) {
    const c = cards[0];
    if (!c || busy || !thread) return;
    if (silent) { cards.shift(); thread = null; draw(); if (cards.length < 3) load(); return; } // заблокировали из анкеты
    busy = true;
    $$("button", btns).forEach((b) => (b.disabled = true));
    navigator.vibrate?.(like ? 12 : 6);
    const request = api.post("/api/feed/swipe", { user_id: c.id, like }).catch((ex) => { toast(ex.message, { error: true }); return {}; });
    const [res] = await Promise.all([request, thread.play(like ? "like" : "skip")]);
    if (res.match) showMatch({ conversation_id: res.conversation_id, user: res.user, common: res.user.common });
    cards.shift();
    seen++;
    if (!res.match) history.push({ id: c.id, like });
    if (history.length > 20) history.shift();
    busy = false;
    $$("button", btns).forEach((b) => (b.disabled = false));
    syncUndo();
    thread = null;
    draw();
    if (cards.length < 3) load();
  }

  async function undo() {
    const last = history.pop();
    if (!last || busy) return;
    try {
      const r = await api.post("/api/feed/undo", { user_id: last.id });
      cards.unshift(r.card);
      seen = Math.max(0, seen - 1);
      toast(r.undone === "like" ? "Лайк отменён" : "Анкета возвращена");
      thread = null;
      draw();
    } catch (ex) {
      toast(ex.message, { error: true });
    }
    syncUndo();
  }
  undoBtn().onclick = undo;

  $(".skip", btns).onclick = () => decide(false);
  $(".like", btns).onclick = () => decide(true);

  // Свайп по нитке с интересами: вниз — нравится, вверх — дальше.
  // Остальная часть экрана (и фото) прокручивается пальцем как обычно и на анкету не отвечает.
  let g = null, swiped = false;
  const glow = (v) => (v > 30 ? "0 0 0 6px rgba(242, 98, 31, .55)" : v < -30 ? "0 0 0 6px rgba(243, 233, 223, .25)" : "");
  const resetG = () => {
    if (!g) return;
    g.el.style.transition = g.el.style.transform = g.el.style.opacity = "";
    g.el.classList.remove("dragging");
    const ava = $(".ava", deck);
    if (ava) ava.style.boxShadow = "";
    g = null;
  };
  deck.addEventListener("pointerdown", (e) => {
    if (busy || e.button > 0) return;
    const el = e.target.closest(".thread");
    if (!el) return;
    g = { el, y0: e.clientY, id: e.pointerId };
    swiped = false;
    el.setPointerCapture(e.pointerId);
    el.classList.add("dragging");
  });
  deck.addEventListener("pointermove", (e) => {
    if (!g || e.pointerId !== g.id) return;
    const v = Math.max(-90, Math.min(90, e.clientY - g.y0));
    if (Math.abs(v) > 6) swiped = true;
    const ava = $(".ava", deck);
    g.el.style.transition = "none";
    g.el.style.transform = `translateY(${v * 0.5}px)`;
    g.el.style.opacity = String(1 - Math.abs(v) / 300);
    if (ava) ava.style.boxShadow = glow(v);
  });
  const endSwipe = (e) => {
    if (!g || e.pointerId !== g.id) return;
    const d = e.clientY - g.y0;
    resetG();
    if (d > 70) decide(true);
    else if (d < -70) decide(false);
    setTimeout(() => (swiped = false), 50); // чтобы свайп не открыл анкету как нажатие
  };
  deck.addEventListener("pointerup", endSwipe);
  deck.addEventListener("pointercancel", resetG);
  const keys = (e) => {
    if (!document.body.contains(deck)) return document.removeEventListener("keydown", keys);
    if (e.target.closest("input, textarea") || $(".profile-view")) return;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") decide(true);
    if (e.key === "ArrowUp" || e.key === "ArrowLeft") decide(false);
  };
  document.addEventListener("keydown", keys);
  load();
}

// ---------------- Подробная анкета ----------------

/** «Парень · Би · 182 см · 76 кг · Лев» — только то, что человек указал и разрешил показывать. */
function aboutLine(p) {
  const zodiac = p.zodiac ? `${ZODIAC_SIGNS[p.zodiac] || ""} ${esc(p.zodiac_label || "")}`.trim() : "";
  return [p.gender_label, p.orientation_label].filter(Boolean).map(esc)
    .concat(p.height_cm ? [`${p.height_cm} см`] : [], p.weight_kg ? [`${p.weight_kg} кг`] : [], zodiac ? [zodiac] : [])
    .join(" · ");
}

/** Чёрный список: человек больше не сможет писать, вы пропадёте из ленты и чатов друг друга. */
async function blockUser(user) {
  if (!(await confirmDialog(`Заблокировать ${user.name}? Он(а) больше не сможет вам писать, вы пропадёте из ленты и чатов друг друга. Разблокировать можно в профиле`, "Заблокировать"))) return false;
  try {
    await api.post(`/api/users/${user.id}/block`);
    toast(`${user.name} в чёрном списке`);
    return true;
  } catch (ex) { toast(ex.message, { error: true }); return false; }
}

async function openProfile(userId, { onDecide = null, preview = false, onCancelLike = null } = {}) {
  let p;
  try {
    p = await api.get(preview ? "/api/profile/preview" : `/api/users/${userId}`);
  } catch (ex) {
    return toast(ex.message, { error: true });
  }
  const goalsSet = new Set(p.common);
  const el = h(`<section class="profile-view" role="dialog" aria-label="Анкета: ${esc(p.name)}">
    <div class="gallery">
      <div class="track">${p.photos.map((u, i) => `<img src="${esc(u)}" alt="Фото ${i + 1}" loading="${i ? "lazy" : "eager"}">`).join("")}</div>
      ${p.photos.length > 1 ? `<div class="dots">${p.photos.map((_, i) => `<i class="${i ? "" : "on"}"></i>`).join("")}</div>` : ""}
    </div>
    <button class="icon-btn close" aria-label="Закрыть">${icons.back}</button>
    ${preview ? `<div class="preview-pill">${icons.user} Так вашу анкету видят другие</div>` : ""}
    <div class="profile-body">
      <div class="pname" translate="no">${esc(p.name)}<span>, ${p.age}</span></div>
      <div class="meta muted small" style="margin-top:6px">${[p.city ? `${icons.pin} ${esc(p.city)}` : "", kmText(p.distance_km), p.verified ? "фото подтверждено" : "", p.online ? "в сети" : ""].filter(Boolean).join(" · ")}</div>
      ${aboutLine(p) ? `<p class="about-line">${aboutLine(p)}</p>` : ""}
      <div class="match-strip">
        <div><b>${preview ? "?" : `${p.match}%`}</b><span>${preview ? "совпадение у каждого своё" : "совпадение"}</span></div>
        ${preview ? `<div><b>${p.interests.length}</b><span>${plural(p.interests.length, "интерес", "интереса", "интересов")}</span></div>` : `<div><b>${p.common.length}</b><span>${plural(p.common.length, "общий интерес", "общих интереса", "общих интересов")}</span></div>`}
        <div><b>${p.photos.length}</b><span>${plural(p.photos.length, "фото", "фото", "фото")}</span></div>
      </div>
      ${p.bio ? `<h3>О себе</h3><p style="font-size:16px;line-height:1.5" translate="no">${esc(p.bio)}</p>` : ""}
      ${p.goals.length ? `<h3>Ищет</h3><div class="chips">${p.goals.map((g) => `<span class="chip static ghost">${esc(g)}</span>`).join("")}</div>` : ""}
      <h3>Интересы</h3>
      <div class="chips">${p.interests.map((x) => `<span class="chip static ${goalsSet.has(x) ? "hot" : "ghost"}">${esc(x)}</span>`).join("")}</div>
      ${preview ? "" : `<div class="profile-links">
        <button class="link report" data-report>${icons.flag} Пожаловаться</button>
        <button class="link report" data-block>${icons.block} Заблокировать</button>
      </div>`}
    </div>
    <div class="profile-actions"></div>
  </section>`);

  const actions = $(".profile-actions", el);
  const close = () => { el.remove(); document.removeEventListener("keydown", esc_); };
  $("[data-report]", el)?.addEventListener("click", () => { close(); reportUser(p, go); });
  $("[data-block]", el)?.addEventListener("click", async () => { if (await blockUser(p)) { close(); onDecide?.(false, { silent: true }); } });
  const esc_ = (e) => e.key === "Escape" && close();
  if (preview) {
    actions.innerHTML = `<p class="note">Совпадение и расстояние каждый видит своё. Фото, текст и интересы — как здесь</p>
      <button class="btn block" data-edit>${icons.check} Понятно</button>`;
    $("[data-edit]", actions).onclick = () => close();
  } else if (p.conversation_id) {
    actions.innerHTML = `<button class="btn block" data-write>${icons.chat} Написать сообщение</button>`;
    $("[data-write]", actions).onclick = () => { close(); go(`#/chat/${p.conversation_id}`); };
  } else if (onDecide) {
    actions.innerHTML = `<div class="btns">
      <div class="bw"><button class="skip" aria-label="Дальше">${icons.x}</button><span>Дальше</span></div>
      <div class="bw"><button class="like" aria-label="Нравится">${icons.heart}</button><span>Нравится</span></div></div>
      <p class="note">Написать можно после взаимной симпатии</p>`;
    $(".skip", actions).onclick = () => { close(); onDecide(false); };
    $(".like", actions).onclick = () => { close(); onDecide(true); };
  } else {
    actions.innerHTML = `<p class="note">${p.liked ? "Вы отметили симпатию. Чат откроется, когда она станет взаимной" : "Написать можно после взаимной симпатии"}</p>
      ${p.liked && onCancelLike ? `<button class="btn ghost block" data-unlike>${icons.x} Отменить симпатию</button>` : ""}`;
    $("[data-unlike]", actions)?.addEventListener("click", async () => {
      if (!(await confirmDialog(`Отменить симпатию к ${p.name}?`, "Отменить"))) return;
      try { await api.post("/api/feed/undo", { user_id: p.id }); close(); onCancelLike(); } catch (ex) { toast(ex.message, { error: true }); }
    });
  }

  const track = $(".track", el);
  const dots = $$(".dots i", el);
  track.addEventListener("scroll", () => {
    const i = Math.round(track.scrollLeft / track.clientWidth);
    dots.forEach((d, k) => d.classList.toggle("on", k === i));
  }, { passive: true });
  // тап по левой/правой половине фото листает, как в сторис
  track.addEventListener("click", (e) => {
    const right = e.clientX > track.getBoundingClientRect().left + track.clientWidth / 2;
    track.scrollBy({ left: right ? track.clientWidth : -track.clientWidth, behavior: "smooth" });
  });
  $(".close", el).onclick = close;
  document.addEventListener("keydown", esc_);
  document.body.append(el);
  $(".close", el).focus();
}

const isTeen = () => state.me?.age_group === "teen";
const teenLike = () => (isTeen() ? "Дружить" : "Нравится");

function showMatch({ conversation_id, user, common = [] }) {
  if (state.shownMatches.has(conversation_id)) return;
  state.shownMatches.add(conversation_id);
  const el = h(`<div class="overlay match" role="dialog" aria-label="Взаимная симпатия">
    <div class="match-modal">
      <div class="heart-stage" aria-hidden="true"></div>
      <h1 class="match-title">${isTeen() ? "Новый друг" : "Взаимно"}</h1>
      <div class="pair"><img src="${esc(state.me.photo_url)}" alt="Вы"><img src="${esc(user.photo_url)}" alt="${esc(user.name)}"></div>
      <p>${isTeen() ? `Вы и ${esc(user.name)} хотите дружить.` : `Вы и ${esc(user.name)} понравились друг другу.`}${common.length ? " У вас общее:" : ""}</p>
      ${common.length ? `<div class="chips">${common.slice(0, 6).map((x) => `<span class="chip static">${esc(x)}</span>`).join("")}</div>` : ""}
      <button class="btn dark block" data-chat>Написать сообщение</button>
      <button class="btn ghost block" data-close>Смотреть дальше</button>
    </div></div>`);
  document.body.append(el);
  mount3d($(".heart-stage", el), isTeen() ? "knot" : "heart");
  navigator.vibrate?.([20, 60, 30]);
  $("[data-chat]", el).onclick = () => { el.remove(); go(`#/chat/${conversation_id}`); };
  $("[data-close]", el).onclick = () => el.remove();
}

// ---------------- Чаты ----------------

function previewText(m, meId) {
  if (!m) return t("Новая пара, напишите первым");
  const mine = m.sender_id === meId ? t("Вы:") + " " : "";
  const map = { image: "Фото", video: "Видео", voice: "Голосовое", circle: "Видеосообщение", call: m.text === "video" ? "Видеозвонок" : "Звонок" };
  return mine + (m.kind === "text" || m.kind === "sticker" ? m.text : t(map[m.kind] || ""));
}

/** Подключить уведомления в Telegram к аккаунту, созданному по почте. */
async function linkTelegram() {
  try {
    const { url } = await api.post("/api/profile/telegram-link");
    if (tgApp()?.initData !== undefined && tgApp()?.platform && tgApp().platform !== "unknown") tgApp().openTelegramLink(url);
    else if (!window.open(url, "_blank")) location.href = url; // браузер заблокировал новое окно
    toast("Нажмите «Запустить» в боте, и уведомления подключатся", { timeout: 6000 });
  } catch (ex) { toast(ex.message, { error: true }); }
}

/** Почтой приходят только коды, поэтому без Telegram человек не узнает о сообщениях и звонках. */
function telegramNudge() {
  if (state.me.telegram_linked || state.me.is_demo || !state.config.telegram_bot_username) return "";
  return `<div class="tg-nudge">${icons.send}<div><b>Подключите Telegram</b><span>${state.config.calls_enabled ? "В Telegram будут приходить сообщения и пропущенные звонки. На почту — только коды входа" : "В Telegram будут приходить новые сообщения и пары. На почту — только коды входа"}</span></div>
    <button class="btn tg" data-tg-link>Подключить</button></div>`;
}

async function renderChats() {
  const root = screen(`<h1>Чаты</h1>${telegramNudge()}<div id="chats"></div>`);
  $("[data-tg-link]", root)?.addEventListener("click", linkTelegram);
  let chats = [];
  try { chats = await api.get("/api/chats"); } catch (ex) { toast(ex.message, { error: true }); }
  state.unread = chats.reduce((s, c) => s + c.unread, 0);
  updateNavBadge();
  const box = $("#chats", root);
  if (!chats.length) {
    box.replaceChildren(h(`<div class="empty"><h2>Пока без пар</h2><p class="muted">Когда симпатия окажется взаимной, здесь появится чат.</p><a class="btn" href="#/feed">Смотреть анкеты</a></div>`));
    return;
  }
  const fresh = chats.filter((c) => !c.last_message);
  const talks = chats.filter((c) => c.last_message);
  box.replaceChildren(h(`<div>
    ${fresh.length ? `<div class="new-matches" aria-label="Новые пары">${fresh.map((c) =>
      `<a href="#/chat/${c.id}"><img src="${esc(c.user.photo_url)}" alt="">${esc(c.user.name)}</a>`).join("")}</div>` : ""}
    <div class="chat-list">${talks.map((c) => `
      <a class="chat-item" href="#/chat/${c.id}">
        <span class="avatar-wrap"><img class="avatar" src="${esc(c.user.photo_url)}" alt="">${c.user.online ? '<i class="dot" title="В сети"></i>' : ""}</span>
        <span class="body">
          <span class="top"><b translate="no">${esc(c.user.name)}</b><span class="time">${fmtShort(c.last_message.created_at)}</span></span>
          <span class="row" style="gap:8px"><span class="preview" style="flex:1" translate="no">${esc(previewText(c.last_message, state.me.id))}</span>${c.unread ? `<span class="unread">${c.unread}</span>` : ""}</span>
        </span>
      </a>`).join("")}</div></div>`));
}

// ---------------- Отклики ----------------

async function renderLikes() {
  const root = screen(`<h1>Отклики</h1><div id="likes"><div class="spinner"></div></div>`);
  let data;
  try { data = await api.get("/api/feed/likes"); } catch (ex) {
    $("#likes", root).innerHTML = `<p class="muted">${esc(ex.message)}</p>`;
    return;
  }
  const row = (p, kind) => `
    <button class="like-item" data-kind="${kind}" data-id="${p.id}" data-conv="${p.conversation_id || ""}">
      <img class="avatar" src="${esc(p.photo_url || "")}" alt="">
      <span class="body"><b translate="no">${esc(p.name)}, ${p.age}</b><span class="muted small">${[p.city ? esc(p.city) : "", p.verified ? "фото подтверждено" : ""].filter(Boolean).join(" · ")}</span></span>
      <span class="act">${kind === "mutual" ? icons.chat : kind === "received" ? icons.heart : ""}</span>
    </button>`;
  const section = (kind, title, hint, list, empty) => `
    <section class="likes-section">
      <h2>${title} <span class="count">${list.length}</span></h2>
      ${hint ? `<p class="hint">${hint}</p>` : ""}
      ${list.length ? `<div class="like-list">${list.map((p) => row(p, kind)).join("")}</div>` : `<p class="muted small empty-line">${empty}</p>`}
    </section>`;
  $("#likes", root).innerHTML =
    section("mutual", "Взаимные", "", data.mutual, "Пока нет. Когда симпатия совпадёт, человек появится здесь — и можно писать") +
    section("sent", "Вы лайкнули", "Написать можно, когда симпатия станет взаимной", data.sent, "Вы ещё никого не лайкнули") +
    section("received", "Вас лайкнули", "Ответьте взаимностью — и откроется чат", data.received, "Пока никто — но всё впереди");
  $$(".like-item", root).forEach((b) => (b.onclick = () => {
    const id = Number(b.dataset.id);
    if (b.dataset.kind === "mutual") return go(`#/chat/${b.dataset.conv}`);
    if (b.dataset.kind === "sent") return openProfile(id, { onCancelLike: () => { toast("Симпатия отменена"); renderLikes(); } });
    openProfile(id, {
      onDecide: async (like) => {
        try {
          const r = await api.post("/api/feed/swipe", { user_id: id, like });
          if (r.match && r.conversation_id) { toast("Это взаимно! Можно писать"); return go(`#/chat/${r.conversation_id}`); }
          renderLikes();
        } catch (ex) { toast(ex.message, { error: true }); }
      },
    });
  }));
}

let chatCleanup = null;

function closeChat() {
  chatCleanup?.();
  chatCleanup = null;
  state.openChat = null;
}

async function openChat(convId) {
  let data;
  try {
    data = await api.get(`/api/chats/${convId}`);
  } catch (ex) {
    toast(ex.message, { error: true });
    return go("#/chats");
  }
  state.openChat = convId;
  const other = data.user;
  const el = h(`<section class="chat-screen" aria-label="Чат с ${esc(other.name)}">
    <header class="chat-header">
      <a class="icon-btn" href="#/chats" aria-label="Назад">${icons.back}</a>
      <button class="who-link" data-profile aria-label="Открыть анкету">
        <img class="avatar" src="${esc(other.photo_url)}" alt="">
        <span class="who"><b translate="no">${esc(other.name)}${other.age ? `, ${other.age}` : ""}</b><small class="status">${other.online ? "в сети" : "не в сети"}</small></span>
      </button>
      ${state.config.calls_enabled ? `<button class="icon-btn" data-call="audio" aria-label="Аудиозвонок">${icons.phone}</button>
      <button class="icon-btn" data-call="video" aria-label="Видеозвонок">${icons.video}</button>` : ""}
      <button class="icon-btn" data-menu aria-label="Ещё">${icons.more}</button>
    </header>
    <button class="pinned-bar" data-pinned hidden><span class="pin-ico">${icons.pushPin}</span><span class="pin-body"><b>Закреплено</b><span class="pin-text"></span></span><span class="pin-x" data-unpin aria-label="Открепить">${icons.x}</span></button>
    <div class="messages" tabindex="0" translate="no"></div>
    <div class="typing" aria-live="polite"></div>
    <div class="upload-status" aria-live="polite" hidden><span></span><i><b></b></i>
      <button class="icon-btn" data-cancel-all aria-label="Отменить загрузку">${icons.x}</button></div>
    <div class="sticker-panel" hidden></div>
    <div class="reply-bar" hidden><span class="rb-ico"></span><span class="rb-body"><b></b><span class="rb-text"></span></span><button class="icon-btn" data-rb-close aria-label="Отменить">${icons.x}</button></div>
    <div class="composer"></div>
    <input type="file" accept="image/*,video/*" multiple hidden>
    <input type="file" accept="video/*" capture="environment" hidden data-video-capture>
  </section>`);
  document.body.append(el);
  const list = $(".messages", el);
  const typing = $(".typing", el);
  const composer = $(".composer", el);
  const stickerPanel = $(".sticker-panel", el);
  const fileInput = $("input[type=file]", el);
  const seen = new Set();
  let lastDay = null;
  const pendingBox = h(`<div class="pending-box"></div>`);

  const atBottom = () => list.scrollHeight - list.scrollTop - list.clientHeight < 120;
  const scrollDown = () => (list.scrollTop = list.scrollHeight);

  function append(m) {
    if (seen.has(m.id)) return;
    seen.add(m.id);
    const day = fmtDay(m.created_at);
    // новые сообщения встают перед плитками ещё не отправленных файлов
    const put = (node) => (pendingBox.isConnected ? pendingBox.before(node) : list.append(node));
    if (day !== lastDay) {
      put(h(`<div class="day-sep">${day}</div>`));
      lastDay = day;
    }
    const stick = atBottom();
    put(decorate(messageEl(m, m.sender_id === state.me.id), m));
    if (stick || m.sender_id === state.me.id) scrollDown();
  }

  // ---- Ответ, изменение, закрепление (долгое нажатие на сообщение) ----
  const msgs = new Map(); // id → сообщение (для меню и правки)
  const who = (senderId) => (senderId === state.me.id ? "Вы" : other.name);
  function decorate(node, m) {
    msgs.set(m.id, m);
    node.dataset.mid = m.id;
    if (m.reply_to) {
      const q = h(`<button class="reply-quote" type="button"><b>${esc(who(m.reply_to.sender_id))}</b><span>${esc(m.reply_to.text || "Сообщение")}</span></button>`);
      q.onclick = (e) => { e.stopPropagation(); jumpTo(m.reply_to.id); };
      const bubble = $(".bubble", node);
      if (bubble) bubble.prepend(q); else node.prepend(q);
    }
    if (m.edited) $(".time", node)?.insertAdjacentHTML("afterbegin", '<span class="edited">изм. </span>');
    return node;
  }
  function replaceMessage(m) {
    const old = $(`[data-mid="${m.id}"]`, list);
    if (old) old.replaceWith(decorate(messageEl(m, m.sender_id === state.me.id), m));
    else msgs.set(m.id, m);
  }

  // Переход к сообщению (из цитаты или закрепа). Если оно старое и ещё не загружено — догружаем историю
  async function jumpTo(id) {
    let node = $(`[data-mid="${id}"]`, list);
    for (let guard = 0; !node && guard < 20; guard++) {
      const firstId = Math.min(...[...msgs.keys()]);
      if (!Number.isFinite(firstId)) break;
      const older = await api.get(`/api/chats/${convId}?before_id=${firstId}&limit=100`).catch(() => null);
      if (!older?.messages?.length) break;
      const frag = document.createDocumentFragment();
      let day = null;
      for (const m of older.messages) {
        if (seen.has(m.id)) continue;
        seen.add(m.id);
        const d = fmtDay(m.created_at);
        if (d !== day) { frag.append(h(`<div class="day-sep">${d}</div>`)); day = d; }
        frag.append(decorate(messageEl(m, m.sender_id === state.me.id), m));
      }
      list.prepend(frag);
      node = $(`[data-mid="${id}"]`, list);
    }
    if (!node) return toast("Сообщение не найдено — возможно, его удалили");
    node.scrollIntoView({ block: "center", behavior: "smooth" });
    node.classList.remove("flash");
    void node.offsetWidth;
    node.classList.add("flash");
  }

  // Закреплённое — плашка под шапкой
  const pinnedBar = $("[data-pinned]", el);
  let pinned = data.pinned || null;
  function drawPinned() {
    pinnedBar.hidden = !pinned;
    if (pinned) $(".pin-text", pinnedBar).textContent = pinned.text || "Сообщение";
  }
  pinnedBar.onclick = (e) => {
    if (e.target.closest("[data-unpin]")) return setPin(null);
    if (pinned) jumpTo(pinned.id);
  };
  async function setPin(messageId) {
    try {
      pinned = (await api.post(`/api/chats/${convId}/pin`, { message_id: messageId })).pinned;
      drawPinned();
      if (messageId) toast("Сообщение закреплено");
    } catch (ex) { toast(ex.message, { error: true }); }
  }
  drawPinned();

  // Ответ / правка — полоса над полем ввода
  let replyTo = null, editing = null;
  const replyBar = $(".reply-bar", el);
  function drawReplyBar() {
    const m = editing || replyTo;
    replyBar.hidden = !m;
    replyBar.classList.toggle("editing", !!editing);
    if (!m) return;
    $(".rb-ico", replyBar).innerHTML = editing ? icons.pencil : icons.reply;
    $(".rb-body b", replyBar).textContent = editing ? "Редактирование" : `Ответ: ${who(m.sender_id)}`;
    $(".rb-text", replyBar).textContent = m.kind === "text" || m.kind === "sticker" ? m.text : (m.text || "Вложение");
  }
  $("[data-rb-close]", replyBar).onclick = () => {
    if (editing) draft = "";
    replyTo = editing = null;
    drawReplyBar();
    drawComposer();
  };
  function startReply(m) {
    editing = null;
    replyTo = { id: m.id, sender_id: m.sender_id, kind: m.kind, text: m.kind === "text" || m.kind === "sticker" ? m.text : ({ image: "📷 Фото", video: "🎬 Видео", voice: "🎤 Голосовое", circle: "⭕ Кружок" }[m.kind] || "") };
    drawReplyBar();
    drawComposer();
    $("textarea", composer)?.focus();
  }
  function startEdit(m) {
    replyTo = null;
    editing = m;
    draft = m.text;
    drawReplyBar();
    drawComposer();
    const ta = $("textarea", composer);
    ta?.focus();
    ta?.setSelectionRange(ta.value.length, ta.value.length);
  }

  // Меню сообщения
  function openMsgMenu(m, y) {
    const mine = m.sender_id === state.me.id;
    const isPinned = pinned?.id === m.id;
    const menu = h(`<div class="msg-menu-overlay" role="dialog" aria-label="Действия с сообщением">
      <div class="msg-menu" role="menu">
        <button role="menuitem" data-a="reply">${icons.reply}<span>Ответить</span></button>
        ${mine && m.kind === "text" ? `<button role="menuitem" data-a="edit">${icons.pencil}<span>Изменить</span></button>` : ""}
        <button role="menuitem" data-a="pin">${icons.pushPin}<span>${isPinned ? "Открепить" : "Закрепить"}</span></button>
        ${m.kind === "text" ? `<button role="menuitem" data-a="copy">${icons.copy}<span>Копировать</span></button>` : ""}
      </div></div>`);
    document.body.append(menu);
    const box = $(".msg-menu", menu);
    const top = Math.min(Math.max(12, y - 20), window.innerHeight - box.offsetHeight - 12);
    box.style.top = `${top}px`;
    box.classList.toggle("right", mine);
    requestAnimationFrame(() => menu.classList.add("show"));
    menu.onclick = (e) => {
      const a = e.target.closest("[data-a]")?.dataset.a;
      if (!a && e.target !== menu) return;
      menu.remove();
      if (a === "reply") startReply(m);
      else if (a === "edit") startEdit(m);
      else if (a === "pin") setPin(isPinned ? null : m.id);
      else if (a === "copy") navigator.clipboard?.writeText(m.text).then(() => toast("Скопировано"), () => {});
    };
  }
  // долгое нажатие на телефоне, правая кнопка мыши на компьютере
  let pressTimer = 0, pressStart = null, suppressClick = false;
  list.addEventListener("pointerdown", (e) => {
    const node = e.target.closest(".msg[data-mid]");
    if (!node || e.target.closest(".reply-quote")) return;
    pressStart = { x: e.clientX, y: e.clientY };
    clearTimeout(pressTimer);
    pressTimer = setTimeout(() => {
      const m = msgs.get(Number(node.dataset.mid));
      if (!m || m.kind === "call") return;
      suppressClick = true;
      navigator.vibrate?.(15);
      openMsgMenu(m, pressStart.y);
    }, 450);
  });
  const cancelPress = (e) => {
    if (e?.type === "pointermove" && pressStart && Math.hypot(e.clientX - pressStart.x, e.clientY - pressStart.y) < 10) return;
    clearTimeout(pressTimer);
  };
  list.addEventListener("pointermove", cancelPress);
  list.addEventListener("pointerup", cancelPress);
  list.addEventListener("pointercancel", cancelPress);
  list.addEventListener("click", (e) => { if (suppressClick) { e.stopPropagation(); e.preventDefault(); suppressClick = false; } }, true);
  list.addEventListener("contextmenu", (e) => {
    const node = e.target.closest(".msg[data-mid]");
    const m = node && msgs.get(Number(node.dataset.mid));
    if (!m || m.kind === "call") return;
    e.preventDefault();
    clearTimeout(pressTimer);
    openMsgMenu(m, e.clientY);
  });

  if (!data.messages.length) {
    list.append(h(`<div class="empty" style="text-align:center"><h3>Вы понравились друг другу</h3><p class="muted small">Начните с общего интереса или запишите кружочек.</p></div>`));
  }
  data.messages.forEach(append);
  list.append(pendingBox);
  const uploader = createUploader({
    box: pendingBox, status: $(".upload-status", el), convId,
    onSent: (m) => { $(".empty", list)?.remove(); append(m); scrollDown(); },
  });
  uploader.restore().then(() => requestAnimationFrame(scrollDown));
  requestAnimationFrame(scrollDown);
  const markRead = () => api.post(`/api/chats/${convId}/read`).then(refreshUnread).catch(() => {});
  markRead();

  // --- События ---
  let typingTimer;
  const offs = [
    on("message_edit", (d) => { if (d.message.conversation_id === convId) replaceMessage(d.message); }),
    on("pin", (d) => { if (d.conversation_id === convId) { pinned = d.message; drawPinned(); } }),
    on("message", (d) => {
      if (d.message.conversation_id !== convId) return;
      $(".empty", list)?.remove();
      append(d.message);
      if (d.message.sender_id !== state.me.id) { typing.textContent = ""; markRead(); }
    }),
    on("typing", (d) => {
      if (d.conversation_id !== convId) return;
      typing.textContent = `${other.name} печатает…`;
      clearTimeout(typingTimer);
      typingTimer = setTimeout(() => (typing.textContent = ""), 4000);
    }),
    on("unmatch", (d) => {
      if (d.conversation_id !== convId) return;
      toast(`${other.name} удалил(а) пару`);
      go("#/chats");
    }),
  ];
  chatCleanup = () => { offs.forEach((f) => f()); voice?.cancel(); uploader.stop(); el.remove(); };

  $$("[data-call]", el).forEach((b) => (b.onclick = () => startCall(convId, other, b.dataset.call === "video")));
  $("[data-profile]", el).onclick = () => openProfile(other.id);
  $("[data-menu]", el).onclick = () => {
    const sheet = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Действия с чатом">
      <div class="bottom-sheet stack">
        <button class="btn ghost block" data-a="unmatch">${icons.trash} Удалить пару</button>
        <button class="btn danger block" data-a="block">${icons.block} Заблокировать</button>
        <button class="btn quiet block" data-a="close">Отмена</button>
      </div></div>`);
    document.body.append(sheet);
    sheet.onclick = async (e) => {
      const a = e.target.closest("[data-a]")?.dataset.a;
      if (!a && e.target !== sheet) return;
      sheet.remove();
      if (a === "unmatch" && (await confirmDialog(`Удалить пару с ${other.name}? Чат исчезнет у вас обоих.`, "Удалить пару"))) {
        await api.del(`/api/chats/${convId}`);
        go("#/chats");
      } else if (a === "block" && (await blockUser(other))) go("#/chats");
    };
  };

  // --- Стикеры ---
  let pack = Object.keys(PACKS)[0];
  function drawStickers() {
    stickerPanel.innerHTML = `<div class="packs">${Object.keys(PACKS).map((p) => `<button data-pack="${p}" class="${p === pack ? "on" : ""}">${p}</button>`).join("")}</div>
      ${PACKS[pack].map((s) => `<button class="st-btn" data-st="${s}" aria-label="Стикер ${s}">${s}</button>`).join("")}`;
    $$("[data-pack]", stickerPanel).forEach((b) => (b.onclick = () => { pack = b.dataset.pack; drawStickers(); }));
    $$("[data-st]", stickerPanel).forEach((b) => (b.onclick = () => {
      api.post(`/api/chats/${convId}/messages`, { kind: "sticker", text: b.dataset.st }).catch((ex) => toast(ex.message, { error: true }));
      stickerPanel.hidden = true;
    }));
  }
  drawStickers();

  // --- Отправка файлов: очередь с паузой и продолжением (uploads.js) ---
  async function upload(kind, blob, duration, filename) {
    $(".empty", list)?.remove();
    const file = kind === "image" ? await shrinkImage(blob) : blob;
    uploader.add(kind, file, { name: kind === "image" && file !== blob ? "photo.jpg" : filename, duration });
  }
  const MAX_PICK = 10;
  // iPhone при выборе из галереи иногда не указывает тип файла: тогда узнаём видео по расширению
  const isVideo = (f) => f.type.startsWith("video/") || /\.(mov|mp4|m4v|webm|3gp)$/i.test(f.name || "");
  const videoCapture = $("[data-video-capture]", el);
  videoCapture.onchange = () => { sendFiles([...videoCapture.files]); videoCapture.value = ""; };
  fileInput.onchange = () => { sendFiles([...fileInput.files]); fileInput.value = ""; };
  async function sendFiles(files) {
    if (files.length > MAX_PICK) toast(`За раз можно отправить до ${MAX_PICK} файлов, отправляем первые ${MAX_PICK}`);
    for (const f of files.slice(0, MAX_PICK)) await upload(isVideo(f) ? "video" : "image", f, null, f.name || "file"); // по порядку выбора
  }

  // --- Поле ввода ---
  let voice = null;
  let draft = "";
  let lastTypingSent = 0;

  function drawComposer() {
    if (voice) {
      composer.innerHTML = `<div class="rec-bar"><span>●</span><span class="t">0:00</span><button class="cancel" data-cancel>Отмена</button></div>
        <button class="icon-btn send" data-stop aria-label="Отправить голосовое">${icons.send}</button>`;
      const t = $(".t", composer);
      const tick = setInterval(() => (voice ? (t.textContent = fmtDur(voice.elapsed())) : clearInterval(tick)), 200);
      $("[data-cancel]", composer).onclick = () => { voice.cancel(); voice = null; drawComposer(); };
      $("[data-stop]", composer).onclick = stopVoice;
      return;
    }
    composer.innerHTML = `
      <button class="icon-btn" data-attach aria-label="Фото или видео">${icons.clip}</button>
      <textarea rows="1" placeholder="Сообщение" aria-label="Сообщение" maxlength="4000"></textarea>
      <button class="icon-btn" data-stickers aria-label="Стикеры">${icons.smile}</button>
      <span class="row" style="gap:6px" data-media>
        <button class="icon-btn" data-circle aria-label="Записать кружочек">${icons.circle}</button>
        <button class="icon-btn" data-voice aria-label="Записать голосовое">${icons.mic}</button>
      </span>
      <button class="icon-btn send" data-send aria-label="Отправить" hidden>${icons.send}</button>`;
    const ta = $("textarea", composer);
    ta.value = draft;
    const sync = () => {
      const has = ta.value.trim().length > 0;
      $("[data-send]", composer).hidden = !has;
      $("[data-media]", composer).hidden = has;
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
    };
    sync();
    ta.addEventListener("input", () => {
      draft = ta.value;
      sync();
      if (Date.now() - lastTypingSent > 3000) {
        send({ type: "typing", conversation_id: convId });
        lastTypingSent = Date.now();
      }
    });
    const sendText = async () => {
      const text = ta.value.trim();
      if (!text) return;
      draft = ""; ta.value = ""; sync();
      const editingNow = editing, replyNow = replyTo;
      editing = replyTo = null;
      drawReplyBar();
      try {
        if (editingNow) {
          replaceMessage(await api.patch(`/api/chats/${convId}/messages/${editingNow.id}`, { text }));
          return;
        }
        const m = await api.post(`/api/chats/${convId}/messages`, { text, reply_to: replyNow?.id || null });
        $(".empty", list)?.remove();
        append(m);
      } catch (ex) {
        toast(ex.message, { error: true });
        draft = text; ta.value = text; sync();
      }
    };
    ta.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); sendText(); }
    });
    $("[data-send]", composer).onclick = sendText;
    $("[data-attach]", composer).onclick = () => openAttachSheet({
      onPick: sendFiles,
      pickGallery: () => fileInput.click(),
      pickVideo: () => videoCapture.click(),
    });
    $("[data-stickers]", composer).onclick = () => (stickerPanel.hidden = !stickerPanel.hidden);
    $("[data-voice]", composer).onclick = startVoice;
    $("[data-circle]", composer).onclick = async () => {
      const res = await recordCircle();
      if (res && res.duration > 0.6) upload("circle", res.blob, res.duration, "circle.webm");
    };
  }

  async function startVoice() {
    voice = new VoiceRecorder();
    try {
      await voice.start();
    } catch {
      voice = null;
      return toast("Нет доступа к микрофону", { error: true });
    }
    voice.onLimit = stopVoice;
    drawComposer();
  }
  async function stopVoice() {
    if (!voice) return;
    const v = voice;
    voice = null;
    drawComposer();
    const { blob, duration } = await v.stop();
    if (duration > 0.6) upload("voice", blob, duration, "voice.webm");
  }
  drawComposer();
}

function messageEl(m, mine) {
  const time = `<span class="time">${fmtTime(m.created_at)}${mine && m.read_at ? " ✓✓" : ""}</span>`;
  const wrap = (cls, inner) => h(`<div class="msg ${cls} ${mine ? "mine" : ""}">${inner}</div>`);
  switch (m.kind) {
    case "sticker":
      return wrap("sticker", `<div class="st" role="img" aria-label="Стикер">${esc(m.text)}</div>${time}`);
    case "image": {
      const el = wrap("media", `<div class="bubble"><img src="${esc(m.media_url)}" alt="Фото" decoding="async">${m.text ? `<div class="caption">${esc(m.text)}</div>` : ""}</div>`);
      $("img", el).onclick = () => {
        const lb = h(`<div class="lightbox" role="dialog"><img src="${esc(m.media_url)}" alt="Фото"></div>`);
        lb.onclick = () => lb.remove();
        document.body.append(lb);
      };
      return el;
    }
    case "video":
      // poster — первый кадр с сервера; #t=0.1 — запасной способ, чтобы iPhone показал кадр, а не серый квадрат
      return wrap("media", `<div class="bubble"><video src="${esc(m.media_url)}#t=0.1" ${m.poster_url ? `poster="${esc(m.poster_url)}"` : ""} controls playsinline preload="metadata"></video></div>`);
    case "voice":
      return voiceEl(m, mine, time);
    case "circle":
      return circleEl(m, mine, time);
    case "call":
      return wrap("", `<div class="bubble"><span class="call-line">${m.text === "video" ? icons.video : icons.phone}${
        mine ? "Исходящий" : "Входящий"} ${m.text === "video" ? "видеозвонок" : "звонок"}</span>${time}</div>`);
    default:
      return wrap("", `<div class="bubble text">${esc(m.text)}${time}</div>`);
  }
}

function voiceEl(m, mine, time) {
  let seed = m.id * 9301;
  const rnd = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
  const bars = Array.from({ length: 30 }, () => `<i style="height:${20 + rnd() * 80}%"></i>`).join("");
  const el = h(`<div class="msg ${mine ? "mine" : ""}"><div class="bubble">
    <div class="voice"><button class="play" aria-label="Слушать">${icons.play}</button><div class="bars">${bars}</div><span class="len">${fmtDur(m.duration)}</span></div>
    ${time}<audio preload="none" src="${esc(m.media_url)}"></audio></div></div>`);
  const audio = $("audio", el), btn = $(".play", el), len = $(".len", el), ticks = $$(".bars i", el);
  btn.onclick = () => (audio.paused ? audio.play() : audio.pause());
  audio.onplay = () => (btn.innerHTML = icons.pause);
  audio.onpause = () => (btn.innerHTML = icons.play);
  audio.ontimeupdate = () => {
    const total = Number.isFinite(audio.duration) ? audio.duration : m.duration || 1;
    const k = audio.currentTime / total;
    ticks.forEach((t, i) => t.classList.toggle("on", i / ticks.length < k));
    len.textContent = fmtDur(audio.currentTime);
  };
  audio.onended = () => { ticks.forEach((t) => t.classList.remove("on")); len.textContent = fmtDur(m.duration); };
  return el;
}

function circleEl(m, mine, time) {
  const C = 2 * Math.PI * 48;
  const el = h(`<div class="msg circle ${mine ? "mine" : ""}">
    <div class="circle-msg" role="button" tabindex="0" aria-label="Видеосообщение, нажмите для звука">
      <video src="${esc(m.media_url)}#t=0.1" ${m.poster_url ? `poster="${esc(m.poster_url)}"` : ""} muted loop playsinline autoplay preload="metadata"></video>
      <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="none" stroke="var(--orange)" stroke-width="2.5" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg>
      <span class="dur">${fmtDur(m.duration)}</span>
    </div>${time}</div>`);
  const v = $("video", el), ring = $("circle", el);
  // iPhone: muted нужно выставить свойством, атрибут из разметки WebKit не учитывает — без этого кружок не стартует
  v.muted = true;
  v.playsInline = true;
  v.play().catch(() => {});
  const toggle = () => {
    if (v.muted) {
      v.muted = false; v.loop = false; v.currentTime = 0; v.play();
    } else {
      v.muted = true; v.loop = true; ring.setAttribute("stroke-dashoffset", C); v.play();
    }
  };
  $(".circle-msg", el).onclick = toggle;
  v.ontimeupdate = () => {
    if (v.muted) return;
    const total = Number.isFinite(v.duration) ? v.duration : m.duration || 1;
    ring.setAttribute("stroke-dashoffset", C * (1 - v.currentTime / total));
  };
  v.onended = () => { v.muted = true; v.loop = true; ring.setAttribute("stroke-dashoffset", C); v.play(); };
  return el;
}

// ---------------- Профиль и настройки ----------------

// Радиус поиска: ступени вместо сплошной шкалы — и 5 км, и 7000 км выставляются одним движением
const RADIUS_STEPS = [1, 2, 3, 5, 10, 15, 20, 30, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 7000];
const radiusIndex = (km) => RADIUS_STEPS.reduce((best, v, i) => (Math.abs(v - km) < Math.abs(RADIUS_STEPS[best] - km) ? i : best), 0);
const fmtKm = (km) => Number(km).toLocaleString("ru-RU");

function renderSettings() {
  const me = state.me;
  const step = onboardingStep(me);
  const pick = identityPick(me);
  const inTelegram = !!tgApp()?.initData;
  const root = screen(`
    <h1>Профиль ${me.is_admin ? `<span class="admin-badge">${icons.shield} Администрация</span>` : ""}</h1>
    ${me.is_demo ? `<div class="demo-banner" style="margin-top:14px">${icons.sparkle}<span>Вы в демо-режиме. Боты отвечают в чате, данные удалятся через сутки.</span></div>` : ""}
    ${step ? `<p class="badge-warn" style="margin-top:10px">Анкета не завершена. <a href="#/feed">Продолжить настройку</a></p>` : ""}
    <div class="section profile-hero">
      ${me.photo_url ? `<img src="${esc(me.photo_url)}" alt="Ваше фото">` : "<span></span>"}
      <div class="stack" style="gap:8px">
        ${me.photo_verified ? `<span class="badge-ok">${icons.check} Фото подтверждено</span>` : `<span class="badge-warn">Фото не подтверждено</span>`}
        <button class="btn quiet" id="change-photo">Заменить фото</button>
        ${me.name && me.photo_url ? `<button class="btn ghost" id="preview-profile">${icons.user} Как видят мою анкету</button>` : ""}
        <p class="hint">Новое фото снова нужно будет подтвердить камерой.</p>
      </div>
      <input type="file" accept="image/*" hidden>
    </div>

    <div class="section">
      <h3>Ещё фото</h3>
      <p class="hint" style="margin:-4px 0 12px">До 6 фото: хобби, поездки, друзья. Их видно в подробной анкете.</p>
      <div class="gallery-edit">${me.photos.map((p) => `<div class="ph-cell"><img src="${esc(p.url)}" alt=""><button class="del" data-del="${p.id}" aria-label="Удалить фото">${icons.x}</button></div>`).join("")}${
        me.photos.length < 6 ? `<button class="ph-cell add" data-add aria-label="Добавить фото">${icons.plus}</button>` : ""}</div>
      <input type="file" accept="image/*" multiple hidden id="gallery-input">
    </div>

    <div class="section">
      <h3>Интересы</h3>
      <div class="chips" style="margin-bottom:12px">${[...me.goals, ...me.interests].map((x, i) =>
        `<span class="chip static ${i < me.goals.length ? "hot" : ""}">${esc(x)}</span>`).join("")}</div>
      <a class="btn ghost" href="#/settings/interests">Изменить интересы</a>
      <p class="hint" style="margin-top:10px">Если ваших интересов нет в списке, напишите их в описании</p>
    </div>

    <form class="section stack" id="profile-form">
      <h3>О себе</h3>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(me.name)}"></label>
      <div class="field"><span>Дата рождения</span>
        <div class="readonly">${me.birth_date ? new Date(me.birth_date).toLocaleDateString(getLang() === "en" ? "en-GB" : "ru-RU") : "—"}</div>
        <span class="hint">Изменить дату можно только через <a href="#/support">поддержку</a></span></div>
      <div class="stack" data-identity></div>
      <div class="field"><span>Кого ищу</span>${choiceGroup("looking_for", state.config.looking_for, me.looking_for)}</div>
      <label class="field"><span>Описание</span><textarea class="input" name="bio" maxlength="500" placeholder="О себе и интересах, которых нет в списке">${esc(me.bio)}</textarea></label>
      <div class="extras-row">
        <label class="field"><span>Рост, см</span><input class="input" name="height" type="number" inputmode="numeric" min="100" max="250" placeholder="—" value="${me.height_cm ?? ""}"></label>
        ${me.age_group === "teen" ? "" : `<label class="field"><span>Вес, кг</span><input class="input" name="weight" type="number" inputmode="numeric" min="30" max="250" placeholder="—" value="${me.weight_kg ?? ""}"></label>`}
        <label class="field"><span>Знак</span><select class="input" name="zodiac"><option value="">—</option>${Object.entries(state.config.zodiac || {}).map(([k, l]) =>
          `<option value="${k}" ${k === me.zodiac ? "selected" : ""}>${ZODIAC_SIGNS[k] || ""} ${esc(l)}</option>`).join("")}</select></label>
      </div>
      <label class="field"><span>Искать в радиусе <b id="dist-val">${fmtKm(me.max_distance_km)}</b> км</span>
        <input type="range" name="dist" min="0" max="${RADIUS_STEPS.length - 1}" step="1" value="${radiusIndex(me.max_distance_km)}"></label>
      <p class="hint" id="my-city">${me.city_name ? `${icons.pin} Ваш город: <b>${esc(me.city_name)}</b> — определён по геопозиции` : "Город определится по геопозиции"}</p>
      <label class="switch"><input type="checkbox" name="showcity" ${me.show_city ? "checked" : ""}>
        <span class="label">Показывать город в анкете<small>Другие увидят только название города, точное место — никогда</small></span></label>
      <button type="button" class="btn ghost" id="relocate">${icons.pin} Обновить геопозицию</button>
      ${me.telegram_linked ? `<label class="switch"><input type="checkbox" name="tgnotify" ${me.tg_notifications ? "checked" : ""}>
        <span class="label">Уведомления в Telegram<small>${state.config.calls_enabled ? "Непрочитанные сообщения, пропущенные звонки и пары, когда вы не в приложении" : "Непрочитанные сообщения и пары, когда вы не в приложении"}</small></span></label>`
        : state.config.telegram_bot_username ? `<button type="button" class="btn ghost" id="tg-link">${icons.send} Подключить уведомления в Telegram</button>` : ""}
      <button class="btn block">Сохранить изменения</button>
    </form>

    <div class="section">
      <h3>Оформление</h3>
      <div class="choice-grid" style="grid-template-columns:repeat(3,1fr)" role="radiogroup" aria-label="Тема">
        ${[["dark", "Тёмная"], ["light", "Светлая"], ["system", "Как в системе"]].map(([k, l]) =>
          `<button type="button" class="chip" data-theme-pick="${k}" aria-pressed="${getThemePref() === k}">${l}</button>`).join("")}
      </div>
    </div>

    <div class="section">
      <h3>Язык</h3>
      <div class="choice-grid" style="grid-template-columns:repeat(2,1fr)" role="radiogroup" aria-label="Язык">
        ${[["ru", "Русский"], ["en", "English"]].map(([k, l]) => `<button type="button" class="chip" data-lang="${k}" translate="no" aria-pressed="${getLang() === k}">${l}</button>`).join("")}
      </div>
    </div>

    <div class="section stack">
      <h3>Чёрный список</h3>
      <div class="stack" data-blocks><p class="muted small">Загрузка…</p></div>
    </div>

    <div class="section stack">
      <h3>Ярлык на экране телефона</h3>
      <p class="hint" style="margin-top:-4px">COFI откроется одним нажатием, как обычное приложение</p>
      ${inTelegram && canShortcut() ? `<button type="button" class="btn ghost" id="tg-home">${icons.phoneApp} Добавить ярлык из Telegram</button>` : ""}
      ${inTelegram ? `<button type="button" class="btn ghost" id="open-browser">${icons.globe} Открыть COFI в браузере</button>` : ""}
      <details class="soft-details">
        <summary><span>iPhone и iPad (Safari)</span></summary>
        <ol class="howto">
          <li>Откройте COFI в Safari${inTelegram ? " (кнопка «Открыть COFI в браузере» выше)" : ""}</li>
          <li>Нажмите «Поделиться» — квадрат со стрелкой вверх внизу экрана</li>
          <li>Пролистайте вниз и выберите «На экран „Домой“»</li>
          <li>Нажмите «Добавить» — значок COFI появится на рабочем столе</li>
        </ol>
      </details>
      <details class="soft-details">
        <summary><span>Android (Chrome)</span></summary>
        <ol class="howto">
          <li>Откройте COFI в Chrome${inTelegram ? " (кнопка «Открыть COFI в браузере» выше)" : ""}</li>
          <li>Нажмите меню ⋮ в правом верхнем углу</li>
          <li>Выберите «Добавить на главный экран» или «Установить приложение»</li>
          <li>Подтвердите «Добавить» — значок COFI появится на рабочем столе</li>
        </ol>
      </details>
    </div>

    <div class="section stack">
      <a class="row-link" href="#/guide"><span><b>Как пользоваться</b><br><span class="muted small">${state.config.calls_enabled ? "Жесты, пары, чат и звонки" : "Жесты, пары и чат"}</span></span>${icons.arrow}</a>
      <a class="row-link" href="#/support"><span><b>Поддержка</b><br><span class="muted small">Помощь, жалобы и предложения</span></span>${icons.headset}</a>
      <details class="soft-details docs-list">
        <summary><span><b>Документы</b><br><span class="muted small">Соглашение, правила, персональные данные</span></span></summary>
        ${LEGAL_DOCS.map((d) => `<a class="doc-link" href="#/legal/${d.key}" data-doc="${d.key}">${d.title}</a>`).join("")}
      </details>
    </div>

    <a class="section ad-offer" href="#/ads">
      <span class="ad-offer-icon">${icons.megaphone}</span>
      <span><b>Реклама в COFI</b><br>Во время тестирования реклама не размещается. Для будущего сотрудничества пишите на craftycat119@mail.ru или в этот чат.</span>
      ${icons.arrow}
    </a>

    <div class="section stack">
      <h3>Аккаунт</h3>
      <p class="muted small">${me.is_demo ? "Демо-аккаунт без регистрации" : me.auth_provider === "telegram" ? `Вход через Telegram${me.telegram_username ? ` (@${esc(me.telegram_username)})` : ""}` : `Вход по почте ${esc(me.email)}`}</p>
      ${me.is_admin ? `<a class="btn quiet" href="/admin">Админ-панель</a>` : ""}
      ${me.is_demo ? `<button class="btn" id="leave-demo">Зарегистрироваться</button>` : ""}
      <button class="btn ghost" id="logout">Выйти</button>
      <button class="btn danger" id="delete">Удалить анкету</button>
    </div>`);

  identityFields($("[data-identity]", root), pick, me.age);
  bindChoice(root, "looking_for", (v) => (pick.looking_for = v));
  $$("[data-lang]", root).forEach((b) => (b.onclick = () => {
    if (b.dataset.lang === getLang()) return;
    setLang(b.dataset.lang);
    api.put("/api/profile", { language: b.dataset.lang }).catch(() => {});
    rerender();
  }));
  $$("[data-theme-pick]", root).forEach((b) => (b.onclick = () => {
    setTheme(b.dataset.themePick);
    $$("[data-theme-pick]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  const form = $("#profile-form", root);
  form.dist.oninput = () => ($("#dist-val", root).textContent = fmtKm(RADIUS_STEPS[form.dist.value]));
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = {
      name: form.name.value,
      bio: form.bio.value,
      max_distance_km: RADIUS_STEPS[Number(form.dist.value)],
      show_city: form.showcity.checked,
      ...pick,
    };
    if (form.tgnotify) data.tg_notifications = form.tgnotify.checked;
    data.height_cm = Number(form.height.value) || 0;
    if (form.weight) data.weight_kg = Number(form.weight.value) || 0;
    data.zodiac = form.zodiac.value;
    try {
      state.me = await api.put("/api/profile", data);
      toast("Изменения сохранены");
    } catch (ex) { toast(ex.message, { error: true }); }
  };

  $("#tg-link", root)?.addEventListener("click", linkTelegram);
  $("#tg-home", root)?.addEventListener("click", addShortcut);
  $("#preview-profile", root)?.addEventListener("click", () => openProfile(me.id, { preview: true }));
  $("#open-browser", root)?.addEventListener("click", openInBrowser);

  const drawBlocks = async () => {
    const box = $("[data-blocks]", root);
    let list = [];
    try { list = await api.get("/api/blocks"); } catch { /* офлайн */ }
    box.innerHTML = list.length ? list.map((u) => `<div class="block-row"><img class="avatar" src="${esc(u.photo_url || "")}" alt=""><b translate="no">${esc(u.name || "Без имени")}</b>
      <button type="button" class="btn quiet" data-unblock="${u.id}">Разблокировать</button></div>`).join("")
      : `<p class="muted small">Пусто. Заблокировать человека можно в его анкете или в меню чата</p>`;
    $$("[data-unblock]", box).forEach((b) => (b.onclick = async () => {
      try { await api.del(`/api/users/${b.dataset.unblock}/block`); toast("Разблокировано"); drawBlocks(); } catch (ex) { toast(ex.message, { error: true }); }
    }));
  };
  drawBlocks();

  $("#relocate", root).onclick = async () => {
    try {
      const r = await api.post("/api/profile/location", await getPosition());
      state.me.city_name = r.city || null;
      $("#my-city", root).innerHTML = r.city ? `${icons.pin} Ваш город: <b>${esc(r.city)}</b> — определён по геопозиции` : "Город по этой геопозиции не определился";
      toast(r.city ? `Геопозиция обновлена: ${r.city}` : "Геопозиция обновлена");
    } catch (ex) { toast(ex.message, { error: true }); }
  };

  const galleryInput = $("#gallery-input", root);
  $("[data-add]", root)?.addEventListener("click", () => galleryInput.click());
  galleryInput.onchange = async () => {
    for (const f of [...galleryInput.files].slice(0, 6 - state.me.photos.length)) {
      const fd = new FormData();
      fd.append("file", f);
      try { state.me = await api.post("/api/profile/photos", fd); } catch (ex) { toast(ex.message, { error: true }); break; }
    }
    renderSettings();
  };
  $$("[data-del]", root).forEach((b) => (b.onclick = async () => {
    try { state.me = await api.del(`/api/profile/photos/${b.dataset.del}`); renderSettings(); } catch (ex) { toast(ex.message, { error: true }); }
  }));

  const input = $(".profile-hero input[type=file]", root);
  $("#change-photo", root).onclick = () => input.click();
  input.onchange = async () => {
    const fd = new FormData();
    fd.append("file", input.files[0]);
    try {
      await api.post("/api/profile/photo", fd);
      await reloadMe();
      go("#/feed"); // онбординг сам откроет сканер
    } catch (ex) { toast(ex.message, { error: true }); }
  };

  $("#leave-demo", root)?.addEventListener("click", async () => {
    await api.del("/api/profile");
    disconnectSocket();
    state.me = null;
    go("#/");
  });
  $("#logout", root).onclick = async () => {
    await api.post("/api/auth/logout");
    disconnectSocket();
    state.me = null;
    go("#/");
  };
  $("#delete", root).onclick = async () => {
    if (!(await confirmDialog("Удалить анкету навсегда? Чаты и пары тоже удалятся.", "Удалить навсегда"))) return;
    await api.del("/api/profile");
    disconnectSocket();
    state.me = null;
    go("#/");
  };
}

// ---------------- Глобальные события ----------------

on("match", (d) => {
  if (!state.me) return;
  showMatch({ conversation_id: d.conversation_id, user: d.user, common: d.common });
  notifyBrowser("Взаимная симпатия!", `Вы понравились ${d.user.name}`);
});

on("message", (d) => {
  const m = d.message;
  if (!state.me || m.sender_id === state.me.id || state.openChat === m.conversation_id) return;
  refreshUnread();
  if (currentHash().startsWith("#/chats")) renderChats();
  api.get(`/api/chats/${m.conversation_id}?limit=1`).then((c) => {
    const text = previewText(m, state.me.id);
    toast(`${c.user.name}: ${text}`, { image: c.user.photo_url, onClick: () => go(`#/chat/${m.conversation_id}`) });
    notifyBrowser(c.user.name, text);
  }).catch(() => {});
});

function notifyBrowser(title, body) {
  if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    try { new Notification(title, { body, icon: "/static/img/logo-192.png" }); } catch { /* мобильные браузеры */ }
  }
}

document.addEventListener("click", () => {
  if ("Notification" in window && Notification.permission === "default" && state.me) Notification.requestPermission();
}, { once: true });

window.addEventListener("unhandledrejection", (e) => {
  if (e.reason instanceof ApiError && e.reason.status === 401) {
    state.me = null;
    disconnectSocket();
    go("#/");
  }
});

// Если внешнее фото не загрузилось (нет сети), показываем фирменную заглушку
const PLACEHOLDER = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="50"><defs><pattern id="p" width="11" height="11" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="11" height="11" fill="#c9461a"/><rect width="3" height="11" fill="#a9380f"/></pattern></defs><rect width="40" height="50" fill="url(#p)"/></svg>');
document.addEventListener("error", (e) => {
  const img = e.target;
  if (img.tagName === "IMG" && !img.dataset.fallback) {
    img.dataset.fallback = "1";
    img.src = PLACEHOLDER;
  }
}, true);

/** Сервер не ответил: понятный экран вместо вечной загрузки. */
function offlineScreen() {
  const app = document.getElementById("app");
  app.innerHTML = `<div class="screen offline-screen"><div class="empty">
    <h1>Нет связи с COFI</h1>
    <p class="lead">Сервер не ответил. Проверьте интернет и попробуйте ещё раз. Если не помогает — откройте COFI в браузере.</p>
    <button class="btn block" data-retry>Повторить</button>
    <button class="btn ghost block" data-browser>${icons.globe} Открыть в браузере</button>
  </div></div>`;
  app.querySelector("[data-retry]").onclick = () => location.reload();
  app.querySelector("[data-browser]").onclick = openInBrowser;
}

boot();
