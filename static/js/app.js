import { api, ApiError, connectSocket, disconnectSocket, on, send } from "./api.js";
import { initCalls, startCall } from "./call.js";
import { icons } from "./icons.js";
import { recordCircle, VoiceRecorder } from "./recorder.js";
import { runScanner } from "./scanner.js";
import { PACKS } from "./stickers.js";
import { $, $$, confirmDialog, esc, fmtDay, fmtDur, fmtShort, fmtTime, h, toast } from "./ui.js";

const app = document.getElementById("app");
const FEED_KEYS = ["dating", "sex", "friends"];
const FEED_SHORT = { dating: "Знакомства", sex: "18+", friends: "Дружба" };
const FEED_HINT = {
  dating: "Свидания и отношения",
  sex: "Без обязательств, только 18+",
  friends: "Друзья, компания, совместные планы",
};

const state = {
  config: null,
  me: null,
  feed: localStorage.getItem("feed") || "dating",
  unread: 0,
  openChat: null, // id открытого чата
  shownMatches: new Set(),
};
if (!FEED_KEYS.includes(state.feed)) state.feed = "dating";
document.body.dataset.feed = state.feed;

// ---------------- Запуск и маршрутизация ----------------

async function boot() {
  try {
    state.config = await api.get("/api/config");
  } catch {
    state.config = { feeds: FEED_SHORT, ice_servers: [] };
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
  if (!me.name || !me.age) return "about";
  if (!me.photo_url) return "photo";
  if (!me.photo_verified) return "scan";
  if (!Object.values(me.feeds).some((f) => f.enabled)) return "feeds";
  if (!me.has_location) return "location";
  return null;
}

function route() {
  closeChat();
  if (!state.me) return renderAuth();
  const step = onboardingStep(state.me);
  const [, name, arg] = location.hash.split("/");
  if (step && name !== "settings") return renderOnboarding(step);
  switch (name) {
    case "chats": return renderChats();
    case "chat": return renderChats().then(() => openChat(Number(arg)));
    case "settings": return renderSettings();
    default: return renderFeed();
  }
}

function screen(html, { nav = true } = {}) {
  app.replaceChildren(h(`<main class="screen ${nav ? "" : "no-nav"}">${html}</main>`));
  if (nav) app.append(navBar());
  return app.firstElementChild;
}

function navBar() {
  const cur = location.hash.split("/")[1] || "feed";
  const item = (key, label, icon) =>
    `<a href="#/${key}" class="${cur === key || (key === "chats" && cur === "chat") ? "on" : ""}">${icon}<span>${label}</span>${
      key === "chats" && state.unread ? `<b class="badge">${state.unread}</b>` : ""}</a>`;
  return h(`<nav class="nav" aria-label="Разделы">${item("feed", "Лента", icons.flame)}${item("chats", "Чаты", icons.chat)}${item("settings", "Профиль", icons.user)}</nav>`);
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

// ---------------- Вход и регистрация ----------------

function renderAuth(mode = "login") {
  const tg = state.config.telegram_bot_username;
  const root = screen(`
    <section class="auth-hero">
      <div class="wordmark">${esc(state.config.app_name || "Spark")}</div>
      <p>Один профиль — три ленты. Выбирайте, где вас видят: свидания, 18+ или компания на выходные.</p>
      <div class="feed-chips"><span class="feed-chip dating">Знакомства</span><span class="feed-chip sex">18+</span><span class="feed-chip friends">Дружба</span></div>
    </section>
    <div class="stack">
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
        <p class="hint" style="text-align:center">Через Telegram почта и пароль не нужны — только подтверждение фото.</p>` : ""}
    </div>`, { nav: false });

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
      ${devCode ? `<p class="hint">Режим разработки: SMTP не настроен, код — <b>${esc(devCode)}</b></p>` : ""}
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

const STEP_ORDER = ["about", "photo", "scan", "feeds", "location"];

function stepsBar(step) {
  const i = STEP_ORDER.indexOf(step);
  return `<div class="steps" aria-label="Шаг ${i + 1} из ${STEP_ORDER.length}">${STEP_ORDER.map((_, j) => `<i class="${j <= i ? "done" : ""}"></i>`).join("")}</div>`;
}

async function nextStep() {
  await reloadMe();
  route();
}

function renderOnboarding(step) {
  ({ about: stepAbout, photo: stepPhoto, scan: stepScan, feeds: stepFeeds, location: stepLocation })[step]();
}

function stepAbout() {
  const me = state.me;
  const root = screen(`${stepsBar("about")}
    <form class="stack">
      <h1>Расскажите о себе</h1>
      <p class="muted">Это общий профиль для всех лент. Позже можно задать отдельное описание для каждой.</p>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(me.name)}" required></label>
      <label class="field"><span>Возраст</span><input class="input" name="age" type="number" min="18" max="100" value="${me.age ?? ""}" required></label>
      <label class="field"><span>Коротко о себе</span><textarea class="input" name="bio" maxlength="500" placeholder="Чем увлекаетесь, что ищете, какой идеальный вечер">${esc(me.bio)}</textarea></label>
      <button class="btn block">Дальше</button>
    </form>`, { nav: false });
  $("form", root).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api.put("/api/profile", { name: f.name.value, age: Number(f.age.value), bio: f.bio.value });
      nextStep();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
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
    drop.innerHTML = `<div class="spinner"></div>`;
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
      <p class="muted">Нужно фото, где хорошо видно лицо — только ваше. Следующим шагом сверим его с камерой.</p>
      <div class="photo-drop" role="button" tabindex="0">${icons.camera}<br>Выбрать фото</div>
      <input type="file" accept="image/*" hidden>
      <p class="error-text" hidden></p>
    </div>`, { nav: false });
  $(".photo-drop svg", root).style.cssText = "width:42px;height:42px;margin:0 auto 6px";
  photoPicker(root, nextStep);
}

