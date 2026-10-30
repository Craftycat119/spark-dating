import { api } from "./api.js";
import { icons } from "./icons.js";
import { $, $$, confirmDialog, esc, h, toast } from "./ui.js";

const view = $("#view");
const drawer = $("#drawer");
const usersState = { q: "", interest: "", page: 1 };
let catalog = [];

const dt = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short" }) : "—");
const tags = (items, cls = "") => items.map((f) => `<span class="tag ${cls}">${esc(f)}</span>`).join("");
const mapLink = (lat, lon) => (lat == null ? "—" : `<a href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=12/${lat}/${lon}" target="_blank" rel="noopener">${lat.toFixed(4)}, ${lon.toFixed(4)}</a>`);

async function boot() {
  try {
    const me = await api.get("/api/auth/me");
    if (!me.is_admin) throw new Error();
    catalog = (await api.get("/api/config")).survey.slice(1).flatMap((q) => q.options);
  } catch {
    view.innerHTML = `<h1>Нет доступа</h1><p class="muted">Войдите в приложение под аккаунтом администратора.</p><p style="margin-top:16px"><a class="btn" href="/">Войти</a></p>`;
    $(".rail nav").hidden = true;
    return;
  }
  window.addEventListener("hashchange", route);
  route();
}

function route() {
  const [name, arg] = (location.hash.slice(1) || "overview").split("/");
  $$(".rail nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === name));
  closeDrawer();
  ({ overview, users, chats, mail })[name]?.(arg) ?? overview();
}

// ---------- Обзор ----------
async function overview() {
  const s = await api.get("/api/admin/stats");
  const max = Math.max(1, ...s.top_interests.map((x) => x.count));
  view.innerHTML = `<h1>Обзор</h1>
    <div class="kpis">
      <div><b>${s.users}</b><span>Всего анкет</span></div>
      <div><b>${s.new_24h}</b><span>Новых за сутки</span></div>
      <div><b>${s.verified}</b><span>С подтверждённым фото</span></div>
      <div><b>${s.online}</b><span>Сейчас в сети</span></div>
      <div><b>${s.matches}</b><span>Пар</span></div>
      <div><b>${s.messages}</b><span>Сообщений</span></div>
      <div><b>${s.banned}</b><span>Заблокировано</span></div>
    </div>
    <h3 style="margin-top:32px">Популярные интересы</h3>
    <div class="feed-bars">${s.top_interests.map((x) => `
      <div class="r"><span>${esc(x.name)}</span><div class="track"><div class="fill" style="width:${(x.count / max) * 100}%"></div></div><b>${x.count}</b></div>`).join("") || '<p class="muted">Пока нет данных</p>'}
    </div>`;
}

// ---------- Анкеты ----------
async function users() {
  view.innerHTML = `<h1>Анкеты</h1>
    <div class="toolbar">
      <input class="input" type="search" placeholder="Имя, почта, @telegram или ID" value="${esc(usersState.q)}">
      <select class="input"><option value="">Любые интересы</option>${catalog.map((k) => `<option ${usersState.interest === k ? "selected" : ""}>${esc(k)}</option>`).join("")}</select>
    </div>
    <div id="table"><div class="spinner"></div></div>`;
  const search = $("input", view);
  let t;
  search.oninput = () => { clearTimeout(t); t = setTimeout(() => { usersState.q = search.value; usersState.page = 1; loadUsers(); }, 300); };
  $("select", view).onchange = (e) => { usersState.interest = e.target.value; usersState.page = 1; loadUsers(); };
  loadUsers();
}

async function loadUsers() {
  const p = new URLSearchParams({ q: usersState.q, interest: usersState.interest, page: usersState.page, per_page: 30 });
  const res = await api.get(`/api/admin/users?${p}`);
  const box = $("#table");
  if (!box) return;
  if (!res.items.length) {
    box.innerHTML = `<p class="muted">Никого не нашли. Попробуйте другой запрос.</p>`;
    return;
  }
  const pages = Math.ceil(res.total / res.per_page);
  box.innerHTML = `<table class="grid"><thead><tr>
      <th></th><th>Имя</th><th>Вход</th><th>Регистрация</th><th>IP</th><th>Ищет</th><th>Статус</th></tr></thead>
    <tbody>${res.items.map((u) => `<tr data-id="${u.id}">
      <td>${u.photo_url ? `<img src="${esc(u.photo_url)}" alt="">` : ""}</td>
      <td><b>${esc(u.name || "Без имени")}</b>${u.age ? `, ${u.age}` : ""}<br><span class="muted small">#${u.id}</span></td>
      <td>${u.email ? esc(u.email) : u.telegram_username ? `@${esc(u.telegram_username)}` : `Telegram ${u.telegram_id}`}</td>
      <td>${dt(u.created_at)}</td>
      <td>${esc(u.registration_ip || "—")}</td>
      <td>${tags(u.goals)}</td>
      <td>${u.is_banned ? '<span class="tag warn">Заблокирован</span>' : ""}${u.photo_verified ? '<span class="tag ok">Фото ✓</span>' : '<span class="tag warn">Фото не проверено</span>'}${u.online ? '<span class="tag ok">В сети</span>' : ""}</td>
    </tr>`).join("")}</tbody></table>
    <div class="pager"><button data-p="-1" ${usersState.page <= 1 ? "disabled" : ""}>Назад</button>
      <span>Страница ${usersState.page} из ${pages} · всего ${res.total}</span>
      <button data-p="1" ${usersState.page >= pages ? "disabled" : ""}>Вперёд</button></div>`;
  $$("tbody tr", box).forEach((tr) => (tr.onclick = () => openUser(Number(tr.dataset.id))));
  $$("[data-p]", box).forEach((b) => (b.onclick = () => { usersState.page += Number(b.dataset.p); loadUsers(); }));
}

function closeDrawer() { drawer.hidden = true; drawer.innerHTML = ""; }

async function openUser(id) {
  const u = await api.get(`/api/admin/users/${id}`);
  drawer.hidden = false;
  drawer.innerHTML = `
    <button class="icon-btn close" aria-label="Закрыть">${icons.x}</button>
    <h2>${esc(u.name || "Без имени")}${u.age ? `, ${u.age}` : ""}</h2>
    <p class="muted small">#${u.id} · ${u.online ? "в сети" : `был(а) ${dt(u.last_seen_at)}`}</p>
    <div class="photos">
      <figure><img src="${esc(u.photo_url || "")}" alt=""><figcaption>Фото анкеты</figcaption></figure>
      <figure><img src="${esc(u.selfie_url || "")}" alt=""><figcaption>Кадр со сканера${u.face_score != null ? `, сходство ${u.face_score.toFixed(2)}` : ""}</figcaption></figure>
    </div>
    <div class="actions">
      <button class="btn quiet" data-ban>${u.is_banned ? "Разблокировать" : "Заблокировать"}</button>
      <button class="btn quiet" data-reverify>Сбросить проверку фото</button>
      <button class="btn danger" data-delete>Удалить анкету</button>
    </div>
    <h3>Регистрация</h3>
    <dl class="kv">
      <dt>Когда</dt><dd>${dt(u.created_at)}</dd>
      <dt>Способ</dt><dd>${u.auth_provider === "telegram" ? `Telegram ${u.telegram_username ? "@" + esc(u.telegram_username) : ""} (ID ${u.telegram_id})` : "Почта"}</dd>
      <dt>Почта</dt><dd>${esc(u.email || "—")} ${u.email ? (u.email_verified ? '<span class="tag ok">подтверждена</span>' : '<span class="tag warn">не подтверждена</span>') : ""}</dd>
      <dt>IP при регистрации</dt><dd>${esc(u.registration_ip || "—")}</dd>
      <dt>Место регистрации</dt><dd>${mapLink(u.registration_lat, u.registration_lon)}</dd>
      <dt>Текущее место</dt><dd>${mapLink(u.lat, u.lon)} <span class="muted small">${u.location_updated_at ? dt(u.location_updated_at) : ""}</span></dd>
      <dt>Устройство</dt><dd class="small muted">${esc(u.registration_user_agent || "—")}</dd>
      <dt>Фото подтверждено</dt><dd>${u.photo_verified ? dt(u.photo_verified_at) : "нет"}</dd>
      <dt>Лайки</dt><dd>поставил(а) ${u.likes_given}, получил(а) ${u.likes_received}</dd>
      <dt>Последние входы</dt><dd>${u.sessions.map((s) => `${esc(s.ip || "?")}, ${dt(s.created_at)}`).join("<br>") || "—"}</dd>
    </dl>
    <h3>Анкета</h3>
    <dl class="kv">
      <dt>Пол</dt><dd>${esc(u.gender || "—")}</dd>
      <dt>Кого ищет</dt><dd>${esc(u.looking_for || "—")}</dd>
      <dt>Цель</dt><dd>${tags(u.goals, "hot") || "—"}</dd>
      <dt>Интересы</dt><dd>${tags(u.interests) || "—"}</dd>
      <dt>О себе</dt><dd>${esc(u.bio || "—")}</dd>
    </dl>
    <h3>Переписки (${u.conversations.length})</h3>
    <div>${u.conversations.map((c) => convRow(c)).join("") || '<p class="muted small">Пар пока нет</p>'}</div>`;
  $(".close", drawer).onclick = closeDrawer;
  $$(".conv-row", drawer).forEach((r) => (r.onclick = () => openConversation(Number(r.dataset.id))));
  $("[data-ban]", drawer).onclick = async () => {
    try {
      await api.post(`/api/admin/users/${id}/ban`, { banned: !u.is_banned });
      toast(u.is_banned ? "Пользователь разблокирован" : "Пользователь заблокирован");
      openUser(id); loadUsers();
    } catch (e) { toast(e.message, { error: true }); }
  };
  $("[data-reverify]", drawer).onclick = async () => {
    await api.post(`/api/admin/users/${id}/reset-verification`);
    toast("Проверка сброшена. Анкета скрыта до повторного сканирования");
    openUser(id); loadUsers();
  };
  $("[data-delete]", drawer).onclick = async () => {
    if (!(await confirmDialog(`Удалить анкету «${u.name}» со всеми чатами и файлами?`, "Удалить анкету"))) return;
    try {
      await api.del(`/api/admin/users/${id}`);
      toast("Анкета удалена");
      closeDrawer(); loadUsers();
    } catch (e) { toast(e.message, { error: true }); }
  };
}

function convRow(c) {
  return `<div class="conv-row" data-id="${c.id}">
    ${c.users.map((x) => `<img src="${esc(x.photo_url || "")}" alt="">`).join("")}
    <span style="flex:1">${c.users.map((x) => esc(x.name)).join(" и ")}<br><span class="muted">${c.messages} сообщ.</span> ${c.active ? "" : '<span class="tag warn">пара удалена</span>'}</span>
    <span class="muted">${dt(c.last_message_at || c.created_at)}</span></div>`;
}

// ---------- Переписки ----------
async function chats(arg) {
  view.innerHTML = `<h1>Переписки</h1><div id="convs"><div class="spinner"></div></div>`;
  const list = await api.get("/api/admin/conversations");
  $("#convs").innerHTML = list.map(convRow).join("") || '<p class="muted">Переписок пока нет.</p>';
  $$(".conv-row", view).forEach((r) => (r.onclick = () => openConversation(Number(r.dataset.id))));
  if (arg) openConversation(Number(arg));
}

async function openConversation(id) {
  const c = await api.get(`/api/admin/conversations/${id}`);
  const [a] = c.users;
  const names = Object.fromEntries(c.users.map((u) => [u.id, u.name]));
  const body = (m) => {
    switch (m.kind) {
      case "image": return `<a href="${esc(m.media_url)}" target="_blank"><img src="${esc(m.media_url)}" alt="Фото"></a>`;
      case "video": return `<video src="${esc(m.media_url)}" controls preload="metadata"></video>`;
      case "circle": return `<video class="circlev" src="${esc(m.media_url)}" controls preload="metadata"></video>`;
      case "voice": return `<audio src="${esc(m.media_url)}" controls preload="none"></audio>`;
      case "sticker": return `<span style="font-size:48px">${esc(m.text)}</span>`;
      case "call": return `<div class="bubble">${m.text === "video" ? "Видеозвонок" : "Аудиозвонок"}</div>`;
      default: return `<div class="bubble">${esc(m.text)}</div>`;
    }
  };
  drawer.hidden = false;
  drawer.innerHTML = `<button class="icon-btn close" aria-label="Закрыть">${icons.x}</button>
    <h2>${c.users.map((u) => esc(u.name)).join(" и ")}</h2>
    <p class="muted small">Пара с ${dt(c.created_at)}</p>
    <div class="transcript">${c.items.map((m) => `<div class="msg ${m.sender_id === a.id ? "" : "mine"}">
      <div class="who">${esc(names[m.sender_id] || "?")} · ${dt(m.created_at)}</div>${body(m)}</div>`).join("") || '<p class="muted">Сообщений нет</p>'}</div>`;
  $(".close", drawer).onclick = closeDrawer;
}

// ---------- Рассылка ----------
function mail() {
  view.innerHTML = `<h1>Рассылка</h1>
    <form class="stack" style="max-width:560px">
      <p class="muted">Письмо уйдёт всем с подтверждённой почтой, кто не отключил рассылку в настройках. Пользователи Telegram без почты его не получат.</p>
      <label class="field"><span>Тема</span><input class="input" name="subject" maxlength="200" required placeholder="Например: в COFI появились кружочки"></label>
      <label class="field"><span>Текст</span><textarea class="input" name="body" rows="10" required></textarea></label>
      <button class="btn">Отправить рассылку</button>
    </form>`;
  $("form", view).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    if (!(await confirmDialog("Отправить письмо всем подписчикам?", "Отправить"))) return;
    try {
      const r = await api.post("/api/admin/broadcast", { subject: f.subject.value, body: f.body.value });
      toast(`Рассылка поставлена в очередь: ${r.recipients} получателей`);
      f.reset();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
}

boot();
