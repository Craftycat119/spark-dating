// Снимок с фронтальной камеры прямо на странице: превью, «Снять», «Переснять», «Использовать».
// Если камера недоступна (нет HTTPS, нет разрешения), отдаём выбор системе: input с capture="user",
// на телефоне он сразу открывает камеру.
import { icons } from "./icons.js";
import { $, h } from "./ui.js";

function nativeCapture() {
  return new Promise((resolve) => {
    const input = h(`<input type="file" accept="image/*" capture="user" hidden>`);
    input.onchange = () => { resolve(input.files[0] || null); input.remove(); };
    document.body.append(input);
    input.click();
  });
}

/** Возвращает File с JPEG-снимком или null, если человек передумал. */
export async function takePhoto() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 1280 } }, audio: false });
  } catch {
    return nativeCapture();
  }
  return new Promise((resolve) => {
    const el = h(`<div class="overlay camera-shot" role="dialog" aria-label="Сделать фото">
      <div class="cam-frame"><video autoplay playsinline muted></video><canvas class="live"></canvas><canvas class="shot" hidden></canvas><i class="cam-oval"></i></div>
      <p class="cam-hint">Лицо в овале, хороший свет, без очков и масок</p>
      <div class="cam-actions">
        <button class="btn ghost" data-cancel>Отмена</button>
        <button class="shutter" data-shoot aria-label="Снять"></button>
        <button class="btn ghost" data-retake hidden>Переснять</button>
      </div>
      <button class="btn block" data-use hidden>${icons.check} Использовать фото</button>
    </div>`);
    const video = $("video", el), canvas = $("canvas.shot", el), live = $("canvas.live", el);
    // iPhone (и Telegram на нём) не запускает видео, пока элемент не на странице: сначала вставляем, потом поток
    document.body.append(el);
    video.muted = true;
    video.playsInline = true;
    video.setAttribute("playsinline", "");
    video.setAttribute("webkit-playsinline", "");
    video.srcObject = stream;
    video.play().catch(() => {});
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
    const done = (file) => { drawing = false; stream.getTracks().forEach((t) => t.stop()); el.remove(); resolve(file); };
    const toggle = (shot) => {
      live.hidden = shot; canvas.hidden = !shot;
      $("[data-shoot]", el).hidden = shot; $("[data-retake]", el).hidden = !shot; $("[data-use]", el).hidden = !shot;
    };
    $("[data-cancel]", el).onclick = () => done(null);
    $("[data-shoot]", el).onclick = () => {
      // квадрат по центру кадра, зеркально, как человек видел себя в превью
      if (!video.videoWidth) return; // кадр ещё не пришёл
      const s = Math.min(video.videoWidth, video.videoHeight);
      canvas.width = canvas.height = Math.min(s, 1080);
      const ctx = canvas.getContext("2d");
      ctx.translate(canvas.width, 0);
      ctx.scale(-1, 1);
      ctx.drawImage(video, (video.videoWidth - s) / 2, (video.videoHeight - s) / 2, s, s, 0, 0, canvas.width, canvas.height);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      toggle(true);
    };
    $("[data-retake]", el).onclick = () => toggle(false);
    $("[data-use]", el).onclick = () => canvas.toBlob((b) => done(b && new File([b], "camera.jpg", { type: "image/jpeg" })), "image/jpeg", 0.9);
  });
}
