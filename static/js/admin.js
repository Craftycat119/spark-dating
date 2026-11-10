import { api, connectSocket, on } from "./api.js";
import "./theme.js";
import { icons } from "./icons.js";
import { $, $$, confirmDialog, esc, toast } from "./ui.js";

const view = $("#view");
const drawer = $("#drawer");
const usersState = { q: "", interest: "", page: 1 };
let catalog = [];
let cfg = {}; // настройки приложения: пол, сексуальность, знаки, опрос — для форм редактирования

// Время в админке — в часовом поясе статистики (STATS_TZ_HOURS, по умолчанию Вьетнам), а не компьютера, с которого открыли
let adminTz;
const dt = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU", { dateStyle: "medium", timeStyle: "short", timeZone: adminTz }) : "—");
const tags = (items, cls = "") => items.map((f) => `<span class="tag ${cls}">${esc(f)}</span>`).join("");
const mapLink = (lat, lon) => (lat == null ? "—" : `<a href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=12/${lat}/${lon}" target="_blank" rel="noopener">${lat.toFixed(4)}, ${lon.toFixed(4)}</a>`);

async function boot() {
  try {
    const me = await api.get("/api/auth/me");
    if (!me.is_admin) throw new Error();
    cfg = await api.get("/api/config");
    const h = cfg.stats_tz_hours ?? 7;
    adminTz = h === 0 ? "UTC" : `Etc/GMT${h > 0 ? "-" : "+"}${Math.abs(h)}`; // у Etc/GMT знак наоборот: GMT-7 = UTC+7
    catalog = cfg.survey.slice(1).flatMap((q) => q.options);
  } catch {
    view.innerHTML = `<h1>Нет доступа</h1><p class="muted">Войдите в приложение под аккаунтом администратора.</p><p style="margin-top:16px"><a class="btn" href="/">Войти</a></p>`;
    $(".rail nav").hidden = true;
    return;
  }
  window.addEventListener("hashchange", route);
  connectSocket();
  route();
  api.get("/api/admin/help-requests?status=new").then((r) => setHelpBadge(r.new)).catch(() => {});
}

