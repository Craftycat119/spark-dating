// «Фото» для демо: рисуем на canvas, потому что внешние картинки на странице по ссылке заблокированы.
// Портрет: крупная буква на вязаном полосатом фоне, как аватар в макете «Нити».
// Сцена: тёплый градиент, боке и большой эмодзи-символ увлечения.
const cache = new Map();
const W = 540, H = 675;

const TONES = [
  ["#c9461a", "#a9380f"], ["#d9622a", "#b04711"], ["#b8401a", "#8e2f0c"], ["#e0743a", "#bb5220"],
  ["#a8411f", "#7e2c10"], ["#cf5a2c", "#9c3a12"], ["#c24f2d", "#923518"], ["#dd6b34", "#a8461a"],
];
const SCENES = {
  "film-camera": ["📷", "Плёнка"], "coffee-bar": ["☕", "Кофейня"], "mountain-trail": ["🏔️", "Тропа"],
  "bike-forest": ["🚲", "Выезд за город"], "camp-tent": ["⛺", "Палатка"], "techno-club": ["🎛️", "Сет"],
  "neon-city": ["🌃", "Ночной город"], "anime-room": ["🎴", "Аниме-вечер"], "concert-lights": ["🎤", "Концерт"],
  "gym-weights": ["🏋️", "Зал"], "restaurant-dinner": ["🍽️", "Ужин"], airport: ["✈️", "Командировка"],
  "museum-hall": ["🖼️", "Выставка"], "yoga-mat": ["🧘", "Йога"], bookshop: ["📚", "Книжный"],
  "board-games": ["🎲", "Игротека"], "standup-mic": ["🎙️", "Открытый микрофон"], "retro-console": ["🕹️", "Ретро"],
  "dance-floor": ["💃", "Танцпол"], "beach-sunset": ["🌅", "Закат"], festival: ["🎪", "Фестиваль"],
  "church-old": ["⛪", "Воскресенье"], "family-dinner": ["🥘", "Семейный ужин"], office: ["💼", "Офис"],
  "horror-night": ["🕯️", "Хоррор-ночь"], "plants-home": ["🪴", "Мои растения"], knitting: ["🧶", "Вязание"],
  "night-club": ["🪩", "Клуб"], "car-city": ["🚗", "Ночная поездка"], "luxury-dinner": ["🥂", "Ресторан"],
};

function hash(s) {
  let h = 2166136261;
  for (const c of s) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return h >>> 0;
}
function rng(seed) {
  let x = seed || 1;
  return () => ((x = Math.imul(x ^ (x >>> 15), 2246822507) ^ Math.imul(x ^ (x >>> 13), 3266489909)) >>> 0) / 4294967296;
}
async function fontsReady() {
  try { await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 1500))]); } catch { /* без шрифтов тоже ок */ }
}
function canvas() {
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  return [c, c.getContext("2d")];
}

export async function portraitFor(key, name) {
  if (cache.has("p" + key)) return cache.get("p" + key);
  await fontsReady();
  const [c, g] = canvas();
  const [a, b] = TONES[hash(key) % TONES.length];
  g.fillStyle = a; g.fillRect(0, 0, W, H);
  g.save(); g.translate(W / 2, H / 2); g.rotate(Math.PI / 4);
  g.fillStyle = b;
  for (let x = -H; x < H; x += 22) g.fillRect(x, -H, 7, H * 2);
  g.restore();
  const v = g.createRadialGradient(W / 2, H * 0.42, 40, W / 2, H / 2, H * 0.7);
  v.addColorStop(0, "rgba(255,190,140,.25)"); v.addColorStop(1, "rgba(20,8,4,.55)");
  g.fillStyle = v; g.fillRect(0, 0, W, H);
  g.fillStyle = "#f3e9df";
  g.font = `700 260px Unbounded, "Arial Black", sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  g.shadowColor = "rgba(40,10,0,.45)"; g.shadowBlur = 30; g.shadowOffsetY = 12;
  g.fillText(name.charAt(0).toUpperCase(), W / 2, H * 0.47);
  const url = c.toDataURL("image/jpeg", 0.86);
  cache.set("p" + key, url);
  return url;
}

export async function sceneFor(key) {
  if (cache.has("s" + key)) return cache.get("s" + key);
  await fontsReady();
  const [emoji, label] = SCENES[key] || ["✨", key];
  const r = rng(hash(key));
  const [c, g] = canvas();
  const hue = 8 + r() * 28;
  const grd = g.createLinearGradient(0, 0, W * r(), H);
  grd.addColorStop(0, `hsl(${hue}, 85%, ${52 + r() * 10}%)`);
  grd.addColorStop(1, `hsl(${hue - 6}, 75%, ${14 + r() * 8}%)`);
  g.fillStyle = grd; g.fillRect(0, 0, W, H);
  for (let i = 0; i < 14; i++) { // боке
    const x = r() * W, y = r() * H * 0.8, rad = 20 + r() * 90;
    const b = g.createRadialGradient(x, y, 0, x, y, rad);
    b.addColorStop(0, `rgba(255,${200 + r() * 55},${150 + r() * 80},${0.12 + r() * 0.2})`);
    b.addColorStop(1, "rgba(255,200,150,0)");
    g.fillStyle = b; g.beginPath(); g.arc(x, y, rad, 0, Math.PI * 2); g.fill();
  }
  g.font = `220px "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  g.shadowColor = "rgba(0,0,0,.35)"; g.shadowBlur = 40; g.shadowOffsetY = 16;
  g.fillText(emoji, W / 2, H * 0.44);
  g.shadowColor = "transparent";
  g.fillStyle = "rgba(18,12,9,.38)"; g.fillRect(0, H - 120, W, 120);
  g.fillStyle = "#f3e9df"; g.textAlign = "left";
  g.font = `600 38px Onest, system-ui, sans-serif`;
  g.fillText(label, 32, H - 58);
  const url = c.toDataURL("image/jpeg", 0.84);
  cache.set("s" + key, url);
  return url;
}

/** Файл пользователя → уменьшенный JPEG data: URL (переживает перезагрузку страницы). */
export function fileToDataUrl(file, max = 900) {
  return new Promise((resolve, reject) => {
    if (!file) return reject(new Error("Нет файла"));
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => {
      const k = Math.min(1, max / Math.max(im.width, im.height));
      const c = document.createElement("canvas");
      c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
      c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.85));
    };
    im.onerror = () => reject(new Error("Это не изображение"));
    im.src = url;
  });
}
