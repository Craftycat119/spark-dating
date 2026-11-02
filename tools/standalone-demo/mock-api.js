// Имитация сервера COFI прямо в браузере: тот же интерфейс, что у static/js/api.js.
// Логика повторяет app/routers: подбор по интересам, свайпы, пары, чаты, ответы ботов.
import DATA from "./data.json";
import { portraitFor, sceneFor, petFor, fileToDataUrl } from "./images.js";

export class ApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string" ? detail : detail?.message || "Ошибка";
    super(message);
    this.status = status;
    this.detail = detail;
    this.code = typeof detail === "object" ? detail?.code : undefined;
  }
}

const KEY = "cofi-demo-state-v1";
const REPLY_DELAY = 2200;
const now = () => new Date().toISOString().replace(/Z$/, "") + "Z";

// ---------- события вместо WebSocket ----------
const listeners = new Map();
export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}
function emit(type, data) {
  setTimeout(() => {
    listeners.get(type)?.forEach((fn) => fn({ type, ...data }));
  }, 0);
}
export function connectSocket() {}
export function disconnectSocket() {}
export function send(payload) {
  if (payload.type === "call:offer") {
    setTimeout(() => emit("call:unavailable", { conversation_id: payload.conversation_id, call_id: payload.call_id, reason: "bot" }), 400);
  }
  return true;
}

// ---------- состояние ----------
function fresh() {
  return { seq: 100, me: null, accounts: {}, users: {}, swipes: [], convs: [], messages: [], pets: null, threads: [], smsgs: [] };
}
let S = load();
function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw);
      s.messages = s.messages.filter((m) => !(m.media_url || "").startsWith("blob:")); // видео не переживает перезагрузку
      return { ...fresh(), ...s };
    }
  } catch { /* приватный режим */ }
  return fresh();
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(S)); } catch { /* не страшно */ }
}
const id = () => ++S.seq;
const me = () => (S.me ? S.users[S.me] : null);
const deny = (status, detail) => { throw new ApiError(status, detail); };

