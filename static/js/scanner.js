// Сканер лица: три кадра (прямо, поворот в одну сторону, в другую) → сервер сверяет с фото
import { getCamera, release } from "./media.js";
import { api } from "./api.js";
import { h } from "./ui.js";

const STEPS = [
  { pose: "center", text: "Смотрите прямо в камеру", arrow: "" },
  { pose: "left", text: "Медленно поверните голову влево", arrow: "left" },
  { pose: "right", text: "Теперь поверните вправо", arrow: "right" },
];
const STEP_MS = 2600;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** Кадры с камеры идут: размер известен и время видео движется. */
async function framesFlow(video, ms) {
  const t0 = performance.now();
  let last = -1;
  while (performance.now() - t0 < ms) {
    if (video.readyState >= 2 && video.videoWidth && video.currentTime !== last && last >= 0) return true;
    last = video.readyState >= 2 ? video.currentTime : last;
    await wait(150);
  }
  return false;
}

/** Средняя яркость кадра (0–255): чёрный кадр — камера ещё не проснулась или закрыта. */
function brightness(video) {
  try {
    const c = document.createElement("canvas");
    c.width = c.height = 24;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(video, 0, 0, 24, 24);
    const d = g.getImageData(0, 0, 24, 24).data;
    let s = 0;
    for (let i = 0; i < d.length; i += 4) s += d[i] * 0.3 + d[i + 1] * 0.59 + d[i + 2] * 0.11;
    return s / (d.length / 4);
  } catch {
    return 255; // не смогли прочитать — не мешаем проверке
  }
}

function grab(video) {
  const canvas = document.createElement("canvas");
  const w = Math.min(video.videoWidth, 720);
  canvas.width = w;
  canvas.height = Math.round((video.videoHeight / video.videoWidth) * w);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.88);
}

/** Показывает сканер внутри root. Возвращает {ok, reason, profile}. */
export async function runScanner(root, { consent = false } = {}) {
  const el = h(`<div class="stack">
    <div class="scanner">
      <video playsinline muted autoplay></video><canvas class="live"></canvas>
      <div class="mask"></div><div class="oval"></div>
      <div class="arrow"></div><div class="countdown"></div>
      <div class="instruction">Разрешите доступ к камере</div>
      <button type="button" class="btn cam-start" hidden>Включить камеру</button>
    </div>
    <p class="muted small">Мы сравним лицо на камере с лицом на фото. Кадры со сканера не видны другим пользователям.</p>
  </div>`);
  root.replaceChildren(el);
  const video = el.querySelector("video");
  const oval = el.querySelector(".oval");
  const instruction = el.querySelector(".instruction");
  const arrow = el.querySelector(".arrow");
  const countdown = el.querySelector(".countdown");

  let stream;
  try {
    stream = await getCamera("user");
  } catch {
    return { ok: false, reason: "Нет доступа к камере. Разрешите его в настройках браузера и попробуйте снова." };
  }
  // iPhone (и Telegram на нём): muted и playsinline нужно выставить свойствами, атрибутов из разметки WebKit не слушается —
  // иначе видео не играет и овал остаётся чёрным (тот же приём, что для фото с камеры в camera.js)
  video.muted = true;
  video.playsInline = true;
  video.setAttribute("playsinline", "");
  video.setAttribute("webkit-playsinline", "");
  video.srcObject = stream;
  instruction.textContent = "Включаем камеру…";
  try { await video.play(); } catch { /* iPhone в режиме энергосбережения и часть Android ждут нажатия — ниже */ }
  // Видео не пошло само за 3 секунды — запускаем по нажатию (так разрешено на любом телефоне)
  if (!(await framesFlow(video, 3000))) {
    const btn = el.querySelector(".cam-start");
    instruction.textContent = "Нажмите, чтобы включить камеру";
    btn.hidden = false;
    await new Promise((r) => {
      btn.onclick = async () => {
        try { await video.play(); } catch { /* попробуем ещё раз ниже */ }
        if (await framesFlow(video, 3000)) r();
        else instruction.textContent = "Камера не включилась. Закройте другие приложения с камерой и нажмите ещё раз";
      };
    });
    btn.hidden = true;
  }
  // Картинку рисуем на canvas: в Telegram на iPhone сам <video> внутри Mini App часто остаётся чёрным,
  // хотя кадры с камеры идут (их же мы и отправляем на сверку). Если canvas не рисует — показываем само видео.
  const live = el.querySelector("canvas.live");
  const scanner = el.querySelector(".scanner");
  let drawing = true;
  const draw = () => {
    if (!drawing) return;
    if (video.videoWidth) {
      try {
        if (live.width !== video.videoWidth) { live.width = video.videoWidth; live.height = video.videoHeight; }
        live.getContext("2d").drawImage(video, 0, 0, live.width, live.height);
      } catch { scanner.classList.add("show-video"); }
    }
    requestAnimationFrame(draw);
  };
  draw();
  await wait(400);
  // Лицо должно быть видно: ждём, пока кадр перестанет быть чёрным (камера «просыпается», рука закрывает объектив)
  for (let t = 0; t < 40 && brightness(video) < 12; t++) {
    instruction.textContent = "Ничего не видно — откройте камеру и встаньте к свету";
    await wait(250);
  }
  instruction.textContent = "Поместите лицо в овал";
  await wait(900);

  const frames = {};
  try {
    for (const step of STEPS) {
      instruction.textContent = step.text;
      arrow.className = `arrow ${step.arrow}`;
      arrow.textContent = step.arrow === "left" ? "←" : step.arrow === "right" ? "→" : "";
      oval.className = "oval active";
      for (let t = 3; t > 0; t--) {
        countdown.textContent = t;
        await wait(STEP_MS / 3);
      }
      countdown.textContent = "";
      frames[step.pose] = grab(video);
      oval.className = "oval ok";
      await wait(250);
    }
  } finally {
    drawing = false;
    release("video");
  }

  arrow.textContent = "";
  instruction.textContent = "Сверяем лицо с фото…";
  oval.className = "oval active";
  try {
    const res = await api.post("/api/profile/verify-face", { frames, consent });
    oval.className = res.ok ? "oval ok" : "oval";
    instruction.textContent = res.ok ? "Готово, это вы" : "Не получилось";
    return res;
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}
