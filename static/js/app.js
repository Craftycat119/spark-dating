import { api, ApiError, connectSocket, disconnectSocket, on, send } from "./api.js";
import { initCalls, startCall } from "./call.js";
import { icons } from "./icons.js";
import { recordCircle, VoiceRecorder } from "./recorder.js";
import { runScanner } from "./scanner.js";
import { PACKS } from "./stickers.js";
import { mountThread } from "./threads.js";
import { renderGuide } from "./guide.js";
import { getThemePref, resolvedTheme, setTheme } from "./theme.js";
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
      if (!el.isConnected) return;
      const fallback = el.querySelector(".wordmark");
      if (mountPuff(el, { shape }) && fallback) fallback.remove();
    })
    .catch(() => { /* без 3D всё работает */ });
}

// ---------------- Запуск и маршрутизация ----------------

async function boot() {
  try {
    state.config = await api.get("/api/config");
  } catch {
    state.config = { app_name: "COFI", survey: [], genders: {}, looking_for: {}, min_interests: 3, ice_servers: [] };
  }
  try {
    state.me = await api.get("/api/auth/me");
  } catch {
    state.me = null;
  }
  if (state.me) afterLogin();
  window.addEventListener("hashchange", route);
  route();
}

function afterLogin() {
  connectSocket();
  initCalls(state.config, async (convId) => {
    try {
      const c = await api.get(`/api/chats/${convId}?limit=1`);
      return c.user;
    } catch { return null; }
  });
  refreshLocationSilently();
  refreshUnread();
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function onboardingStep(me) {
  if (!me.name || !me.age || !me.gender || !me.looking_for) return "about";
  if (!me.survey_done) return "survey";
  if (!me.photo_url) return "photo";
  if (!me.photo_verified) return "scan";
  if (!me.has_location) return "location";
  return null;
}

function route() {
  closeChat();
  $(".profile-view")?.remove();
  const page = location.hash.split("/")[1];
  if (page === "guide") return showGuide();
  if (!state.me) return renderAuth();
  const step = onboardingStep(state.me);
  const [, name, arg] = location.hash.split("/");
  if (step && name !== "settings") return renderOnboarding(step);
  switch (name) {
    case "chats": return renderChats();
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
  const cur = location.hash.split("/")[1] || "feed";
  const item = (key, label, icon) =>
    `<a href="#/${key}" class="${cur === key || (key === "chats" && cur === "chat") ? "on" : ""}">${icon}<span>${label}</span>${
      key === "chats" && state.unread ? `<b class="badge">${state.unread}</b>` : ""}</a>`;
  return h(`<nav class="nav" aria-label="Разделы">${item("feed", "Пары", icons.flame)}${item("chats", "Чаты", icons.chat)}${item("settings", "Профиль", icons.user)}</nav>`);
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
  stopGuide = renderGuide(main, { loggedIn: !!state.me, onDemo: startDemo });
}

async function startDemo() {
  try {
    state.me = await api.post("/api/auth/demo");
  } catch (ex) {
    return toast(ex.message, { error: true });
  }
  afterLogin();
  go("#/feed");
  toast("Это демо: свайп вниз, чтобы лайкнуть. Трое из ботов уже лайкнули вас", { timeout: 6000 });
}

function themeIcon() {
  return resolvedTheme() === "light" ? icons.moon : icons.sun;
}

// ---------------- Вход и регистрация ----------------

function renderAuth(mode = "login") {
  const tg = state.config.telegram_bot_username;
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
        <p class="error-text" id="auth-error" hidden></p>
        <button class="btn block" type="submit">${mode === "login" ? "Войти" : "Создать аккаунт"}</button>
        ${mode === "login" ? `<button type="button" class="link" id="forgot" style="align-self:flex-start">Забыли пароль?</button>` : ""}
      </form>
      ${tg ? `<div class="divider">или</div><div id="tg-login" style="display:flex;justify-content:center;min-height:48px"></div>
        <p class="hint" style="text-align:center">Через Telegram почта и пароль не нужны, только подтверждение фото.</p>` : ""}
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
          <button class="chip hot" data-demo>Демо без регистрации</button>
          <a class="chip" href="#/guide">Как это работает</a>
        </div>
      </div>
    </section>
${sheet}`, { nav: false, cls: "auth" });
    mount3d($(".stage", root), "knot");
    $("[data-demo]", root).onclick = startDemo;
    $(".theme-toggle", root).onclick = (e) => {
      setTheme(resolvedTheme() === "light" ? "dark" : "light");
      e.currentTarget.innerHTML = themeIcon();
    };
  }
  $$("[data-mode]", root).forEach((b) => (b.onclick = () => renderAuth(b.dataset.mode)));
  const form = $("form", root);
  const err = $("#auth-error", root);
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
        const r = await api.post("/api/auth/register", { email, password });
        renderCode(email, r.dev_code);
      } else {
        state.me = await api.post("/api/auth/login", { email, password });
        afterLogin();
        go("#/feed");
      }
    } catch (ex) {
      if (ex.code === "email_not_verified") return renderCode(email, ex.detail.dev_code);
      showErr(ex.message);
    } finally {
      btn.disabled = false;
    }
  };

  $("#forgot", root)?.addEventListener("click", () => renderForgot(form.email.value.trim()));

  if (tg) {
    window.onTelegramAuth = async (user) => {
      try {
        state.me = await api.post("/api/auth/telegram", user);
        afterLogin();
        go("#/feed");
      } catch (ex) { toast(ex.message, { error: true }); }
    };
    const s = document.createElement("script");
    s.async = true;
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.dataset.telegramLogin = tg;
    s.dataset.size = "large";
    s.dataset.radius = "24";
    s.dataset.onauth = "onTelegramAuth(user)";
    s.dataset.requestAccess = "write";
    $("#tg-login", root).append(s);
  }
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
    <div class="stack" style="margin-top:24px">
      <h1>Проверьте почту</h1>
      <p class="muted">Мы отправили 6-значный код на <b style="color:var(--text)">${esc(email)}</b>. На эту почту будут приходить новости о метчах и обновлениях.</p>
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
}

function renderForgot(prefill = "") {
  const root = screen(`
    <div class="stack" style="margin-top:24px">
      <h1>Новый пароль</h1>
      <p class="muted">Пришлём код на почту, после чего вы зададите новый пароль.</p>
      <form class="stack" id="f1">
        <label class="field"><span>Почта</span><input class="input" type="email" name="email" value="${esc(prefill)}" required></label>
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
  f1.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api.post("/api/auth/forgot-password", { email: f1.email.value.trim() });
      f2.hidden = false;
      if (r.dev_code) { $("#dev-hint", root).hidden = false; $("#dev-hint", root).textContent = `Режим разработки: код ${r.dev_code}`; }
      f2.code.focus();
    } catch (ex) { toast(ex.message, { error: true }); }
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
}

// ---------------- Онбординг ----------------

const STEP_ORDER = ["about", "survey", "photo", "scan", "location"];

function stepsBar(step) {
  const i = STEP_ORDER.indexOf(step);
  return `<div class="steps" aria-label="Шаг ${i + 1} из ${STEP_ORDER.length}">${STEP_ORDER.map((_, j) => `<i class="${j <= i ? "done" : ""}"></i>`).join("")}</div>`;
}

async function nextStep() {
  await reloadMe();
  route();
}

function renderOnboarding(step) {
  ({ about: stepAbout, survey: () => renderSurvey(), photo: stepPhoto, scan: stepScan, location: stepLocation })[step]();
}

function choiceGroup(name, options, value) {
  return `<div class="choice-grid" style="grid-template-columns:repeat(${Object.keys(options).length},1fr)" role="radiogroup">${Object.entries(options).map(([k, label]) =>
    `<button type="button" class="chip" data-name="${name}" data-value="${k}" aria-pressed="${k === value}">${esc(label)}</button>`).join("")}</div>`;
}

function bindChoice(root, name, onPick) {
  $$(`[data-name="${name}"]`, root).forEach((b) => (b.onclick = () => {
    $$(`[data-name="${name}"]`, root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    onPick(b.dataset.value);
  }));
}

function stepAbout() {
  const me = state.me;
  const pick = { gender: me.gender, looking_for: me.looking_for };
  const root = screen(`${stepsBar("about")}
    <form class="stack">
      <h1>Знакомимся</h1>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(me.name)}" autocomplete="given-name" required></label>
      <label class="field"><span>Возраст</span><input class="input" name="age" type="number" min="18" max="100" value="${me.age ?? ""}" required></label>
      <div class="field"><span>Я</span>${choiceGroup("gender", state.config.genders, me.gender)}</div>
      <div class="field"><span>Кого ищу</span>${choiceGroup("looking_for", state.config.looking_for, me.looking_for)}</div>
      <label class="field"><span>Коротко о себе</span><textarea class="input" name="bio" maxlength="500" placeholder="Например: варю фильтр-кофе, по субботам бегаю в парке">${esc(me.bio)}</textarea></label>
      <p class="error-text" hidden></p>
      <button class="btn block">Дальше</button>
    </form>`, { nav: false });
  bindChoice(root, "gender", (v) => (pick.gender = v));
  bindChoice(root, "looking_for", (v) => (pick.looking_for = v));
  $("form", root).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const err = $(".error-text", root);
    if (!pick.gender || !pick.looking_for) { err.textContent = "Выберите пол и кого ищете"; err.hidden = false; return; }
    try {
      await api.put("/api/profile", { name: f.name.value, age: Number(f.age.value), bio: f.bio.value, ...pick });
      nextStep();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
}

/** Опрос: по вопросу на экран, можно выбирать несколько вариантов. */
function renderSurvey({ editing = false } = {}) {
  const survey = state.config.survey;
  const answers = { goals: new Set(state.me.goals), interests: new Set(state.me.interests) };
  let i = 0;

  const draw = () => {
    const q = survey[i];
    const set = q.key === "goals" ? answers.goals : answers.interests;
    const last = i === survey.length - 1;
    const root = screen(`${editing ? "" : stepsBar("survey")}
      <div class="stack" style="gap:18px">
        <div class="survey-head"><span class="muted small">${editing ? "Интересы" : "Пара вопросов о вас"}</span><span class="survey-count">${i + 1}/${survey.length}</span></div>
        <h1>${esc(q.title)}</h1>
        ${q.hint ? `<p class="muted">${esc(q.hint)}</p>` : ""}
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
  drop.onclick = () => input.click();
  drop.onkeydown = (e) => (e.key === "Enter" || e.key === " ") && input.click();
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    drop.style.backgroundImage = `url(${URL.createObjectURL(file)})`;
    drop.classList.add("has");
    drop.innerHTML = `<div class="skeleton"></div>`;
    err.hidden = true;
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api.post("/api/profile/photo", fd);
      drop.innerHTML = "";
      onUploaded();
    } catch (ex) {
      drop.innerHTML = "";
      err.textContent = ex.message;
      err.hidden = false;
    }
    input.value = "";
  };
}

function stepPhoto() {
  const root = screen(`${stepsBar("photo")}
    <div class="stack">
      <h1>Ваше фото</h1>
      <p class="muted">Нужно фото, где хорошо видно лицо, и только ваше. Следующим шагом сверим его с камерой.</p>
      <div class="photo-drop" role="button" tabindex="0"><div>${icons.camera}Выбрать фото</div></div>
      <input type="file" accept="image/*" hidden>
      <p class="error-text" hidden></p>
    </div>`, { nav: false });
  photoPicker(root, nextStep);
}

function stepScan() {
  const root = screen(`${stepsBar("scan")}
    <div class="stack">
      <h1>Проверка, что это вы</h1>
      <p class="muted">Камера покажет овал. Держите лицо в нём и следуйте подсказкам: смотрите прямо, затем поверните голову влево и вправо. Это защищает от чужих фото.</p>
      <div class="profile-hero"><img src="${esc(state.me.photo_url)}" alt="Ваше фото"><p class="small muted">Сверяем с этим фото</p></div>
      <div id="scan-area"></div>
      <p class="error-text" id="scan-error" hidden></p>
      <button class="btn block" id="start">${icons.shield} Начать проверку</button>
      <button class="btn ghost block" id="change">Выбрать другое фото</button>
      <input type="file" accept="image/*" hidden>
    </div>`, { nav: false });
  const startBtn = $("#start", root);
  const err = $("#scan-error", root);
  startBtn.onclick = async () => {
    startBtn.hidden = true;
    err.hidden = true;
    $(".profile-hero", root).hidden = true;
    const res = await runScanner($("#scan-area", root));
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
  const btn = $(".btn", root);
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
    <div class="deck" aria-live="polite"><div class="skeleton" style="position:relative;height:420px"></div></div>
    <div class="btns" hidden>
      <div class="bw"><button class="skip" aria-label="Дальше">${icons.x}</button><span>Дальше</span></div>
      <div class="bw"><button class="like" aria-label="Нравится">${icons.heart}</button><span>Нравится</span></div>
    </div>
    <p class="swipe-hint" hidden>Свайп вниз: нравится, вверх: дальше. Нажмите на фото, чтобы открыть анкету</p>`, { cls: "feed" });
  const deck = $(".deck", root);
  const btns = $(".btns", root);
  const hint = $(".swipe-hint", root);
  const counter = $(".counter", root);
  let cards = [], total = 0, seen = 0, busy = false, loading = false, thread = null;

  const empty = (title, text, btnLabel, fn) => {
    btns.hidden = hint.hidden = true;
    counter.textContent = "";
    deck.replaceChildren(h(`<div class="empty"><h1>${title}</h1><p class="lead">${text}</p>${btnLabel ? `<button class="btn">${btnLabel}</button>` : ""}</div>`));
    if (fn) $(".btn", deck).onclick = fn;
  };

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const res = await api.get("/api/feed?limit=10");
      total = seen + res.total;
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
      return empty("Рядом пока никого", `В радиусе ${state.me.max_distance_km} км новых анкет нет. Увеличьте радиус или добавьте интересов.`, "Открыть профиль", () => go("#/settings"));
    }
    btns.hidden = hint.hidden = false;
    counter.textContent = `${seen + 1} из ${Math.max(total, seen + 1)} рядом`;
    const rest = c.interests.filter((x) => !c.common.includes(x));
    deck.replaceChildren(h(`<div>
      <article class="person enter">
        <button class="ava" aria-label="Открыть анкету: ${esc(c.name)}">
          ${c.photo_url ? `<img src="${esc(c.photo_url)}" alt="">` : esc(c.name.charAt(0))}
          ${c.photos_count ? `<span class="more">+${c.photos_count} фото</span>` : ""}
        </button>
        <div class="pname">${esc(c.name)}<span>, ${c.age}</span></div>
        <div class="meta">${[kmText(c.distance_km), c.verified ? "фото подтверждено" : ""].filter(Boolean).join(" · ")}</div>
        ${c.bio ? `<p class="pbio">${esc(c.bio)}</p>` : ""}
      </article>
      <div class="shared-lbl">${c.common.length
        ? `У вас общего: <b>${c.common.length} ${plural(c.common.length, "интерес", "интереса", "интересов")}</b> · совпадение ${c.match}%`
        : "Общих интересов пока нет, но можно познакомиться"}</div>
      <div class="thread"></div>
      ${rest.length ? `<p class="rest">Ещё интересы: ${esc(rest.slice(0, 8).join(", "))}</p>` : ""}
    </div>`));
    $(".ava", deck).onclick = () => openProfile(c.id, { onDecide: decide });
    thread = mountThread($(".thread", deck), c.common.slice(0, 6));
  }

  async function decide(like) {
    const c = cards[0];
    if (!c || busy || !thread) return;
    busy = true;
    $$("button", btns).forEach((b) => (b.disabled = true));
    navigator.vibrate?.(like ? 12 : 6);
    const request = api.post("/api/feed/swipe", { user_id: c.id, like }).catch((ex) => { toast(ex.message, { error: true }); return {}; });
    const [res] = await Promise.all([request, thread.play(like ? "like" : "skip")]);
    if (res.match) showMatch({ conversation_id: res.conversation_id, user: res.user, common: res.user.common });
    cards.shift();
    seen++;
    busy = false;
    $$("button", btns).forEach((b) => (b.disabled = false));
    thread = null;
    draw();
    if (cards.length < 3) load();
  }

  $(".skip", btns).onclick = () => decide(false);
  $(".like", btns).onclick = () => decide(true);

  // Свайп по вертикали: вниз — нравится, вверх — дальше (как в макете)
  let y0 = null;
  deck.addEventListener("pointerdown", (e) => { if (!e.target.closest(".ava")) y0 = e.clientY; });
  deck.addEventListener("pointerup", (e) => {
    if (y0 === null) return;
    const dy = e.clientY - y0;
    y0 = null;
    if (dy > 80) decide(true);
    else if (dy < -80) decide(false);
  });
  deck.addEventListener("pointercancel", () => (y0 = null));
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

async function openProfile(userId, { onDecide = null } = {}) {
  let p;
  try {
    p = await api.get(`/api/users/${userId}`);
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
    <div class="profile-body">
      <div class="pname">${esc(p.name)}<span>, ${p.age}</span></div>
      <div class="meta muted small" style="margin-top:6px">${[kmText(p.distance_km), p.verified ? "фото подтверждено" : "", p.online ? "в сети" : ""].filter(Boolean).join(" · ")}</div>
      <div class="match-strip">
        <div><b>${p.match}%</b><span>совпадение</span></div>
        <div><b>${p.common.length}</b><span>${plural(p.common.length, "общий интерес", "общих интереса", "общих интересов")}</span></div>
        <div><b>${p.photos.length}</b><span>${plural(p.photos.length, "фото", "фото", "фото")}</span></div>
      </div>
      ${p.bio ? `<h3>О себе</h3><p style="font-size:16px;line-height:1.5">${esc(p.bio)}</p>` : ""}
      ${p.goals.length ? `<h3>Ищет</h3><div class="chips">${p.goals.map((g) => `<span class="chip static ghost">${esc(g)}</span>`).join("")}</div>` : ""}
      <h3>Интересы</h3>
      <div class="chips">${p.interests.map((x) => `<span class="chip static ${goalsSet.has(x) ? "hot" : "ghost"}">${esc(x)}</span>`).join("")}</div>
    </div>
    <div class="profile-actions"></div>
  </section>`);

  const actions = $(".profile-actions", el);
  const close = () => { el.remove(); document.removeEventListener("keydown", esc_); };
  const esc_ = (e) => e.key === "Escape" && close();
  if (p.conversation_id) {
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
    actions.innerHTML = `<p class="note">${p.liked ? "Вы отметили симпатию. Чат откроется, когда она станет взаимной" : "Написать можно после взаимной симпатии"}</p>`;
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

function showMatch({ conversation_id, user, common = [] }) {
  if (state.shownMatches.has(conversation_id)) return;
  state.shownMatches.add(conversation_id);
  const el = h(`<div class="overlay match" role="dialog" aria-label="Взаимная симпатия">
    <div class="match-modal">
      <div class="heart-stage" aria-hidden="true"></div>
      <h1 class="match-title">Взаимно</h1>
      <div class="pair"><img src="${esc(state.me.photo_url)}" alt="Вы"><img src="${esc(user.photo_url)}" alt="${esc(user.name)}"></div>
      <p>Вы и ${esc(user.name)} понравились друг другу.${common.length ? " У вас общее:" : ""}</p>
      ${common.length ? `<div class="chips">${common.slice(0, 6).map((x) => `<span class="chip static">${esc(x)}</span>`).join("")}</div>` : ""}
      <button class="btn dark block" data-chat>Написать сообщение</button>
      <button class="btn ghost block" data-close>Смотреть дальше</button>
    </div></div>`);
  document.body.append(el);
  mount3d($(".heart-stage", el), "heart");
  navigator.vibrate?.([20, 60, 30]);
  $("[data-chat]", el).onclick = () => { el.remove(); go(`#/chat/${conversation_id}`); };
  $("[data-close]", el).onclick = () => el.remove();
}

// ---------------- Чаты ----------------

function previewText(m, meId) {
  if (!m) return "Новая пара, напишите первым";
  const mine = m.sender_id === meId ? "Вы: " : "";
  const map = { image: "Фото", video: "Видео", voice: "Голосовое", circle: "Видеосообщение", sticker: m.text, call: m.text === "video" ? "Видеозвонок" : "Звонок" };
  return mine + (m.kind === "text" ? m.text : map[m.kind] || "");
}

async function renderChats() {
  const root = screen(`<h1>Чаты</h1><div id="chats"></div>`);
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
          <span class="top"><b>${esc(c.user.name)}</b><span class="time">${fmtShort(c.last_message.created_at)}</span></span>
          <span class="row" style="gap:8px"><span class="preview" style="flex:1">${esc(previewText(c.last_message, state.me.id))}</span>${c.unread ? `<span class="unread">${c.unread}</span>` : ""}</span>
        </span>
      </a>`).join("")}</div></div>`));
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
        <span class="who"><b>${esc(other.name)}${other.age ? `, ${other.age}` : ""}</b><small class="status">${other.online ? "в сети" : "не в сети"}</small></span>
      </button>
      <button class="icon-btn" data-call="audio" aria-label="Аудиозвонок">${icons.phone}</button>
      <button class="icon-btn" data-call="video" aria-label="Видеозвонок">${icons.video}</button>
      <button class="icon-btn" data-menu aria-label="Ещё">${icons.more}</button>
    </header>
    <div class="messages" tabindex="0"></div>
    <div class="typing" aria-live="polite"></div>
    <div class="sticker-panel" hidden></div>
    <div class="composer"></div>
    <input type="file" accept="image/*,video/*" hidden>
  </section>`);
  document.body.append(el);
  const list = $(".messages", el);
  const typing = $(".typing", el);
  const composer = $(".composer", el);
  const stickerPanel = $(".sticker-panel", el);
  const fileInput = $("input[type=file]", el);
  const seen = new Set();
  let lastDay = null;

  const atBottom = () => list.scrollHeight - list.scrollTop - list.clientHeight < 120;
  const scrollDown = () => (list.scrollTop = list.scrollHeight);

  function append(m) {
    if (seen.has(m.id)) return;
    seen.add(m.id);
    const day = fmtDay(m.created_at);
    if (day !== lastDay) {
      list.append(h(`<div class="day-sep">${day}</div>`));
      lastDay = day;
    }
    const stick = atBottom();
    list.append(messageEl(m, m.sender_id === state.me.id));
    if (stick || m.sender_id === state.me.id) scrollDown();
  }

  if (!data.messages.length) {
    list.append(h(`<div class="empty" style="text-align:center"><h3>Вы понравились друг другу</h3><p class="muted small">Начните с общего интереса или запишите кружочек.</p></div>`));
  }
  data.messages.forEach(append);
  requestAnimationFrame(scrollDown);
  const markRead = () => api.post(`/api/chats/${convId}/read`).then(refreshUnread).catch(() => {});
  markRead();

  // --- События ---
  let typingTimer;
  const offs = [
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
  chatCleanup = () => { offs.forEach((f) => f()); voice?.cancel(); el.remove(); };

  $$("[data-call]", el).forEach((b) => (b.onclick = () => startCall(convId, other, b.dataset.call === "video")));
  $("[data-profile]", el).onclick = () => openProfile(other.id);
  $("[data-menu]", el).onclick = async () => {
    if (await confirmDialog(`Удалить пару с ${other.name}? Чат исчезнет у вас обоих.`, "Удалить пару")) {
      await api.del(`/api/chats/${convId}`);
      go("#/chats");
    }
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

  // --- Отправка файлов ---
  async function upload(kind, blob, duration, filename) {
    const fd = new FormData();
    fd.append("kind", kind);
    if (duration) fd.append("duration", String(Math.round(duration * 10) / 10));
    fd.append("file", blob, filename);
    typing.textContent = "Отправка…";
    try {
      await api.post(`/api/chats/${convId}/media`, fd);
    } catch (ex) {
      toast(ex.message, { error: true });
    } finally {
      if (typing.textContent === "Отправка…") typing.textContent = "";
    }
  }
  fileInput.onchange = () => {
    const f = fileInput.files[0];
    if (f) upload(f.type.startsWith("video") ? "video" : "image", f, null, f.name);
    fileInput.value = "";
  };

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
      try {
        const m = await api.post(`/api/chats/${convId}/messages`, { text });
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
    $("[data-attach]", composer).onclick = () => fileInput.click();
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
      const el = wrap("media", `<div class="bubble"><img src="${esc(m.media_url)}" alt="Фото" loading="lazy">${m.text ? `<div class="caption">${esc(m.text)}</div>` : ""}</div>`);
      $("img", el).onclick = () => {
        const lb = h(`<div class="lightbox" role="dialog"><img src="${esc(m.media_url)}" alt="Фото"></div>`);
        lb.onclick = () => lb.remove();
        document.body.append(lb);
      };
      return el;
    }
    case "video":
      return wrap("media", `<div class="bubble"><video src="${esc(m.media_url)}" controls playsinline preload="metadata"></video></div>`);
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
      <video src="${esc(m.media_url)}" muted loop playsinline autoplay preload="metadata"></video>
      <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="none" stroke="var(--orange)" stroke-width="2.5" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg>
      <span class="dur">${fmtDur(m.duration)}</span>
    </div>${time}</div>`);
  const v = $("video", el), ring = $("circle", el);
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

function renderSettings() {
  const me = state.me;
  const step = onboardingStep(me);
  const pick = { gender: me.gender, looking_for: me.looking_for };
  const root = screen(`
    <h1>Профиль</h1>
    ${me.is_demo ? `<div class="demo-banner" style="margin-top:14px">${icons.sparkle}<span>Вы в демо-режиме. Боты отвечают в чате, данные удалятся через сутки.</span></div>` : ""}
    ${step ? `<p class="badge-warn" style="margin-top:10px">Анкета не завершена. <a href="#/feed">Продолжить настройку</a></p>` : ""}
    <div class="section profile-hero">
      ${me.photo_url ? `<img src="${esc(me.photo_url)}" alt="Ваше фото">` : "<span></span>"}
      <div class="stack" style="gap:8px">
        ${me.photo_verified ? `<span class="badge-ok">${icons.check} Фото подтверждено</span>` : `<span class="badge-warn">Фото не подтверждено</span>`}
        <button class="btn quiet" id="change-photo">Заменить фото</button>
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
    </div>

    <form class="section stack" id="profile-form">
      <h3>О себе</h3>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(me.name)}"></label>
      <label class="field"><span>Возраст</span><input class="input" name="age" type="number" min="18" max="100" value="${me.age ?? ""}"></label>
      <div class="field"><span>Я</span>${choiceGroup("gender", state.config.genders, me.gender)}</div>
      <div class="field"><span>Кого ищу</span>${choiceGroup("looking_for", state.config.looking_for, me.looking_for)}</div>
      <label class="field"><span>Описание</span><textarea class="input" name="bio" maxlength="500">${esc(me.bio)}</textarea></label>
      <label class="field"><span>Искать в радиусе <b id="dist-val">${me.max_distance_km}</b> км</span>
        <input type="range" name="dist" min="1" max="300" value="${Math.min(me.max_distance_km, 300)}"></label>
      <button type="button" class="btn ghost" id="relocate">${icons.pin} Обновить геопозицию</button>
      ${me.email ? `<label class="switch"><input type="checkbox" name="notify" ${me.email_notifications ? "checked" : ""}>
        <span class="label">Письма о парах и обновлениях<small>${esc(me.email)}</small></span></label>` : ""}
      <button class="btn block">Сохранить изменения</button>
    </form>

    <div class="section">
      <h3>Оформление</h3>
      <div class="choice-grid" style="grid-template-columns:repeat(3,1fr)" role="radiogroup" aria-label="Тема">
        ${[["dark", "Тёмная"], ["light", "Светлая"], ["system", "Как в системе"]].map(([k, l]) =>
          `<button type="button" class="chip" data-theme-pick="${k}" aria-pressed="${getThemePref() === k}">${l}</button>`).join("")}
      </div>
    </div>

    <div class="section stack">
      <a class="row-link" href="#/guide"><span><b>Как пользоваться</b><br><span class="muted small">Жесты, пары, чат и звонки</span></span>${icons.arrow}</a>
    </div>

    <div class="section stack">
      <h3>Аккаунт</h3>
      <p class="muted small">${me.is_demo ? "Демо-аккаунт без регистрации" : me.auth_provider === "telegram" ? `Вход через Telegram${me.telegram_username ? ` (@${esc(me.telegram_username)})` : ""}` : `Вход по почте ${esc(me.email)}`}</p>
      ${me.is_admin ? `<a class="btn quiet" href="/admin">Админ-панель</a>` : ""}
      ${me.is_demo ? `<button class="btn" id="leave-demo">Зарегистрироваться</button>` : ""}
      <button class="btn ghost" id="logout">Выйти</button>
      <button class="btn danger" id="delete">Удалить анкету</button>
    </div>`);

  bindChoice(root, "gender", (v) => (pick.gender = v));
  bindChoice(root, "looking_for", (v) => (pick.looking_for = v));
  $$("[data-theme-pick]", root).forEach((b) => (b.onclick = () => {
    setTheme(b.dataset.themePick);
    $$("[data-theme-pick]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  const form = $("#profile-form", root);
  form.dist.oninput = () => ($("#dist-val", root).textContent = form.dist.value);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = {
      name: form.name.value,
      age: Number(form.age.value) || undefined,
      bio: form.bio.value,
      max_distance_km: Number(form.dist.value),
      ...pick,
    };
    if (form.notify) data.email_notifications = form.notify.checked;
    try {
      state.me = await api.put("/api/profile", data);
      toast("Изменения сохранены");
    } catch (ex) { toast(ex.message, { error: true }); }
  };

  $("#relocate", root).onclick = async () => {
    try {
      await api.post("/api/profile/location", await getPosition());
      toast("Геопозиция обновлена");
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
  if (location.hash.startsWith("#/chats")) renderChats();
  api.get(`/api/chats/${m.conversation_id}?limit=1`).then((c) => {
    const text = previewText(m, state.me.id);
    toast(`${c.user.name}: ${text}`, { image: c.user.photo_url, onClick: () => go(`#/chat/${m.conversation_id}`) });
    notifyBrowser(c.user.name, text);
  }).catch(() => {});
});

function notifyBrowser(title, body) {
  if (document.hidden && "Notification" in window && Notification.permission === "granted") {
    try { new Notification(title, { body, icon: "/static/img/icon.svg" }); } catch { /* мобильные браузеры */ }
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

boot();
