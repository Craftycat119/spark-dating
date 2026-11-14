// Снимок с фронтальной камеры прямо на странице: превью, «Снять», «Переснять», «Использовать».
// Если камера недоступна (нет HTTPS, нет разрешения), отдаём выбор системе: input с capture="user",
// на телефоне он сразу открывает камеру.
import { icons } from "./icons.js";
import { getCamera, release } from "./media.js";
import { $, h } from "./ui.js";

function nativeCapture() {
  return new Promise((resolve) => {
    const input = h(`<input type="file" accept="image/*" capture="user" hidden>`);
    input.onchange = () => { resolve(input.files[0] || null); input.remove(); };
    document.body.append(input);
    input.click();
  });
}

const openStream = (facing) => getCamera(facing); // общий поток: разрешение спрашивается один раз

/**
 * Возвращает File с JPEG-снимком или null, если человек передумал.
 * facing: "user" — фронтальная (фото профиля, квадрат с овалом), "environment" — основная.
 * chat: true — снимок для чата: весь кадр, без овала и подсказки про лицо.
 */
export async function takePhoto({ facing = "user", chat = false } = {}) {
  let stream;
  try {
    stream = await openStream(facing);
  } catch {
    return nativeCapture();
  }
  return new Promise((resolve) => {
    const el = h(`<div class="overlay camera-shot ${chat ? "chat-shot" : ""}" role="dialog" aria-label="Сделать фото">
      <div class="cam-frame"><video autoplay playsinline muted></video><canvas class="live"></canvas><canvas class="shot" hidden></canvas>${chat ? "" : `<i class="cam-oval"></i>`}
        <button class="icon-btn cam-flip" data-flip aria-label="Сменить камеру">${icons.flip}</button></div>
      ${chat ? "" : `<p class="cam-hint">Лицо в овале, хороший свет, без очков и масок</p>`}
      <div class="cam-actions">
        <button class="btn ghost" data-cancel>Отмена</button>
        <button class="shutter" data-shoot aria-label="Снять"></button>
        <button class="btn ghost" data-retake hidden>Переснять</button>
      </div>
      <button class="btn block" data-use hidden>${icons.check} ${chat ? "Отправить" : "Использовать фото"}</button>
    </div>`);
    const video = $("video", el), canvas = $("canvas.shot", el), live = $("canvas.live", el);
    const mirror = () => facing === "user";
    const attach = () => {
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      video.setAttribute("webkit-playsinline", "");
      video.srcObject = stream;
      video.play().catch(() => {});
      live.classList.toggle("mirror", mirror());
    };
    // iPhone (и Telegram на нём) не запускает видео, пока элемент не на странице: сначала вставляем, потом поток
    document.body.append(el);
    attach();
    // Превью рисуем на canvas: в Telegram на iPhone сам <video> в Mini App часто чёрный, хотя кадры идут
    let drawing = true;
    const draw = () => {
      if (!drawing) return;
      if (video.videoWidth && !live.hidden) {
        if (live.width !== video.videoWidth) { live.width = video.videoWidth; live.height = video.videoHeight; }
        live.getContext("2d").drawImage(video, 0, 0, live.width, live.height);
      }
      requestAnimationFrame(draw);
    };
    draw();
    const done = (file) => { drawing = false; release("video"); el.remove(); resolve(file); };
    const toggle = (shot) => {
      live.hidden = shot; canvas.hidden = !shot;
      $("[data-flip]", el).hidden = shot;
      $("[data-shoot]", el).hidden = shot; $("[data-retake]", el).hidden = !shot; $("[data-use]", el).hidden = !shot;
    };
    $("[data-flip]", el).onclick = async () => {
      const next = facing === "user" ? "environment" : "user";
      try {
        stream = await openStream(next); // общий модуль сам выключит прежнюю камеру
        facing = next;
        live.width = 0; // размер кадра у другой камеры свой
        attach();
      } catch { /* второй камеры нет */ }
    };
    $("[data-cancel]", el).onclick = () => done(null);
    $("[data-shoot]", el).onclick = () => {
      if (!video.videoWidth) return; // кадр ещё не пришёл
      const vw = video.videoWidth, vh = video.videoHeight;
      // для профиля — квадрат по центру; для чата — весь кадр. Фронтальная — зеркально, как в превью
      const sw = chat ? vw : Math.min(vw, vh), sh = chat ? vh : Math.min(vw, vh);
      const k = Math.min(1, (chat ? 1600 : 1080) / Math.max(sw, sh));
      canvas.width = Math.round(sw * k);
      canvas.height = Math.round(sh * k);
      const ctx = canvas.getContext("2d");
      if (mirror()) { ctx.translate(canvas.width, 0); ctx.scale(-1, 1); }
      ctx.drawImage(video, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, canvas.width, canvas.height);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      toggle(true);
    };
    $("[data-retake]", el).onclick = () => toggle(false);
    $("[data-use]", el).onclick = () => canvas.toBlob((b) => done(b && new File([b], "camera.jpg", { type: "image/jpeg" })), "image/jpeg", 0.9);
  });
}

/**
 * Уменьшает фото на телефоне перед отправкой до того размера, который сервер всё равно сохраняет (1600 px, JPEG).
 * Качество итоговой картинки то же, а отправлять вместо 4–8 МБ приходится 0,3–0,6 МБ — в разы быстрее.
 * Поворот по EXIF браузер применяет сам. Если что-то не так — отправляем исходный файл.
 */
export async function shrinkImage(file, maxSide = 1600) {
  if (!file?.type?.startsWith("image/") || file.type === "image/gif") return file;
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const w = img.naturalWidth, hgt = img.naturalHeight;
    if (!w || !hgt) return file;
    const usual = ["image/jpeg", "image/png", "image/webp"].includes(file.type); // HEIC и прочее сервер не прочитает — переводим в JPEG
    if (usual && Math.max(w, hgt) <= maxSide && file.size < 1_500_000) return file; // и так небольшое
    const k = Math.min(1, maxSide / Math.max(w, hgt));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * k);
    canvas.height = Math.round(hgt * k);
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.92));
    return blob && (blob.size < file.size || !usual) ? new File([blob], "photo.jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;
  } finally {
    URL.revokeObjectURL(url);
  }
}
