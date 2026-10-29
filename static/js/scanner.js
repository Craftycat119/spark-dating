// Сканер лица: три кадра (прямо, поворот в одну сторону, в другую) → сервер сверяет с фото
import { api } from "./api.js";
import { h } from "./ui.js";

const STEPS = [
  { pose: "center", text: "Смотрите прямо в камеру", arrow: "" },
  { pose: "left", text: "Медленно поверните голову влево", arrow: "left" },
  { pose: "right", text: "Теперь поверните вправо", arrow: "right" },
];
const STEP_MS = 2600;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function grab(video) {
  const canvas = document.createElement("canvas");
  const w = Math.min(video.videoWidth, 720);
  canvas.width = w;
  canvas.height = Math.round((video.videoHeight / video.videoWidth) * w);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.88);
}

/** Показывает сканер внутри root. Возвращает {ok, reason, profile}. */
export async function runScanner(root) {
  const el = h(`<div class="stack">
    <div class="scanner">
      <video playsinline muted autoplay></video>
      <div class="mask"></div><div class="oval"></div>
      <div class="arrow"></div><div class="countdown"></div>
      <div class="instruction">Разрешите доступ к камере</div>
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
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 1280 } }, audio: false });
  } catch {
    return { ok: false, reason: "Нет доступа к камере. Разрешите его в настройках браузера и попробуйте снова." };
  }
  video.srcObject = stream;
  await new Promise((r) => (video.readyState >= 2 ? r() : (video.onloadeddata = r)));
  await wait(600);

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
    stream.getTracks().forEach((t) => t.stop());
  }

  arrow.textContent = "";
  instruction.textContent = "Сверяем лицо с фото…";
  oval.className = "oval active";
  try {
    const res = await api.post("/api/profile/verify-face", { frames });
    oval.className = res.ok ? "oval ok" : "oval";
    instruction.textContent = res.ok ? "Готово, это вы" : "Не получилось";
    return res;
  } catch (e) {
    return { ok: false, reason: e.message };
  }
}
