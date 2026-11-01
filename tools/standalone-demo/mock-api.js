// Имитация сервера COFI прямо в браузере: тот же интерфейс, что у static/js/api.js.
// Логика повторяет app/routers: подбор по интересам, свайпы, пары, чаты, ответы ботов.
import DATA from "./data.json";
import { portraitFor, sceneFor, fileToDataUrl } from "./images.js";

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
  return { seq: 100, me: null, accounts: {}, users: {}, swipes: [], convs: [], messages: [] };
}
let S = load();
function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const s = JSON.parse(raw);
      s.messages = s.messages.filter((m) => !(m.media_url || "").startsWith("blob:")); // видео не переживает перезагрузку
      return s;
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
function isComplete(u) {
  return !!(u.name && u.age && u.gender && u.looking_for && u.interests.length >= DATA.min_interests && u.goals.length && u.photo_url && u.photo_verified);
}
function ownProfile(u) {
  return {
    id: u.id, email: u.email, email_verified: true, email_notifications: false, auth_provider: u.is_demo ? "demo" : "email",
    telegram_username: null, name: u.name, age: u.age, bio: u.bio, gender: u.gender, looking_for: u.looking_for,
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
  if (Object.values(S.users).some((u) => u.is_bot)) return;
  for (const b of DATA.bots) {
    const uid = id();
    S.users[uid] = {
      id: uid, key: b.key, is_bot: true, name: b.name, age: b.age, gender: b.gender, looking_for: "any", bio: b.bio,
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
  const text = sent.length < bot.replies.length ? bot.replies[sent.length] : DATA.fallback_reply;
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
  app_name: "COFI", survey: DATA.survey, genders: DATA.genders, looking_for: DATA.looking_for,
  min_interests: DATA.min_interests, telegram_bot_username: null, ice_servers: [], face_dev_mode: true,
}));

route("GET", "/api/auth/me", () => (me() ? ownProfile(me()) : deny(401, "Нужно войти в аккаунт")));

route("POST", "/api/auth/demo", async () => {
  await ensureBots();
  const uid = id();
  const g = DATA.guest;
  S.users[uid] = { id: uid, is_demo: true, name: g.name, age: g.age, gender: g.gender, looking_for: g.looking_for, bio: g.bio,
    goals: g.goals, interests: g.interests, lat: DATA.center[0], lon: DATA.center[1], max_distance_km: 50,
    photo_url: await portraitFor("guest", g.name), photos: [], photo_verified: true };
  for (const b of Object.values(S.users)) if (b.is_bot && b.likes_you) S.swipes.push({ from: b.id, to: uid, liked: true });
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
    S.users[uid] = { id: uid, is_demo: true, email, name: "", age: null, gender: null, looking_for: null, bio: "",
      goals: [], interests: [], lat: DATA.center[0], lon: DATA.center[1], max_distance_km: 50, photo_url: null, photos: [], photo_verified: false };
    for (const b of Object.values(S.users)) if (b.is_bot && b.likes_you) S.swipes.push({ from: b.id, to: uid, liked: true });
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
route("POST", "/api/auth/telegram", () => deny(503, "Вход через Telegram в демо не работает"));
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
  if (b.age !== undefined) { if (!(b.age >= 18 && b.age <= 100)) deny(422, "Приложение доступно только с 18 лет"); u.age = b.age; }
  if (b.bio !== undefined) u.bio = b.bio.trim().slice(0, 500);
  if (b.gender !== undefined) u.gender = b.gender;
  if (b.looking_for !== undefined) u.looking_for = b.looking_for;
  if (b.interests !== undefined) {
    const v = [...new Set(b.interests)];
    if (v.length < DATA.min_interests) deny(422, `Выберите хотя бы ${DATA.min_interests} интереса`);
    u.interests = v;
  }
  if (b.goals !== undefined) { if (!b.goals.length) deny(422, "Выберите, что вы ищете"); u.goals = [...new Set(b.goals)]; }
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
  return Object.values(S.users).filter((o) => o.is_bot && compatible(u, o));
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
    id: o.id, name: o.name, age: o.age, bio: o.bio, photo_url: await img(o.photo_url), verified: true,
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

async function request(method, url, body) {
  const path = url.split("?")[0];
  for (const r of ROUTES) {
    const m = r.method === method && path.match(r.re);
    if (m) {
      await new Promise((res) => setTimeout(res, 60)); // как будто сеть
      return structuredClone(await r.fn(body, m.slice(1)));
    }
  }
  throw new ApiError(404, "Не найдено");
}

export const api = {
  get: (u) => request("GET", u),
  post: (u, b) => request("POST", u, b ?? {}),
  put: (u, b) => request("PUT", u, b),
  del: (u) => request("DELETE", u),
};