function route() {
  const [name, arg] = (location.hash.slice(1) || "overview").split("/");
  $$(".rail nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === name));
  closeDrawer();
  ({ overview, users, chats, mail, support, animals })[name]?.(arg) ?? overview();
}

// ---------- Обзор ----------
async function overview() {
  const s = await api.get("/api/admin/stats");
  const max = Math.max(1, ...s.top_interests.map((x) => x.count));
  const a = s.audience;
  view.innerHTML = `<h1>Обзор</h1>
    <h3>Аудитория <span class="muted small">без ботов и гостей демо · время UTC${(cfg.stats_tz_hours ?? 7) >= 0 ? "+" : ""}${cfg.stats_tz_hours ?? 7}${(cfg.stats_tz_hours ?? 7) === 7 ? " (Вьетнам)" : ""}</span></h3>
    <div class="kpis">
      <div><b>${a.registered}</b><span>Зарегистрировано</span></div>
      <div><b>${a.online}</b><span>Сейчас онлайн</span></div>
    </div>
    <table class="grid audience">
      <thead><tr><th>Период</th><th>Заходили (уникальные)</th><th>Посещений</th><th>Новых регистраций</th></tr></thead>
      <tbody>${a.periods.map((p) => `<tr><td>${p.label}</td><td><b>${p.unique}</b></td><td>${p.visits}</td><td>${p.new}</td></tr>`).join("")}</tbody>
    </table>
    <p class="muted small">Уникальные — сколько разных людей открывали COFI. Посещение — заход после перерыва больше 30 минут, один человек может зайти несколько раз в день. Сутки считаются по московскому времени.</p>
    <h3 style="margin-top:28px">Активность</h3>
    <div class="kpis">
      <div><b>${s.users}</b><span>Всего анкет (с ботами и демо)</span></div>
      <div><b>${s.verified}</b><span>С подтверждённым фото</span></div>
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
    <details class="add-admin">
      <summary>${icons.plus} Добавить администратора</summary>
      <form class="stack">
        <p class="muted small">Анкету заполнять не нужно: только имя и значок «Администрация». Укажите почту и пароль для входа
          или @username человека, который уже входил в COFI через Telegram.</p>
        <input class="input" name="name" placeholder="Имя" required maxlength="64">
        <div class="row" style="gap:8px;flex-wrap:wrap">
          <input class="input" name="email" type="email" placeholder="Почта" style="flex:1;min-width:180px">
          <input class="input" name="password" type="text" placeholder="Пароль (8+ символов, заглавная, цифра)" style="flex:1;min-width:180px">
        </div>
        <input class="input" name="telegram" placeholder="…или Telegram: @username">
        <button class="btn">Добавить</button>
      </form>
    </details>
    <div id="table"><div class="spinner"></div></div>`;
  $(".add-admin form", view).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      const u = await api.post("/api/admin/admins", { name: f.name.value, email: f.email.value, password: f.password.value, telegram: f.telegram.value });
      toast(`${u.name} теперь администратор`);
      f.reset();
      loadUsers();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
  const search = $("input[type=search]", view);
  let t;
  search.oninput = () => { clearTimeout(t); t = setTimeout(() => { usersState.q = search.value; usersState.page = 1; loadUsers(); }, 300); };
  $(".toolbar select", view).onchange = (e) => { usersState.interest = e.target.value; usersState.page = 1; loadUsers(); };
  loadUsers();
}

// Список анкет обновляется сам: раз в 20 секунд и при возвращении на вкладку,
// иначе удалённые пользователями анкеты оставались в таблице до перезагрузки страницы
let usersTimer = null;
function watchUsers() {
  clearInterval(usersTimer);
  usersTimer = setInterval(() => (document.hidden || !$("#table") ? null : loadUsers()), 20000);
}
document.addEventListener("visibilitychange", () => !document.hidden && $("#table") && loadUsers());

async function loadUsers() {
  watchUsers();
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
      <th></th><th>Имя</th><th>Дата рождения</th><th>Вход</th><th>Регистрация</th><th>IP</th><th>Ищет</th><th>Статус</th></tr></thead>
    <tbody>${res.items.map((u) => `<tr data-id="${u.id}">
      <td>${pic(u.photo_url, "", true)}</td>
      <td><b>${esc(u.name || "Без имени")}</b>${u.is_admin ? ' <span class="tag hot">Админ</span>' : ""}<br><span class="muted small">#${u.id}</span></td>
      <td>${u.birth_date ? `${new Date(u.birth_date).toLocaleDateString("ru-RU")}<br><span class="muted small">${u.age} ${plural(u.age, "год", "года", "лет")}</span>` : '<span class="muted">—</span>'}</td>
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

const plural = (n, one, few, many) => {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
};

/** Фото или аккуратная заглушка: пустой src давал значок «битой» картинки. */
// Фото не загрузилось — заглушка «Файл не найден» (без встроенного onerror: его запрещает CSP)
document.addEventListener("error", (e) => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || !img.dataset.fallback) return;
  img.replaceWith(Object.assign(document.createElement("div"), { className: `pic-empty${img.dataset.fallback === "small" ? " small" : ""}`, textContent: "Файл не найден" }));
}, true);

function pic(url, empty, small = false) {
  if (!url) return small ? `<span class="pic-empty small">${icons.user}</span>` : `<div class="pic-empty">${icons.user}<span>${esc(empty)}</span></div>`;
  return `<img src="${esc(url)}" alt="" loading="lazy" data-fallback="${small ? "small" : "big"}">`;
}

function closeDrawer() { drawer.hidden = true; drawer.innerHTML = ""; }

async function openUser(id) {
  let u;
  try {
    u = await api.get(`/api/admin/users/${id}`);
  } catch (e) {
    toast(e.status === 404 ? "Эта анкета уже удалена" : e.message, { error: e.status !== 404 });
    closeDrawer();
    return loadUsers();
  }
  drawer.hidden = false;
  drawer.innerHTML = `
    <button class="icon-btn close" aria-label="Закрыть">${icons.x}</button>
    <h2>${esc(u.name || "Без имени")}${u.age > 0 ? `, ${u.age}` : ""}</h2>
    <p class="muted small">#${u.id} · ${u.online ? "в сети" : `был(а) ${dt(u.last_seen_at)}`}</p>
    <div class="photos">
      <figure>${pic(u.photo_url, "Фото ещё не загружено")}<figcaption>Фото анкеты
        <span class="photo-tools"><button class="link" data-photo-replace>Заменить</button>${u.photo_url ? `<button class="link danger-link" data-photo-remove>Удалить</button>` : ""}</span></figcaption></figure>
      <figure>${pic(u.selfie_url, "Проверку лица ещё не проходил(а)")}<figcaption>Кадр со сканера${u.face_score != null ? `, сходство ${u.face_score.toFixed(2)}` : ""}</figcaption></figure>
    </div>
    <div class="photos gallery-admin">${u.gallery_items.map((g) => `<figure><a href="${esc(g.url)}" target="_blank"><img src="${esc(g.url)}" alt=""></a>
      <button class="icon-btn tiny-x" data-gallery-del="${g.id}" aria-label="Удалить фото">${icons.x}</button></figure>`).join("")}
      ${u.gallery_items.length < 6 ? `<button class="add-photo" data-gallery-add>${icons.plus}<span>Фото в галерею</span></button>` : ""}</div>
    <input type="file" accept="image/*" hidden data-file-main><input type="file" accept="image/*" hidden data-file-gallery>
    <div class="actions">
      <button class="btn" data-edit>Редактировать анкету</button>
      ${u.photo_url && !u.photo_verified ? `<button class="btn quiet" data-verify-photo>Подтвердить фото вручную</button>` : ""}
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
      <dt>Дата рождения</dt><dd>${u.birth_date && u.age < 0
        ? `<span class="tag warn">${new Date(u.birth_date).toLocaleDateString("ru-RU")} — дата в будущем, исправьте ниже</span>`
        : u.birth_date
        ? `${new Date(u.birth_date).toLocaleDateString("ru-RU")}, ${u.age} ${plural(u.age, "год", "года", "лет")} <span class="tag">${u.age_group === "teen" ? "14–17, «Дружба»" : "18+, «Знакомства»"}</span>`
        : '<span class="muted">не указана: человек ещё не прошёл шаг «Знакомимся»</span>'}
        ${u.age_verified ? '<span class="tag ok">проверен по документу</span>' : ""}
        <form class="row" data-birth style="margin-top:8px;gap:8px"><input class="input" type="date" name="d" value="${u.birth_date || ""}" style="padding:8px 10px;max-width:170px">
        <button class="btn quiet" style="min-height:38px;padding:0 14px;font-size:13px">Исправить и отметить проверенным</button></form></dd>
      <dt>Пол</dt><dd>${esc(u.gender_label || "—")}${u.show_identity === false ? ' <span class="muted small">(скрыт в анкете)</span>' : ""}</dd>
      <dt>Сексуальность</dt><dd>${esc(u.orientation_label || "—")}${u.show_orientation === false ? ' <span class="muted small">(скрыта в анкете)</span>' : ""}</dd>
      <dt>Кого ищет</dt><dd>${esc(u.looking_for_label || "—")}</dd>
      <dt>Цель</dt><dd>${tags(u.goals, "hot") || "—"}</dd>
      <dt>Интересы</dt><dd>${tags(u.interests) || "—"}</dd>
      <dt>О себе</dt><dd>${esc(u.bio || "—")}</dd>
    </dl>
    <h3>Переписки (${u.conversations.length})</h3>
    <div>${u.conversations.map((c) => convRow(c)).join("") || '<p class="muted small">Пар пока нет</p>'}</div>`;
  $(".close", drawer).onclick = closeDrawer;
  const run = async (fn, ok) => { try { await fn(); toast(ok); openUser(id); loadUsers(); } catch (ex) { toast(ex.message, { error: true }); } };
  const upload = (input, url, extra = {}) => {
    input.onchange = () => {
      if (!input.files[0]) return;
      const fd = new FormData();
      fd.append("file", input.files[0]);
      for (const [k, v] of Object.entries(extra)) fd.append(k, v);
      run(() => api.post(url, fd), "Фото загружено");
    };
    input.click();
  };
  $("[data-edit]", drawer).onclick = () => editUser(u);
  $("[data-verify-photo]", drawer)?.addEventListener("click", () => run(() => api.post(`/api/admin/users/${id}/verify-photo`), "Фото подтверждено, анкета видна в ленте"));
  $("[data-photo-replace]", drawer).onclick = async () => {
    const keep = u.photo_verified && await confirmDialog("Оставить отметку «фото подтверждено»? Если нет, человеку придётся снова пройти сканер", "Оставить отметку");
    upload($("[data-file-main]", drawer), `/api/admin/users/${id}/photo`, { keep_verified: keep ? "true" : "false" });
  };
  $("[data-photo-remove]", drawer)?.addEventListener("click", async () => {
    if (await confirmDialog("Удалить фото анкеты? Анкета скроется из ленты, пока человек не загрузит новое", "Удалить фото")) run(() => api.del(`/api/admin/users/${id}/photo`), "Фото удалено");
  });
  $("[data-gallery-add]", drawer)?.addEventListener("click", () => upload($("[data-file-gallery]", drawer), `/api/admin/users/${id}/photos`));
  $$("[data-gallery-del]", drawer).forEach((b) => (b.onclick = async () => {
    if (await confirmDialog("Удалить это фото из галереи?", "Удалить")) run(() => api.del(`/api/admin/users/${id}/photos/${b.dataset.galleryDel}`), "Фото удалено");
  }));
  $("[data-birth]", drawer).onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api.post(`/api/admin/users/${id}/birth-date`, { birth_date: e.target.d.value, verified: true });
      toast("Дата рождения обновлена");
      openUser(id);
    } catch (ex) { toast(ex.message, { error: true }); }
  };
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

/** Форма редактирования анкеты: те же поля и правила, что у самого человека. */
function editUser(u) {
  const pr = u.profile;
  const teen = u.age_group === "teen";
  const opts = (map, value, empty) => (empty ? `<option value="">${empty}</option>` : "") +
    Object.entries(map).map(([k, l]) => `<option value="${esc(k)}" ${k === value ? "selected" : ""}>${esc(l)}</option>`).join("");
  const goals = teen ? cfg.teen_goals : cfg.survey[0].options;
  const sexOptions = (gender) => {
    const keys = cfg.orientations_by_gender?.[gender] || Object.keys(cfg.orientations);
    // без согласия человека новую сексуальность поставить нельзя — только оставить текущую или убрать
    const allowed = pr.consent_sexuality ? keys : keys.filter((k) => k === pr.orientation);
    return opts(Object.fromEntries(allowed.map((k) => [k, cfg.orientations[k]])), pr.orientation, "не указана");
  };
  drawer.innerHTML = `
    <button class="icon-btn close" aria-label="Закрыть">${icons.x}</button>
    <h2>Редактирование: ${esc(u.name || "без имени")}</h2>
    <p class="muted small">#${u.id}. Дата рождения меняется в карточке анкеты, согласия за человека дать нельзя.</p>
    <form class="stack edit-form">
      <label class="field"><span>Имя</span><input class="input" name="name" maxlength="64" value="${esc(u.name || "")}"></label>
      <label class="field"><span>О себе</span><textarea class="input" name="bio" rows="5" maxlength="500">${esc(u.bio || "")}</textarea></label>
      <div class="grid2">
        <label class="field"><span>Пол</span><select class="input" name="gender">${opts(teen ? cfg.teen_genders : cfg.genders, pr.gender, "—")}</select></label>
        <label class="field"><span>Кого ищет</span><select class="input" name="looking_for">${opts(cfg.looking_for, pr.looking_for, "—")}</select></label>
        ${teen ? "" : `<label class="field"><span>Сексуальность${pr.consent_sexuality ? "" : " <small class=\"muted\">(нет согласия: можно только убрать)</small>"}</span><select class="input" name="orientation">${sexOptions(pr.gender)}</select></label>`}
        <label class="field"><span>Знак зодиака</span><select class="input" name="zodiac">${opts(cfg.zodiac, pr.zodiac, "—")}</select></label>
        <label class="field"><span>Рост, см</span><input class="input" type="number" name="height_cm" min="100" max="250" value="${pr.height_cm ?? ""}"></label>
        ${teen ? "" : `<label class="field"><span>Вес, кг</span><input class="input" type="number" name="weight_kg" min="30" max="250" value="${pr.weight_kg ?? ""}"></label>`}
        <label class="field"><span>Радиус поиска, км</span><input class="input" type="number" name="max_distance_km" min="1" max="20000" value="${pr.max_distance_km ?? 50}"></label>
      </div>
      <label class="check-row"><input type="checkbox" name="show_identity" ${pr.show_identity !== false ? "checked" : ""}> Показывать пол в анкете</label>
      ${teen ? "" : `<label class="check-row"><input type="checkbox" name="show_orientation" ${pr.show_orientation !== false ? "checked" : ""}> Показывать сексуальность</label>`}
      <div class="field"><span>Что ищет</span><div class="checks">${goals.map((g) => `<label class="chip"><input type="checkbox" name="goals" value="${esc(g)}" ${u.goals.includes(g) ? "checked" : ""}> ${esc(g)}</label>`).join("")}</div></div>
      <div class="field"><span>Интересы <small class="muted">(не меньше ${cfg.min_interests})</small></span>
        ${cfg.survey.slice(1).map((q) => `<details class="int-group" ${q.options.some((o) => u.interests.includes(o)) ? "open" : ""}><summary>${esc(q.title)}</summary><div class="checks">${q.options.map((o) =>
          `<label class="chip"><input type="checkbox" name="interests" value="${esc(o)}" ${u.interests.includes(o) ? "checked" : ""}> ${esc(o)}</label>`).join("")}</div></details>`).join("")}</div>
      <div class="row" style="gap:10px"><button class="btn">Сохранить</button><button type="button" class="btn quiet" data-cancel>Отмена</button></div>
    </form>`;
  const f = $(".edit-form", drawer);
  $(".close", drawer).onclick = closeDrawer;
  $("[data-cancel]", drawer).onclick = () => openUser(u.id);
  f.gender.onchange = () => { if (f.orientation) f.orientation.innerHTML = sexOptions(f.gender.value); };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const num = (el) => (el && el.value !== "" ? Number(el.value) : el ? 0 : undefined);
    const data = {
      name: f.name.value, bio: f.bio.value, gender: f.gender.value || undefined, looking_for: f.looking_for.value || undefined,
      zodiac: f.zodiac.value, height_cm: num(f.height_cm), weight_kg: num(f.weight_kg), max_distance_km: num(f.max_distance_km) || undefined,
      show_identity: f.show_identity.checked, show_orientation: f.show_orientation?.checked,
      goals: [...f.querySelectorAll("[name=goals]:checked")].map((x) => x.value),
      interests: [...f.querySelectorAll("[name=interests]:checked")].map((x) => x.value),
    };
    if (f.orientation) data.orientation = f.orientation.value;
    try {
      await api.put(`/api/admin/users/${u.id}/profile`, data);
      toast("Анкета сохранена");
      openUser(u.id);
      loadUsers();
    } catch (ex) { toast(ex.message, { error: true }); }
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

// ---------- Обращения: поддержка и реклама ----------
const CAT = { help: "Помощь", complaint: "Жалоба", suggestion: "Предложение", ads: "Реклама" };
const supportState = { topic: "", status: "open" };

async function support(arg) {
  view.innerHTML = `<h1>Обращения</h1>
    <div class="toolbar">
      <select class="input" data-topic><option value="">Все разделы</option><option value="support">Поддержка</option><option value="ads">Реклама</option></select>
      <select class="input" data-status><option value="open">Открытые</option><option value="closed">Решённые</option><option value="">Все</option></select>
    </div>
    <div id="threads"><div class="spinner"></div></div>`;
  $("[data-topic]", view).value = supportState.topic;
  $("[data-status]", view).value = supportState.status;
  $("[data-topic]", view).onchange = (e) => { supportState.topic = e.target.value; loadThreads(); };
  $("[data-status]", view).onchange = (e) => { supportState.status = e.target.value; loadThreads(); };
  await loadThreads();
  if (arg) openThread(Number(arg));
}

async function loadThreads() {
  const list = await api.get(`/api/admin/support?topic=${supportState.topic}&status=${supportState.status}`);
  const box = $("#threads");
  if (!box) return;
  box.innerHTML = list.map((t) => `<div class="conv-row" data-id="${t.id}">
      <span class="tag ${t.topic === "ads" ? "hot" : t.category === "complaint" ? "warn" : ""}">${CAT[t.category]}</span>
      <span style="flex:1"><b>${t.user ? esc(t.user.name || t.user.email || "#" + t.user.id) : "Гость" + (t.contact ? `, ${esc(t.contact)}` : "")}</b> №${t.id}
      ${t.user && (t.user.telegram_username || t.user.email) ? `<span class="muted small"> · ${esc(t.user.telegram_username ? "@" + t.user.telegram_username : t.user.email)}</span>` : ""}<br>
      <span class="muted">${t.last ? esc(((t.last.author === "user" ? "" : t.last.author === "staff" ? "Вы: " : "Бот: ") + t.last.text).slice(0, 90)) : ""}</span></span>
      <span class="muted">${dt(t.updated_at)}</span></div>`).join("") || '<p class="muted">Обращений нет.</p>';
  $$(".conv-row", box).forEach((r) => (r.onclick = () => openThread(Number(r.dataset.id))));
}

/** Telegram и почта автора обращения: ссылками, чтобы ответить в один клик. */
function contactLinks(t) {
  const u = t.user || {};
  const items = [];
  if (u.telegram_username) items.push(`<a href="https://t.me/${encodeURIComponent(u.telegram_username)}" target="_blank" rel="noopener">Telegram @${esc(u.telegram_username)}</a>`);
  else if (u.telegram_id) items.push(`<span>Telegram id ${esc(String(u.telegram_id))} (без username)</span>`);
  if (u.email) items.push(`<a href="mailto:${esc(u.email)}">${esc(u.email)}</a>`);
  if (t.contact) items.push(`<span>Контакт: ${esc(t.contact)}</span>`);
  return items.length ? items.join("") : '<span class="muted">Контактов нет: ответить можно только здесь</span>';
}

async function openThread(id) {
  const t = await api.get(`/api/admin/support/${id}`);
  const who = { user: t.user ? t.user.name || "Пользователь" : "Гость", bot: "Бот", staff: "Вы" };
  drawer.hidden = false;
  drawer.innerHTML = `<button class="icon-btn close" aria-label="Закрыть">${icons.x}</button>
    <h2>${CAT[t.category]} №${t.id}</h2>
    <div class="sender">${t.user ? `<b>${esc(t.user.name || "Без имени")}</b> <a href="#users" data-user="${t.user.id}">#${t.user.id}</a>` : "<b>Гость без аккаунта</b>"}
      ${contactLinks(t)}
      ${t.about_user_id ? `<span>Жалоба на <a href="#users" data-user="${t.about_user_id}">анкету #${t.about_user_id}</a></span>` : ""}</div>
    <div class="transcript">${t.messages.map((m) => `<div class="msg ${m.author === "staff" ? "mine" : ""}">
      <div class="who">${esc(who[m.author])} · ${dt(m.created_at)}</div><div class="bubble">${esc(m.text)}</div></div>`).join("")}</div>
    <form class="stack" style="margin-top:16px" data-reply>
      <textarea class="input" name="text" rows="3" placeholder="Ответ пользователю" required></textarea>
      <div class="row"><button class="btn">Ответить</button>
      <button type="button" class="btn quiet" data-close-thread>${t.status === "open" ? "Отметить решённым" : "Открыть снова"}</button></div>
    </form>`;
  $(".close", drawer).onclick = closeDrawer;
  $$("[data-user]", drawer).forEach((a) => (a.onclick = (e) => { e.preventDefault(); openUser(Number(a.dataset.user)); }));
  $("[data-reply]", drawer).onsubmit = async (e) => {
    e.preventDefault();
    await api.post(`/api/admin/support/${id}/reply`, { text: e.target.text.value });
    openThread(id);
    loadThreads();
  };
  $("[data-close-thread]", drawer).onclick = async () => {
    await api.post(`/api/admin/support/${id}/status`, { status: t.status === "open" ? "closed" : "open" });
    closeDrawer();
    loadThreads();
  };
  const tr = $(".transcript", drawer);
  tr.lastElementChild?.scrollIntoView({ block: "end" });
}

// новые сообщения в обращениях приходят в реальном времени
on("support", (d) => {
  if (!d.admin) return;
  if (location.hash.startsWith("#support")) loadThreads();
  const open = $(".drawer h2");
  if (open && open.textContent.endsWith(`№${d.thread_id}`)) openThread(d.thread_id);
  else toast(`Новое сообщение в обращении №${d.thread_id}`);
});

// ---------- Питомцы: объявления добавляет только администрация ----------
const PET_CATS = { adoption: "Ищет хозяина", foster: "Передержка", charity: "Помощь и сборы" };

async function animals() {
  view.innerHTML = `<h1>Питомцы</h1>
    <details class="pet-form">
      <summary class="btn">${icons.plus} Добавить объявление</summary>
      <form class="stack" style="max-width:640px;margin-top:16px">
        <div class="row" style="gap:8px;flex-wrap:wrap">${Object.entries(PET_CATS).map(([k, l], i) =>
          `<label class="chip"><input type="radio" name="category" value="${k}" ${i ? "" : "checked"}> ${l}</label>`).join("")}</div>
        <div class="row" style="gap:10px;align-items:flex-start">
          <label class="field" style="flex:2"><span>Кличка или название</span><input class="input" name="name" maxlength="64" required></label>
          <label class="field" style="flex:1"><span>Кто это</span><select class="input" name="species"><option>Кошка</option><option>Собака</option><option>Другое</option></select></label>
        </div>
        <div class="row" style="gap:10px;align-items:flex-start">
          <label class="field" style="flex:1"><span>Возраст</span><input class="input" name="age_text" maxlength="32" placeholder="2 года"></label>
          <label class="field" style="flex:1"><span>Город</span><input class="input" name="city" maxlength="64" value="Москва"></label>
          <label class="field" style="flex:1" data-goal><span>Цель сбора</span><input class="input" name="fundraising_goal" maxlength="64" placeholder="20 000 ₽"></label>
        </div>
        <label class="field"><span>Описание</span><textarea class="input" name="description" rows="6" maxlength="3000"></textarea></label>
        <label class="field"><span>Telegram для заявок</span><input class="input" name="contact" maxlength="128" required placeholder="@username или t.me/… группы"></label>
        <label class="field"><span>Фото, до 5</span><input type="file" name="photos" accept="image/*" multiple></label>
        <button class="btn">Опубликовать</button>
      </form>
    </details>
    <h3 style="margin-top:22px">Заявки «Помочь» из приложения</h3>
    <div class="toolbar"><select class="input" data-help-status><option value="new">Новые</option><option value="done">Обработанные</option><option value="">Все</option></select></div>
    <div id="help-requests"><div class="spinner"></div></div>
    <h3 style="margin-top:22px">Объявления</h3>
    <div id="pets"><div class="spinner"></div></div>`;
  $("[data-help-status]", view).value = helpState.status;
  $("[data-help-status]", view).onchange = (e) => { helpState.status = e.target.value; loadHelp(); };
  loadHelp();
  const form = $(".pet-form form", view);
  const syncGoal = () => ($("[data-goal]", form).hidden = form.category.value !== "charity");
  $$("input[name=category]", form).forEach((r) => (r.onchange = syncGoal));
  syncGoal();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const files = [...form.photos.files];
    if (files.length > 5) return toast("Не больше 5 фото", { error: true });
    const fd = new FormData();
    for (const k of ["category", "name", "species", "age_text", "city", "description", "contact"]) fd.append(k, form[k].value);
    if (form.category.value === "charity") fd.append("fundraising_goal", form.fundraising_goal.value);
    files.forEach((f) => fd.append("files", f));
    try {
      await api.post("/api/animals", fd);
      toast("Объявление опубликовано");
      form.reset();
      syncGoal();
      loadPets();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
  loadPets();
}

const helpState = { status: "new" };

async function loadHelp() {
  const res = await api.get(`/api/admin/help-requests?status=${helpState.status}`);
  setHelpBadge(res.new);
  const box = $("#help-requests");
  if (!box) return;
  const who = (u) => (u ? `${esc(u.name || "Без имени")} <a href="#users" data-user="${u.id}">#${u.id}</a>` : "Анкета удалена");
  box.innerHTML = res.items.length ? `<table class="grid"><thead><tr><th>Когда</th><th>Объявление</th><th>Кто</th><th>Связь</th><th>Сообщение</th><th></th></tr></thead><tbody>
    ${res.items.map((r) => `<tr class="${r.status === "new" ? "row-new" : ""}"><td class="small">${dt(r.created_at)}</td>
      <td>${r.post ? `<b>${esc(r.post.name)}</b><br><span class="muted small">${esc(r.post.category)}</span>` : "Удалено"}</td>
      <td>${who(r.user)}</td>
      <td>${esc(r.contact || "—")}${r.user?.telegram_username ? `<br><a href="https://t.me/${encodeURIComponent(r.user.telegram_username)}" target="_blank" rel="noopener">написать в Telegram</a>` : ""}</td>
      <td>${esc(r.message || "—")}</td>
      <td><button class="btn ${r.status === "new" ? "dark" : "quiet"} tiny" data-help="${r.id}" data-st="${r.status}">${r.status === "new" ? "Обработано" : "Вернуть в новые"}</button></td></tr>`).join("")}</tbody></table>`
    : `<p class="muted">${helpState.status === "new" ? "Новых заявок нет." : "Заявок нет."}</p>`;
  $$("[data-help]", box).forEach((b) => (b.onclick = async () => {
    await api.post(`/api/admin/help-requests/${b.dataset.help}/status`, { status: b.dataset.st === "new" ? "done" : "new" });
    loadHelp();
  }));
  $$("[data-user]", box).forEach((a) => (a.onclick = (e) => { e.preventDefault(); openUser(Number(a.dataset.user)); }));
}

/** Число новых заявок рядом с «Питомцы» в меню. */
function setHelpBadge(n) {
  const a = $('.rail nav a[data-view="animals"]');
  if (a) a.innerHTML = `Питомцы${n ? ` <span class="nav-badge">${n}</span>` : ""}`;
}

// заявка «Помочь» из приложения появляется сразу
on("help_request", (d) => {
  toast(`Заявка «Помочь»: ${d.from || "пользователь"} → ${d.post}`);
  if (location.hash.startsWith("#animals")) loadHelp();
  else api.get("/api/admin/help-requests?status=new").then((r) => setHelpBadge(r.new)).catch(() => {});
});

async function loadPets() {
  const list = await api.get("/api/admin/animals");
  const box = $("#pets");
  if (!box) return;
  box.innerHTML = list.length ? `<table class="grid"><thead><tr><th></th><th>Кличка</th><th>Категория</th><th>Telegram</th><th>Заявки</th><th>Сбор</th><th>Публикация</th><th></th></tr></thead><tbody>
    ${list.map((p) => `<tr><td>${p.photos[0] ? `<img src="${esc(p.photos[0])}" alt="">` : ""}</td><td><b>${esc(p.name)}</b><br><span class="muted small">${dt(p.created_at)}</span></td>
      <td>${esc(p.category)}</td><td>${esc(p.contact)}</td><td>${p.requests}</td>
      <td>${p.fundraising_open === null ? "—" : `<button class="btn ${p.fundraising_open ? "quiet" : "dark"} tiny" data-fund="${p.id}" data-open="${p.fundraising_open}">${p.fundraising_open ? "Открыт: закрыть" : "Закрыт: открыть"}</button>`}</td>
      <td><button class="btn quiet tiny" data-active="${p.id}" data-on="${p.active}">${p.active ? "Снять" : "Вернуть"}</button></td>
      <td><button class="btn quiet tiny" data-edit-pet="${p.id}">Изменить</button> <button class="btn danger tiny" data-del="${p.id}">Удалить</button></td></tr>`).join("")}</tbody></table>`
    : '<p class="muted">Объявлений пока нет. Добавьте первое кнопкой выше.</p>';
  $$("[data-fund]", box).forEach((b) => (b.onclick = async () => {
    await api.patch(`/api/animals/${b.dataset.fund}`, { fundraising_open: b.dataset.open !== "true" });
    loadPets();
  }));
  $$("[data-active]", box).forEach((b) => (b.onclick = async () => {
    await api.patch(`/api/animals/${b.dataset.active}`, { active: b.dataset.on !== "true" });
    loadPets();
  }));
  $$("[data-edit-pet]", box).forEach((b) => (b.onclick = () => editPet(Number(b.dataset.editPet))));
  $$("[data-del]", box).forEach((b) => (b.onclick = async () => {
    if (!(await confirmDialog("Удалить объявление вместе с фото?", "Удалить"))) return;
    await api.del(`/api/admin/animals/${b.dataset.del}`);
    loadPets();
  }));
}

/** Редактор объявления о питомце: все поля, порядок и состав фото. */
async function editPet(id) {
  let p;
  try { p = await api.get(`/api/animals/${id}`); } catch (ex) { return toast(ex.message, { error: true }); }
  drawer.hidden = false;
  drawer.innerHTML = `
    <button class="icon-btn close" aria-label="Закрыть">${icons.x}</button>
    <h2>${esc(p.name)}</h2>
    <p class="muted small">Первое фото видно в ленте</p>
    <div class="photos pet-admin-photos">${p.photos.map((url, i) => `<figure><img src="${esc(url)}" alt="">
      <figcaption>${i === 0 ? '<span class="tag hot">В ленте</span>' : `<button class="link" data-first="${i}">Сделать первым</button>`}
      <button class="link danger-link" data-del-photo="${i}">Удалить</button></figcaption></figure>`).join("")}
      ${p.photos.length < 5 ? `<button class="add-photo" data-add-photos>${icons.plus}<span>Добавить фото</span></button>` : ""}</div>
    <input type="file" accept="image/*" multiple hidden data-pet-files>
    <form class="stack edit-form">
      <div class="row" style="gap:8px;flex-wrap:wrap">${Object.entries(PET_CATS).map(([k, l]) =>
        `<label class="chip"><input type="radio" name="category" value="${k}" ${p.category === k ? "checked" : ""}> ${l}</label>`).join("")}</div>
      <div class="grid2">
        <label class="field"><span>Кличка или название</span><input class="input" name="name" maxlength="64" required value="${esc(p.name)}"></label>
        <label class="field"><span>Кто это</span><input class="input" name="species" maxlength="32" value="${esc(p.species || "")}"></label>
        <label class="field"><span>Возраст</span><input class="input" name="age_text" maxlength="32" value="${esc(p.age_text || "")}"></label>
        <label class="field"><span>Город</span><input class="input" name="city" maxlength="64" value="${esc(p.city || "")}"></label>
        <label class="field"><span>Telegram для связи <small class="muted">(можно пусто)</small></span><input class="input" name="contact" maxlength="128" value="${esc(p.contact || "")}" placeholder="@username"></label>
        <label class="field" data-goal><span>Цель сбора</span><input class="input" name="fundraising_goal" maxlength="64" value="${esc(p.fundraising_goal || "")}"></label>
      </div>
      <label class="field"><span>Описание</span><textarea class="input" name="description" rows="12" maxlength="3000">${esc(p.description || "")}</textarea></label>
      <div class="row" style="gap:10px"><button class="btn">Сохранить</button><button type="button" class="btn quiet" data-cancel>Закрыть</button></div>
    </form>`;
  const f = $(".edit-form", drawer);
  const syncGoal = () => ($("[data-goal]", f).hidden = f.category.value !== "charity");
  $$("input[name=category]", f).forEach((r) => (r.onchange = syncGoal));
  syncGoal();
  $(".close", drawer).onclick = closeDrawer;
  $("[data-cancel]", drawer).onclick = closeDrawer;
  const act = async (fn, ok) => { try { await fn(); toast(ok); editPet(id); loadPets(); } catch (ex) { toast(ex.message, { error: true }); } };
  $$("[data-first]", drawer).forEach((b) => (b.onclick = () => act(() => api.post(`/api/animals/${id}/photos/${b.dataset.first}/first`), "Фото стало первым")));
  $$("[data-del-photo]", drawer).forEach((b) => (b.onclick = async () => {
    if (await confirmDialog("Удалить это фото?", "Удалить")) act(() => api.del(`/api/animals/${id}/photos/${b.dataset.delPhoto}`), "Фото удалено");
  }));
  const input = $("[data-pet-files]", drawer);
  $("[data-add-photos]", drawer)?.addEventListener("click", () => input.click());
  input.onchange = () => {
    const fd = new FormData();
    [...input.files].forEach((file) => fd.append("files", file));
    act(() => api.post(`/api/animals/${id}/photos`, fd), "Фото добавлены");
  };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(["name", "species", "age_text", "city", "contact", "description", "fundraising_goal"].map((k) => [k, f[k].value]));
    data.category = f.category.value;
    try {
      await api.patch(`/api/animals/${id}`, data);
      toast("Объявление сохранено");
      loadPets();
      editPet(id);
    } catch (ex) { toast(ex.message, { error: true }); }
  };
}

// ---------- Рассылка ----------
function mail() {
  view.innerHTML = `<h1>Рассылка</h1>
    <form class="stack" style="max-width:560px">
      <p class="muted">Сообщение придёт через Telegram-бота всем, у кого подключён Telegram и включены уведомления. На почту рассылки не отправляются: почтой уходят только коды входа.</p>
      <label class="field"><span>Тема</span><input class="input" name="subject" maxlength="200" required placeholder="Например: в COFI появились кружочки"></label>
      <label class="field"><span>Текст</span><textarea class="input" name="body" rows="10" required></textarea></label>
      <button class="btn">Отправить рассылку</button>
    </form>`;
  $("form", view).onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    if (!(await confirmDialog("Отправить сообщение всем в Telegram?", "Отправить"))) return;
    try {
      const r = await api.post("/api/admin/broadcast", { subject: f.subject.value, body: f.body.value });
      toast(`Рассылка поставлена в очередь: ${r.recipients} получателей`);
      f.reset();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
}

boot();