// ---------- подбор (как app/interests.py) ----------
function matchScore(a, ag, b, bg) {
  const set = new Set(a);
  const common = b.filter((x) => set.has(x));
  const interestPart = common.length / (Math.min(a.length, b.length) || 1);
  const g = new Set(ag);
  const goalCommon = bg.filter((x) => g.has(x)).length;
  const goalPart = ag.length && bg.length ? goalCommon / Math.min(ag.length, bg.length) : 0;
  return [Math.round(100 * (0.8 * interestPart + 0.2 * goalPart)), common];
}
const ok = (looking, g) => !looking || looking === "any" || looking === g;
const compatible = (u, o) => ok(u.looking_for, o.gender) && ok(o.looking_for, u.gender);
function km(a, b) {
  const R = 6371, rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// ---------- сериализация (как app/serializers.py) ----------
function years(u) {
  if (!u.birth_date) return u.age ?? null;
  const b = new Date(u.birth_date), n = new Date();
  return n.getFullYear() - b.getFullYear() - (n < new Date(n.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0);
}
function group(u) {
  const y = years(u);
  return y == null || y < DATA.min_age ? null : y >= 18 ? "adult" : "teen";
}
function birthFor(age) {
  const d = new Date();
  d.setFullYear(d.getFullYear() - age);
  return d.toISOString().slice(0, 10);
}
function isComplete(u) {
  return !!(u.name && group(u) && u.gender && u.looking_for && u.interests.length >= DATA.min_interests && u.goals.length && u.photo_url && u.photo_verified);
}
function ownProfile(u) {
  return {
    id: u.id, email: u.email || null, email_verified: true, email_notifications: false,
    auth_provider: u.provider || (u.is_demo ? "demo" : "email"), telegram_username: u.telegram_username || null, name: u.name, age: years(u), birth_date: u.birth_date || null, age_group: group(u),
    age_verified: false, language: "ru", bio: u.bio, gender: u.gender, looking_for: u.looking_for,
    interests: u.interests, goals: u.goals, survey_done: u.interests.length >= DATA.min_interests && u.goals.length > 0,
    photo_url: u.photo_url, photos: u.photos, photo_verified: u.photo_verified, has_location: true,
    max_distance_km: u.max_distance_km, is_admin: false, is_complete: isComplete(u), is_demo: true,
  };
}
function messageOut(m) {
  return { id: m.id, conversation_id: m.conversation_id, sender_id: m.sender_id, kind: m.kind, text: m.text,
    media_url: m.media_url || null, duration: m.duration ?? null, created_at: m.created_at, read_at: m.read_at || null };
}

// ---------- боты ----------
async function ensureBots() {
  if (Object.values(S.users).some((u) => u.is_bot && u.key?.startsWith("teen_"))) return;
  for (const u of Object.values(S.users)) if (u.is_bot) delete S.users[u.id]; // старое сохранение без подростков
  for (const b of [...DATA.bots, ...DATA.teen_bots]) {
    const uid = id();
    S.users[uid] = {
      id: uid, key: b.key, is_bot: true, name: b.name, age: b.age, birth_date: birthFor(b.age), gender: b.gender, looking_for: "any", bio: b.bio,
      goals: b.goals, interests: b.interests, lat: DATA.center[0] + b.km[0] / 111, lon: DATA.center[1] + b.km[1] / 63,
      photo_url: `@portrait:${b.key}`, photos: b.scenes.map((sc, i) => ({ id: uid * 10 + i, url: `@scene:${sc}` })),
      photo_verified: true, likes_you: b.likes_you, replies: b.replies,
    };
  }
}
// Фото генерируются на лету (внешние картинки на странице по ссылке не грузятся)
async function img(ref) {
  if (!ref || !ref.startsWith("@")) return ref;
  const [kind, key] = ref.slice(1).split(":");
  if (kind === "portrait") {
    const b = Object.values(S.users).find((u) => u.key === key);
    return portraitFor(key, b?.name || "?");
  }
  return sceneFor(key);
}
async function photos(u) {
  return Promise.all(u.photos.map(async (p) => ({ id: p.id, url: await img(p.url) })));
}

function botReply(conv, bot, greeting = false) {
  const sent = S.messages.filter((m) => m.conversation_id === conv.id && m.sender_id === bot.id);
  if (greeting && sent.length) return;
  const text = sent.length < bot.replies.length ? bot.replies[sent.length] : group(bot) === "teen" ? DATA.teen_fallback : DATA.fallback_reply;
  setTimeout(() => emit("typing", { conversation_id: conv.id }), REPLY_DELAY * 0.4);
  setTimeout(() => {
    if (!conv.active) return;
    const m = { id: id(), conversation_id: conv.id, sender_id: bot.id, kind: "text", text, created_at: now() };
    S.messages.push(m);
    conv.last_message_at = m.created_at;
    save();
    emit("message", { message: messageOut(m) });
  }, REPLY_DELAY);
}

// ---------- маршруты ----------
const ROUTES = [];
const route = (method, pattern, fn) => ROUTES.push({ method, re: new RegExp(`^${pattern}$`), fn });

route("GET", "/api/config", () => ({
  app_name: "COFI", survey: DATA.survey, genders: DATA.genders, looking_for: DATA.looking_for, teen_goals: DATA.teen_goals,
  min_age: DATA.min_age, min_interests: DATA.min_interests, telegram_bot_username: "cofi_bot", ice_servers: [], face_dev_mode: true,
}));

route("GET", "/api/auth/me", () => (me() ? ownProfile(me()) : deny(401, "Нужно войти в аккаунт")));

route("POST", "/api/auth/demo", async (body) => {
  await ensureBots();
  const uid = id();
  const teen = !!body?.teen;
  const g = teen ? DATA.teen_guest : DATA.guest;
  S.users[uid] = { id: uid, is_demo: true, name: g.name, age: g.age, birth_date: birthFor(g.age), gender: g.gender, looking_for: g.looking_for, bio: g.bio,
    goals: g.goals, interests: g.interests, lat: DATA.center[0], lon: DATA.center[1], max_distance_km: 50,
    photo_url: await portraitFor(teen ? "guest-teen" : "guest", g.name), photos: [], photo_verified: true };
  for (const b of Object.values(S.users)) if (b.is_bot && b.likes_you && group(b) === group(S.users[uid])) S.swipes.push({ from: b.id, to: uid, liked: true });
  S.me = uid;
  save();
  return ownProfile(S.users[uid]);
});

const PASSWORD_RULES = (p) => [
  p.length < 8 && "Пароль должен быть не короче 8 символов",
  !/\p{Lu}/u.test(p) && "Нужна хотя бы одна заглавная буква",
  !/\d/.test(p) && "Нужна хотя бы одна цифра",
].filter(Boolean);

route("POST", "/api/auth/register", async (b) => {
  const email = (b.email || "").trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) deny(422, "Некорректная почта");
  const errs = PASSWORD_RULES(b.password || "");
  if (errs.length) deny(422, errs.join("; "));
  if (S.accounts[email]?.verified) deny(409, "Аккаунт с этой почтой уже существует, войдите");
  S.accounts[email] = { password: b.password, verified: false, code: "246810" };
  save();
  return { status: "code_sent", email, dev_code: "246810" };
});
route("POST", "/api/auth/resend-code", (b) => ({ status: "code_sent", email: b.email, dev_code: "246810" }));
route("POST", "/api/auth/verify-email", async (b) => {
  const acc = S.accounts[(b.email || "").toLowerCase()];
  if (!acc) deny(404, "Аккаунт не найден");
  if (b.code !== acc.code) deny(400, "Неверный код");
  acc.verified = true;
  return loginAs(b.email.toLowerCase());
});
async function loginAs(email) {
  await ensureBots();
  const acc = S.accounts[email];
  if (!acc.userId) {
    const uid = id();
    // в демо геопозиция и проверка фото не нужны: браузер на странице не даёт камеру и геолокацию
    S.users[uid] = { id: uid, is_demo: true, email, name: "", age: null, birth_date: null, gender: null, looking_for: null, bio: "",
      goals: [], interests: [], lat: DATA.center[0], lon: DATA.center[1], max_distance_km: 50, photo_url: null, photos: [], photo_verified: false };
    acc.userId = uid;
  }
  S.me = acc.userId;
  save();
  return ownProfile(me());
}
route("POST", "/api/auth/login", (b) => {
  const email = (b.email || "").trim().toLowerCase();
  const acc = S.accounts[email];
  if (!acc || acc.password !== b.password) deny(401, "Неверная почта или пароль. В демо войдите кнопкой «Демо без регистрации»");
  if (!acc.verified) deny(403, { code: "email_not_verified", message: "Подтвердите почту", dev_code: acc.code });
  return loginAs(email);
});
route("POST", "/api/auth/forgot-password", (b) => ({ status: "code_sent", email: b.email, dev_code: "246810" }));
route("POST", "/api/auth/reset-password", (b) => {
  const acc = S.accounts[(b.email || "").toLowerCase()];
  if (!acc || b.code !== "246810") deny(400, "Неверный код");
  acc.password = b.password;
  acc.verified = true;
  return loginAs(b.email.toLowerCase());
});
// Вход через Telegram: в демо приходит имитация данных виджета (настоящий Telegram на странице по ссылке недоступен)
route("POST", "/api/auth/telegram", async (b) => {
  await ensureBots();
  const key = `tg:${b.id}`;
  if (!S.accounts[key]) {
    const uid = id();
    S.users[uid] = { id: uid, is_demo: true, provider: "telegram", telegram_username: b.username || null, name: (b.first_name || "").slice(0, 64),
      age: null, birth_date: null, gender: null, looking_for: null, bio: "", goals: [], interests: [], lat: DATA.center[0], lon: DATA.center[1],
      max_distance_km: 50, photo_url: null, photos: [], photo_verified: false };
    S.accounts[key] = { userId: uid, verified: true };
  }
  S.me = S.accounts[key].userId;
  save();
  return ownProfile(me());
});
route("POST", "/api/auth/logout", () => { S.me = null; save(); return { status: "ok" }; });

function requireMe() {
  const u = me();
  if (!u) deny(401, "Нужно войти в аккаунт");
  return u;
}

route("GET", "/api/profile", () => ownProfile(requireMe()));
route("PUT", "/api/profile", (b) => {
  const u = requireMe();
  if (b.name !== undefined) { if (!b.name.trim()) deny(422, "Укажите имя"); u.name = b.name.trim().slice(0, 64); }
  if (b.birth_date !== undefined && b.birth_date !== u.birth_date) {
    if (u.birth_date) deny(403, "Дату рождения можно изменить только через поддержку");
    const y = years({ birth_date: b.birth_date });
    if (y < DATA.min_age) deny(422, `COFI доступен с ${DATA.min_age} лет`);
    u.birth_date = b.birth_date;
    if (group(u) === "teen") { u.goals = u.goals.filter((g) => DATA.teen_goals.includes(g)); u.looking_for = "any"; }
    // боты своей возрастной группы, которые «уже лайкнули», как у гостя демо
    for (const o of Object.values(S.users)) {
      if (o.is_bot && o.likes_you && group(o) === group(u) && !S.swipes.some((s) => s.from === o.id && s.to === u.id)) S.swipes.push({ from: o.id, to: u.id, liked: true });
    }
  }
  if (b.bio !== undefined) u.bio = b.bio.trim().slice(0, 500);
  if (b.gender !== undefined) u.gender = b.gender;
  if (b.looking_for !== undefined) u.looking_for = b.looking_for;
  if (b.interests !== undefined) {
    const v = [...new Set(b.interests)];
    if (v.length < DATA.min_interests) deny(422, `Выберите хотя бы ${DATA.min_interests} интереса`);
    u.interests = v;
  }
  if (b.goals !== undefined) {
    if (group(u) === "teen" && b.goals.some((g) => !DATA.teen_goals.includes(g))) deny(422, "В 14–17 лет доступна только дружба");
    if (!b.goals.length) deny(422, "Выберите, что вы ищете");
    u.goals = [...new Set(b.goals)];
  }
  if (b.max_distance_km !== undefined) u.max_distance_km = Math.max(1, Math.min(b.max_distance_km, 20000));
  save();
  return ownProfile(u);
});
route("POST", "/api/profile/photo", async (fd) => {
  const u = requireMe();
  u.photo_url = await fileToDataUrl(fd.get("file"), 900);
  u.photo_verified = true; // в демо без сканера: камера на странице недоступна
  save();
  return ownProfile(u);
});
route("POST", "/api/profile/photos", async (fd) => {
  const u = requireMe();
  if (u.photos.length >= 6) deny(400, "Можно добавить не больше 6 фото");
  u.photos.push({ id: id(), url: await fileToDataUrl(fd.get("file"), 900) });
  save();
  return ownProfile(u);
});
route("DELETE", "/api/profile/photos/(\\d+)", (_, [pid]) => {
  const u = requireMe();
  u.photos = u.photos.filter((p) => p.id !== +pid);
  save();
  return ownProfile(u);
});
route("POST", "/api/profile/verify-face", () => ({ ok: true, score: 1, reason: "", profile: ownProfile(requireMe()) }));
route("POST", "/api/profile/location", () => ({ status: "ok" }));
route("DELETE", "/api/profile", () => { S = fresh(); save(); return { status: "deleted" }; });

function visibleBots(u) {
  // боты взрослые: подростку в демо их не показываем, как и в приложении
  return Object.values(S.users).filter((o) => o.is_bot && group(o) === group(u) && compatible(u, o));
}

route("GET", "/api/feed", async () => {
  const u = requireMe();
  if (!isComplete(u)) deny(409, { code: "profile_incomplete", message: "Заполните анкету" });
  const swiped = new Set(S.swipes.filter((s) => s.from === u.id).map((s) => s.to));
  const scored = [];
  for (const o of visibleBots(u)) {
    if (swiped.has(o.id)) continue;
    const d = km(u, o);
    if (d > u.max_distance_km) continue;
    const [score, common] = matchScore(u.interests, u.goals, o.interests, o.goals);
    scored.push({ score, d, common, o });
  }
  scored.sort((a, b) => Math.floor(b.score / 10) - Math.floor(a.score / 10) || a.d - b.d);
  const cards = await Promise.all(scored.slice(0, 10).map(async ({ score, d, common, o }) => ({
    id: o.id, name: o.name, age: years(o), bio: o.bio, photo_url: await img(o.photo_url), verified: true,
    interests: o.interests, goals: o.goals, photos_count: o.photos.length, match: score, common, distance_km: Math.round(d * 10) / 10,
  })));
  return { total: scored.length, cards };
});

route("POST", "/api/feed/swipe", async (b) => {
  const u = requireMe();
  const t = S.users[b.user_id];
  if (!t || !t.is_bot) deny(404, "Анкета больше не доступна");
  S.swipes = S.swipes.filter((s) => !(s.from === u.id && s.to === t.id));
  S.swipes.push({ from: u.id, to: t.id, liked: !!b.like });
  save();
  if (!b.like || !S.swipes.some((s) => s.from === t.id && s.to === u.id && s.liked)) return { match: false };
  let conv = S.convs.find((c) => c.users.includes(u.id) && c.users.includes(t.id));
  const isNew = !conv || !conv.active;
  if (!conv) { conv = { id: id(), users: [u.id, t.id], created_at: now(), active: true }; S.convs.push(conv); }
  conv.active = true;
  save();
  const [score, common] = matchScore(u.interests, u.goals, t.interests, t.goals);
  if (isNew) botReply(conv, t, true);
  return { match: true, conversation_id: conv.id, user: { id: t.id, name: t.name, age: t.age, photo_url: await img(t.photo_url), common, match: score } };
});

route("GET", "/api/users/(\\d+)", async (_, [uidStr]) => {
  const u = requireMe();
  const o = S.users[+uidStr];
  if (!o || !o.is_bot) deny(404, "Анкета не найдена");
  const conv = S.convs.find((c) => c.active && c.users.includes(u.id) && c.users.includes(o.id));
  const [score, common] = matchScore(u.interests, u.goals, o.interests, o.goals);
  const gallery = await photos(o);
  return {
    id: o.id, name: o.name, age: o.age, bio: o.bio, verified: true,
    photos: [await img(o.photo_url), ...gallery.map((p) => p.url)],
    interests: o.interests, goals: o.goals, common, match: score, distance_km: Math.round(km(u, o) * 10) / 10,
    online: false, liked: S.swipes.some((s) => s.from === u.id && s.to === o.id && s.liked), conversation_id: conv ? conv.id : null,
  };
});

function convFor(u, cid) {
  const c = S.convs.find((x) => x.id === +cid);
  if (!c || !c.active || !c.users.includes(u.id)) deny(404, "Чат не найден");
  return c;
}
async function userBrief(o) {
  return { id: o.id, name: o.name, age: o.age, bio: o.bio, photo_url: await img(o.photo_url), online: false };
}

route("GET", "/api/chats", async () => {
  const u = requireMe();
  const out = [];
  for (const c of S.convs.filter((x) => x.active && x.users.includes(u.id))) {
    const msgs = S.messages.filter((m) => m.conversation_id === c.id);
    const other = S.users[c.users.find((x) => x !== u.id)];
    out.push({ id: c.id, active: true, user: await userBrief(other), last_message: msgs.length ? messageOut(msgs[msgs.length - 1]) : null,
      unread: msgs.filter((m) => m.sender_id !== u.id && !m.read_at).length, created_at: c.created_at });
  }
  return out.sort((a, b) => ((b.last_message?.created_at || b.created_at) > (a.last_message?.created_at || a.created_at) ? 1 : -1));
});
route("GET", "/api/chats/(\\d+)", async (_, [cid]) => {
  const u = requireMe();
  const c = convFor(u, cid);
  const other = S.users[c.users.find((x) => x !== u.id)];
  return { id: c.id, user: await userBrief(other), messages: S.messages.filter((m) => m.conversation_id === c.id).map(messageOut) };
});
route("POST", "/api/chats/(\\d+)/messages", (b, [cid]) => {
  const u = requireMe();
  const c = convFor(u, cid);
  const text = (b.text || "").trim();
  if (!text) deny(422, "Пустое сообщение");
  const m = { id: id(), conversation_id: c.id, sender_id: u.id, kind: b.kind || "text", text, created_at: now() };
  S.messages.push(m);
  save();
  emit("message", { message: messageOut(m) });
  botReply(c, S.users[c.users.find((x) => x !== u.id)]);
  return messageOut(m);
});
route("POST", "/api/chats/(\\d+)/media", async (fd, [cid]) => {
  const u = requireMe();
  const c = convFor(u, cid);
  const kind = fd.get("kind");
  const file = fd.get("file");
  const url = kind === "image" ? await fileToDataUrl(file, 1200) : URL.createObjectURL(file);
  const m = { id: id(), conversation_id: c.id, sender_id: u.id, kind, text: "", media_url: url,
    duration: fd.get("duration") ? +fd.get("duration") : null, created_at: now() };
  S.messages.push(m);
  save();
  emit("message", { message: messageOut(m) });
  botReply(c, S.users[c.users.find((x) => x !== u.id)]);
  return messageOut(m);
});
route("POST", "/api/chats/(\\d+)/read", (_, [cid]) => {
  const u = requireMe();
  const c = convFor(u, cid);
  S.messages.filter((m) => m.conversation_id === c.id && m.sender_id !== u.id).forEach((m) => (m.read_at ||= now()));
  save();
  return { status: "ok" };
});
route("DELETE", "/api/chats/(\\d+)", (_, [cid]) => {
  const c = convFor(requireMe(), cid);
  c.active = false;
  save();
  return { status: "ok" };
});

route("POST", "/api/feed/undo", async (b) => {
  const u = requireMe();
  const sw = S.swipes.find((s) => s.from === u.id && s.to === b.user_id);
  if (!sw) deny(404, "Нечего отменять");
  const conv = S.convs.find((c) => c.active && c.users.includes(u.id) && c.users.includes(b.user_id));
  if (sw.liked && conv) {
    if (S.messages.some((m) => m.conversation_id === conv.id)) deny(409, "У вас уже есть переписка. Удалить пару можно в чате");
    conv.active = false;
  }
  S.swipes = S.swipes.filter((s) => s !== sw);
  save();
  const o = S.users[b.user_id];
  const [score, common] = matchScore(u.interests, u.goals, o.interests, o.goals);
  return { undone: sw.liked ? "like" : "skip", card: { id: o.id, name: o.name, age: years(o), bio: o.bio, photo_url: await img(o.photo_url),
    verified: true, interests: o.interests, goals: o.goals, photos_count: o.photos.length, match: score, common, distance_km: Math.round(km(u, o) * 10) / 10 } };
});

// ---------- Животные ----------
const CAT_TITLE = { charity: "Помощь и сборы", foster: "Передержка", adoption: "Ищет хозяина" };
const tgUrl = (c) => { const m = (c || "").trim().match(/^(?:@|https?:\/\/t\.me\/|t\.me\/)?([A-Za-z0-9_+/-]{3,64})\/?$/); return m ? `https://t.me/${m[1]}` : null; };
function ensurePets() {
  if (S.pets && S.pets.some((p) => p.photos.length >= 3)) return;
  if (S.pets) S.pets = S.pets.filter((p) => p.author_id !== 0); else S.pets = [];
  const mine = S.pets;
  S.pets = DATA.animals.map((a, i) => ({ id: 9000 + i, ...a, city: "Москва", contact: "@cofi_volunteers", fundraising_open: true, active: true,
    photos: [0, 1, 2].map((n) => `@pet:${a.name}:${a.species}:${n}`), author: { id: 0, name: "Волонтёры COFI" }, author_id: 0,
    created_at: new Date(Date.now() - (i + 1) * 86400000 * 2).toISOString(), help_count: [7, 2, 4, 23][i] ?? 0 })).concat(mine);
}
async function petOut(p, u) {
  return { id: p.id, category: p.category, name: p.name, species: p.species, age_text: p.age_text, city: p.city, description: p.description,
    contact_url: tgUrl(p.contact), fundraising_open: p.category === "charity" ? p.fundraising_open : null,
    fundraising_goal: p.category === "charity" ? p.fundraising_goal : "",
    photos: await Promise.all(p.photos.map((x) => (x.startsWith("@pet:") ? petFor(...x.slice(5).split(":")) : x))),
    distance_km: 2.4, author: p.author, is_mine: p.author_id === u.id, created_at: p.created_at };
}
route("GET", "/api/animals", async (_, __, url) => {
  const u = requireMe();
  ensurePets();
  const cat = new URLSearchParams(url.split("?")[1] || "").get("category") || "";
  const list = S.pets.filter((p) => p.active && (!cat || p.category === cat)).sort((a, b) => b.id - a.id);
  return { total: list.length, items: await Promise.all(list.map((p) => petOut(p, u))), categories: CAT_TITLE };
});
route("GET", "/api/animals/(\\d+)", async (_, [pid]) => {
  const u = requireMe();
  ensurePets();
  const p = S.pets.find((x) => x.id === +pid && (x.active || x.author_id === u.id));
  if (!p) deny(404, "Объявление не найдено");
  return { ...(await petOut(p, u)), help_count: p.help_count || 0 };
});
route("POST", "/api/animals", async (fd) => {
  const u = requireMe();
  if (group(u) !== "adult") deny(403, "Публиковать объявления и отправлять заявки можно с 18 лет");
  ensurePets();
  if (!CAT_TITLE[fd.get("category")]) deny(422, "Выберите категорию");
  if (!(fd.get("name") || "").trim()) deny(422, "Укажите кличку или название");
  if (!tgUrl(fd.get("contact"))) deny(422, "Укажите Telegram: @username или ссылку t.me/…");
  const photos = [];
  for (const f of fd.getAll("files")) photos.push(await fileToDataUrl(f, 1000));
  const p = { id: id(), category: fd.get("category"), name: fd.get("name").trim(), species: fd.get("species") || "", age_text: fd.get("age_text") || "",
    city: fd.get("city") || "", description: fd.get("description") || "", contact: fd.get("contact"), fundraising_goal: fd.get("fundraising_goal") || "",
    fundraising_open: true, active: true, photos, author: { id: u.id, name: u.name }, author_id: u.id, created_at: now() };
  S.pets.push(p);
  save();
  return petOut(p, u);
});
route("PATCH", "/api/animals/(\\d+)", async (b, [pid]) => {
  const u = requireMe();
  const p = (S.pets || []).find((x) => x.id === +pid && x.author_id === u.id);
  if (!p) deny(404, "Объявление не найдено");
  if (b.fundraising_open !== undefined) p.fundraising_open = b.fundraising_open;
  if (b.active !== undefined) p.active = b.active;
  save();
  return petOut(p, u);
});
route("POST", "/api/animals/(\\d+)/help", (_, [pid]) => {
  const u = requireMe();
  if (group(u) !== "adult") deny(403, "Публиковать объявления и отправлять заявки можно с 18 лет");
  const p = (S.pets || []).find((x) => x.id === +pid);
  if (!p) deny(404, "Объявление не найдено");
  if (p.category === "charity" && !p.fundraising_open) deny(409, "Сбор уже закрыт, спасибо!");
  p.help_count = (p.help_count || 0) + 1;
  save();
  return { status: "sent", contact_url: tgUrl(p.contact) };
});

// ---------- Поддержка и реклама ----------
const T = DATA.support;
function threadOut(t, withMsgs = true) {
  const out = { id: t.id, topic: t.topic, category: t.category, status: t.status, contact: "", about_user_id: t.about_user_id || null,
    created_at: t.created_at, updated_at: t.updated_at, user: null };
  if (withMsgs) out.messages = S.smsgs.filter((m) => m.thread_id === t.id);
  return out;
}
function smsg(t, author, text) {
  const m = { id: id(), thread_id: t.id, author, text, created_at: now() };
  S.smsgs.push(m);
  t.updated_at = m.created_at;
  return m;
}
function adsAnswer(text) {
  const x = text.toLowerCase();
  if (/формат|размест|вариант|format|placement/.test(x)) return T.formats;
  if (/цен|стоим|бюджет|сколько|прайс|price|cost|budget/.test(x)) return T.price;
  if (/аудитор|охват|статист|audience|reach|stat/.test(x)) {
    const people = Object.values(S.users).filter((u) => u.is_bot);
    const counts = {};
    people.forEach((u) => u.interests.forEach((i) => (counts[i] = (counts[i] || 0) + 1)));
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k, v]) => `${k} (${v})`).join(", ");
    return `Сейчас в COFI ${people.length} анкет с подтверждённым фото, из них ${people.length} старше 18 лет. Популярные интересы: ${top}. Подростковая лента (14–17) для рекламы закрыта.`;
  }
  if (/заявк|менеджер|связ|контакт|звон|request|manager|contact|call/.test(x)) return T.lead;
  return null;
}
route("POST", "/api/support/threads", async (b) => {
  await ensureBots();
  const u = me();
  if (b.topic === "support" && !u) deny(401, "Чтобы написать в поддержку, войдите в аккаунт");
  const t = { id: id(), topic: b.topic === "ads" ? "ads" : "support", category: b.topic === "ads" ? "ads" : b.category || "help",
    status: "open", about_user_id: b.about_user_id, created_at: now(), updated_at: now() };
  S.threads.push(t);
  if (t.topic === "ads") smsg(t, "bot", T.ads_greeting);
  if ((b.text || "").trim()) userMsg(t, b.text);
  else if (t.topic === "support") smsg(t, "bot", T.support_greeting.replace("{id}", t.id));
  save();
  return threadOut(t);
});
function userMsg(t, text) {
  smsg(t, "user", text.trim());
  if (t.topic === "ads") smsg(t, "bot", adsAnswer(text) || T.handoff);
  else if (!S.smsgs.some((m) => m.thread_id === t.id && m.author === "bot")) smsg(t, "bot", T.support_greeting.replace("{id}", t.id));
  else if (S.smsgs.filter((m) => m.thread_id === t.id && m.author === "user").length === 1) {
    // в демо «оператор» отвечает сам, чтобы было видно, как это выглядит
    setTimeout(() => {
      const m = smsg(t, "staff", "Здравствуйте! Это демо, здесь отвечает автоматический оператор. В приложении ответит живой сотрудник из админ-панели.");
      save();
      emit("support", { thread_id: t.id, message: m });
    }, 2500);
  }
}
route("GET", "/api/support/threads", () => S.threads.slice().reverse().map((t) => threadOut(t, false)));
route("GET", "/api/support/threads/(\\d+)", (_, [tid]) => {
  const t = S.threads.find((x) => x.id === +tid);
  if (!t) deny(404, "Обращение не найдено");
  return threadOut(t);
});
route("POST", "/api/support/threads/(\\d+)/messages", (b, [tid]) => {
  const t = S.threads.find((x) => x.id === +tid);
  if (!t) deny(404, "Обращение не найдено");
  userMsg(t, b.text || "");
  save();
  return S.smsgs[S.smsgs.length - 1];
});

async function request(method, url, body) {
  const path = url.split("?")[0];
  for (const r of ROUTES) {
    const m = r.method === method && path.match(r.re);
    if (m) {
      await new Promise((res) => setTimeout(res, 60)); // как будто сеть
      return structuredClone(await r.fn(body, m.slice(1), url));
    }
  }
  throw new ApiError(404, "Не найдено");
}

export const api = {
  get: (u) => request("GET", u),
  post: (u, b) => request("POST", u, b ?? {}),
  put: (u, b) => request("PUT", u, b),
  patch: (u, b) => request("PATCH", u, b),
  del: (u) => request("DELETE", u),
};