function stepScan() {
  const root = screen(`${stepsBar("scan")}
    <div class="stack">
      <h1>Проверка, что это вы</h1>
      <p class="muted">Камера покажет овал. Держите лицо в нём и следуйте подсказкам: смотрите прямо, затем поверните голову влево и вправо. Это защищает от чужих фото.</p>
      <div class="profile-head"><img src="${esc(state.me.photo_url)}" alt="Ваше фото"><p class="small muted">Сверяем с этим фото</p></div>
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
    $(".profile-head", root).hidden = true;
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

function feedEditor(me) {
  return `
    <label class="switch"><input type="checkbox" name="common" ${me.use_common_bio ? "checked" : ""}>
      <span class="label">Одно описание для всех лент<small>Выключите, чтобы написать о себе по-разному для каждой ленты</small></span></label>
    ${FEED_KEYS.map((k) => `
      <div class="feed-option" style="--c:var(--${k})">
        <label class="switch"><input type="checkbox" name="feed-${k}" ${me.feeds[k].enabled ? "checked" : ""}>
          <span class="label">Показывать меня в ленте «${FEED_SHORT[k]}»<small>${FEED_HINT[k]}</small></span></label>
        <textarea class="input" name="bio-${k}" maxlength="500" placeholder="Описание для ленты «${FEED_SHORT[k]}». Пусто — возьмём общее." ${me.use_common_bio ? "hidden" : ""}>${esc(me.feeds[k].bio)}</textarea>
      </div>`).join("")}`;
}

function bindFeedEditor(form) {
  const sync = () => FEED_KEYS.forEach((k) => (form[`bio-${k}`].hidden = form.common.checked));
  form.common.addEventListener("change", sync);
  sync();
}

function readFeedEditor(form) {
  return {
    use_common_bio: form.common.checked,
    feeds: Object.fromEntries(FEED_KEYS.map((k) => [k, { enabled: form[`feed-${k}`].checked, bio: form[`bio-${k}`].value }])),
  };
}

function stepFeeds() {
  const root = screen(`${stepsBar("feeds")}
    <form class="stack">
      <h1>Где вас показывать</h1>
      <p class="muted">Можно выбрать одну ленту или сразу все. Изменить это можно в любой момент в профиле.</p>
      ${feedEditor(state.me)}
      <button class="btn block">Сохранить</button>
    </form>`, { nav: false });
  const form = $("form", root);
  bindFeedEditor(form);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = readFeedEditor(form);
    if (!Object.values(data.feeds).some((f) => f.enabled)) return toast("Выберите хотя бы одну ленту", { error: true });
    try {
      await api.put("/api/profile", data);
      const first = FEED_KEYS.find((k) => data.feeds[k].enabled);
      setFeed(first);
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
      <p class="muted">Ленты показывают анкеты от ближайших к дальним, поэтому нужна ваша геопозиция. Другие видят только расстояние в километрах — точный адрес никто не узнает.</p>
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

// ---------------- Ленты ----------------

function setFeed(feed) {
  state.feed = feed;
  localStorage.setItem("feed", feed);
  document.body.dataset.feed = feed;
}

async function renderFeed() {
  const root = screen(`
    <div class="feed-head"><h1 class="feed-title">${esc(state.config.feeds[state.feed] || FEED_SHORT[state.feed])}</h1></div>
    <div class="feed-switch" role="tablist">${FEED_KEYS.map((k) =>
      `<button role="tab" data-feed="${k}" class="${k === state.feed ? "on" : ""}" aria-selected="${k === state.feed}">${FEED_SHORT[k]}</button>`).join("")}</div>
    <div class="deck" aria-live="polite"><div class="spinner"></div></div>
    <div class="swipe-actions" hidden>
      <button class="nope" aria-label="Не нравится">${icons.x}</button>
      <button class="like" aria-label="Нравится">${icons.heart}</button>
    </div>`);
  $$(".feed-switch button", root).forEach((b) => (b.onclick = () => { setFeed(b.dataset.feed); renderFeed(); }));

  const deck = $(".deck", root);
  const actions = $(".swipe-actions", root);
  let cards = [];
  let busy = false;
  let loading = false;
  const feed = state.feed;

  const empty = (title, text, btnLabel, fn) => {
    actions.hidden = true;
    deck.replaceChildren(h(`<div class="empty"><h2>${title}</h2><p class="muted">${text}</p>${btnLabel ? `<button class="btn">${btnLabel}</button>` : ""}</div>`));
    if (fn) $(".btn", deck).onclick = fn;
  };

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const res = await api.get(`/api/feed/${feed}?limit=10`);
      if (state.feed !== feed) return;
      const known = new Set(cards.map((c) => c.id));
      cards.push(...res.cards.filter((c) => !known.has(c.id)));
      draw();
    } catch (ex) {
      if (ex.code === "feed_disabled") {
        empty("Вы не показываетесь в этой ленте", "Чтобы смотреть анкеты здесь, включите показ своей анкеты в этой ленте.", "Показывать меня здесь", async () => {
          await api.put("/api/profile", { feeds: { [feed]: { enabled: true } } });
          await reloadMe();
          renderFeed();
        });
      } else if (ex.code === "need_location") {
        empty("Нужна геопозиция", "Без неё не получится найти людей рядом.", "Разрешить", async () => {
          try { await api.post("/api/profile/location", await getPosition()); renderFeed(); } catch (e) { toast(e.message, { error: true }); }
        });
      } else empty("Не удалось загрузить ленту", ex.message, "Повторить", renderFeed);
    } finally { loading = false; }
  }

  function draw() {
    if (!cards.length) {
      return empty("Рядом пока никого", `В радиусе ${state.me.max_distance_km} км новых анкет нет. Увеличьте радиус или загляните позже.`, "Изменить радиус", () => go("#/settings"));
    }
    actions.hidden = false;
    deck.replaceChildren(...cards.slice(0, 2).reverse().map((c, i, arr) => cardEl(c, i === arr.length - 1)));
    bindDrag($(".card.top", deck));
  }

  function cardEl(c, top) {
    return h(`<article class="card ${top ? "top" : ""}" style="background-image:url('${esc(c.photo_url)}')" aria-label="${esc(c.name)}, ${c.age}">
      <div class="shade"></div>
      <div class="stamp yes">ДА</div><div class="stamp no">НЕТ</div>
      <div class="info">
        <div class="name">${esc(c.name)} <span>${c.age ?? ""}</span></div>
        <div class="meta">
          ${c.verified ? `<span class="verified">${icons.check} Фото подтверждено</span>` : ""}
          ${c.distance_km != null ? `<span>${c.distance_km < 1 ? "меньше 1 км" : `${Math.round(c.distance_km)} км от вас`}</span>` : ""}
        </div>
        ${c.bio ? `<p class="bio">${esc(c.bio)}</p>` : ""}
      </div></article>`);
  }

  function bindDrag(el) {
    if (!el) return;
    let x0 = 0, y0 = 0, dx = 0, dy = 0, dragging = false;
    const yes = $(".stamp.yes", el), no = $(".stamp.no", el);
    el.addEventListener("pointerdown", (e) => {
      if (busy) return;
      dragging = true; x0 = e.clientX; y0 = e.clientY; dx = dy = 0;
      el.setPointerCapture(e.pointerId);
      el.classList.add("dragging");
    });
    el.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      dx = e.clientX - x0; dy = e.clientY - y0;
      el.style.transform = `translate(${dx}px, ${dy * 0.4}px) rotate(${dx / 18}deg)`;
      yes.style.opacity = Math.max(0, Math.min(1, dx / 100));
      no.style.opacity = Math.max(0, Math.min(1, -dx / 100));
    });
    const end = () => {
      if (!dragging) return;
      dragging = false;
      el.classList.remove("dragging");
      if (Math.abs(dx) > 110) decide(dx > 0);
      else {
        el.classList.add("anim");
        el.style.transform = "";
        yes.style.opacity = no.style.opacity = 0;
        setTimeout(() => el.classList.remove("anim"), 400);
      }
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
  }

  async function decide(like) {
    const el = $(".card.top", deck);
    const card = cards[0];
    if (!el || !card || busy) return;
    busy = true;
    $(like ? ".stamp.yes" : ".stamp.no", el).style.opacity = 1;
    el.classList.add("anim");
    el.style.transform = `translate(${like ? 140 : -140}%, 30px) rotate(${like ? 24 : -24}deg)`;
    el.style.opacity = 0;
    try {
      const res = await api.post(`/api/feed/${feed}/swipe`, { user_id: card.id, like });
      if (res.match) showMatch({ conversation_id: res.conversation_id, feed, user: res.user });
    } catch (ex) {
      toast(ex.message, { error: true });
    }
    await new Promise((r) => setTimeout(r, 250));
    cards.shift();
    busy = false;
    draw();
    if (cards.length < 3) load();
  }

  $(".nope", actions).onclick = () => decide(false);
  $(".like", actions).onclick = () => decide(true);
  const keys = (e) => {
    if (!document.body.contains(deck)) return document.removeEventListener("keydown", keys);
    if (e.target.closest("input, textarea")) return;
    if (e.key === "ArrowRight") decide(true);
    if (e.key === "ArrowLeft") decide(false);
  };
  document.addEventListener("keydown", keys);
  load();
}

function showMatch({ conversation_id, feed, user }) {
  const key = `${conversation_id}:${feed}`;
  if (state.shownMatches.has(key)) return;
  state.shownMatches.add(key);
  const el = h(`<div class="overlay" role="dialog" aria-label="Взаимная симпатия">
    <div class="match-modal">
      <div class="word">Взаимно!</div>
      <div class="pair"><img src="${esc(state.me.photo_url)}" alt="Вы"><img src="${esc(user.photo_url)}" alt="${esc(user.name)}"></div>
      <p class="muted">Вы и ${esc(user.name)} понравились друг другу в ленте «${FEED_SHORT[feed] || feed}». Теперь можно написать.</p>
      <button class="btn block" data-chat>Написать сообщение</button>
      <button class="btn ghost block" data-close>Смотреть дальше</button>
    </div></div>`);
  $("[data-chat]", el).onclick = () => { el.remove(); go(`#/chat/${conversation_id}`); };
  $("[data-close]", el).onclick = () => el.remove();
  document.body.append(el);
}

// ---------------- Чаты ----------------

function previewText(m, meId) {
  if (!m) return "Новая пара — напишите первым";
  const mine = m.sender_id === meId ? "Вы: " : "";
  const map = { image: "Фото", video: "Видео", voice: "Голосовое", circle: "Видеосообщение", sticker: m.text, call: m.text === "video" ? "Видеозвонок" : "Звонок" };
  return mine + (m.kind === "text" ? m.text : map[m.kind] || "");
}

async function renderChats() {
  const root = screen(`<h1>Чаты</h1><div id="chats"><div class="spinner"></div></div>`);
  let chats = [];
  try { chats = await api.get("/api/chats"); } catch (ex) { toast(ex.message, { error: true }); }
  state.unread = chats.reduce((s, c) => s + c.unread, 0);
  updateNavBadge();
  const box = $("#chats", root);
  if (!chats.length) {
    box.replaceChildren(h(`<div class="empty"><h2>Пока без пар</h2><p class="muted">Когда симпатия окажется взаимной, здесь появится чат.</p><a class="btn" href="#/feed">Открыть ленту</a></div>`));
    return;
  }
  const fresh = chats.filter((c) => !c.last_message);
  const talks = chats.filter((c) => c.last_message);
  const dots = (feeds) => `<span class="feed-dots">${feeds.map((f) => `<i class="${f}" title="${FEED_SHORT[f]}"></i>`).join("")}</span>`;
  box.replaceChildren(h(`<div>
    ${fresh.length ? `<div class="new-matches" aria-label="Новые пары">${fresh.map((c) =>
      `<a href="#/chat/${c.id}"><img src="${esc(c.user.photo_url)}" alt="">${esc(c.user.name)}</a>`).join("")}</div>` : ""}
    <div class="chat-list">${talks.map((c) => `
      <a class="chat-item" href="#/chat/${c.id}">
        <span class="avatar-wrap"><img class="avatar" src="${esc(c.user.photo_url)}" alt="">${c.user.online ? '<i class="dot" title="В сети"></i>' : ""}</span>
        <span class="body">
          <span class="top"><b>${esc(c.user.name)}</b>${dots(c.feeds)}<span class="time">${fmtShort(c.last_message.created_at)}</span></span>
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
      <img class="avatar" src="${esc(other.photo_url)}" alt="">
      <div class="who"><b>${esc(other.name)}${other.age ? `, ${other.age}` : ""}</b><small class="status">${other.online ? "в сети" : "не в сети"}</small></div>
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
    list.append(h(`<div class="empty" style="text-align:center"><h3>Вы понравились друг другу</h3><p class="muted small">Начните со стикера или кружочка — это проще, чем «привет».</p></div>`));
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
      <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="48" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg>
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
  const root = screen(`
    <h1>Профиль</h1>
    ${step ? `<p class="badge-warn" style="margin-top:10px">Анкета не завершена — <a href="#/feed">продолжить настройку</a></p>` : ""}
    <div class="section profile-head">
      ${me.photo_url ? `<img src="${esc(me.photo_url)}" alt="Ваше фото">` : ""}
      <div class="stack" style="gap:8px">
        ${me.photo_verified ? `<span class="badge-ok">${icons.check} Фото подтверждено</span>` : `<span class="badge-warn">Фото не подтверждено</span>`}
        <button class="btn quiet" id="change-photo">Заменить фото</button>
        <p class="hint">Новое фото снова нужно будет подтвердить камерой.</p>
      </div>
      <input type="file" accept="image/*" hidden>
    </div>

    <form class="section stack" id="profile-form">
      <h3>О себе</h3>
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(me.name)}"></label>
      <label class="field"><span>Возраст</span><input class="input" name="age" type="number" min="18" max="100" value="${me.age ?? ""}"></label>
      <label class="field"><span>Общее описание</span><textarea class="input" name="bio" maxlength="500">${esc(me.bio)}</textarea></label>
      <h3 style="margin-top:14px">Ленты</h3>
      ${feedEditor(me)}
      <h3 style="margin-top:14px">Поиск</h3>
      <label class="field"><span>Радиус поиска: <b id="dist-val">${me.max_distance_km}</b> км</span>
        <input type="range" name="dist" min="1" max="300" value="${Math.min(me.max_distance_km, 300)}"></label>
      <button type="button" class="btn ghost" id="relocate">${icons.pin} Обновить геопозицию</button>
      ${me.email ? `<label class="switch"><input type="checkbox" name="notify" ${me.email_notifications ? "checked" : ""}>
        <span class="label">Письма о метчах и обновлениях<small>${esc(me.email)}</small></span></label>` : ""}
      <button class="btn block">Сохранить изменения</button>
    </form>

    <div class="section stack">
      <h3>Аккаунт</h3>
      <p class="muted small">${me.auth_provider === "telegram" ? `Вход через Telegram${me.telegram_username ? ` (@${esc(me.telegram_username)})` : ""}` : `Вход по почте ${esc(me.email)}`}</p>
      ${me.is_admin ? `<a class="btn quiet" href="/admin">Открыть админ-панель</a>` : ""}
      <button class="btn ghost" id="logout">Выйти</button>
      <button class="btn danger" id="delete">Удалить анкету</button>
    </div>`);

  const form = $("#profile-form", root);
  bindFeedEditor(form);
  form.dist.oninput = () => ($("#dist-val", root).textContent = form.dist.value);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const data = {
      name: form.name.value,
      age: Number(form.age.value) || undefined,
      bio: form.bio.value,
      max_distance_km: Number(form.dist.value),
      ...readFeedEditor(form),
    };
    if (form.notify) data.email_notifications = form.notify.checked;
    if (!Object.values(data.feeds).some((f) => f.enabled)) return toast("Оставьте хотя бы одну ленту", { error: true });
    try {
      state.me = await api.put("/api/profile", data);
      if (!state.me.feeds[state.feed].enabled) setFeed(FEED_KEYS.find((k) => state.me.feeds[k].enabled));
      toast("Изменения сохранены");
    } catch (ex) { toast(ex.message, { error: true }); }
  };

  $("#relocate", root).onclick = async () => {
    try {
      await api.post("/api/profile/location", await getPosition());
      toast("Геопозиция обновлена");
    } catch (ex) { toast(ex.message, { error: true }); }
  };

  const input = $("input[type=file]", root);
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
  showMatch({ conversation_id: d.conversation_id, feed: d.feed, user: d.user });
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

boot();
