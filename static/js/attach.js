// Шторка «Прикрепить» в чате: открывается на пол-экрана, тянется вверх до почти полного, вниз — закрывается.
// Слева вверху — живая картинка с основной камеры, нажатие открывает съёмку фото.
import { takePhoto } from "./camera.js";
import { icons } from "./icons.js";
import { $, h } from "./ui.js";

const HALF = 0.5, FULL = 0.92;

/** onPick(files) — выбранные/снятые файлы. pickGallery() и pickVideo() должны открыть системный выбор (нужно нажатие). */
export function openAttachSheet({ onPick, pickGallery, pickVideo }) {
  const el = h(`<div class="attach-sheet" role="dialog" aria-label="Прикрепить">
    <div class="attach-scrim" data-close></div>
    <div class="attach-panel">
      <div class="attach-grab" aria-hidden="true"><i></i></div>
      <div class="attach-grid">
        <button class="attach-tile cam" data-camera aria-label="Сделать фото">
          <video playsinline muted autoplay></video><canvas></canvas><span>${icons.camera}</span>
        </button>
        <button class="attach-tile" data-gallery>${icons.image}<span>Галерея</span></button>
        <button class="attach-tile" data-video>${icons.video}<span>Снять видео</span></button>
      </div>
      <p class="muted small attach-hint">В галерее можно отметить сразу несколько фото и видео — до 10</p>
    </div>
  </div>`);
  document.body.append(el);
  const panel = $(".attach-panel", el);
  const vh = () => window.innerHeight;
  let height = HALF;
  const setH = (k, animate = true) => {
    panel.style.transition = animate ? "" : "none";
    panel.style.height = `${Math.round(k * vh())}px`;
  };
  setH(HALF, false);
  requestAnimationFrame(() => el.classList.add("show"));

  // --- живая картинка с основной (задней) камеры ---
  let stream = null, drawing = true;
  const video = $("video", el), canvas = $("canvas", el);
  (async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 480 }, height: { ideal: 480 } }, audio: false });
      if (!drawing) return stopCam();
      video.muted = true;
      video.playsInline = true;
      video.setAttribute("playsinline", "");
      video.srcObject = stream;
      video.play().catch(() => {});
      // рисуем через canvas: в Telegram на iPhone сам <video> бывает чёрным
      const draw = () => {
        if (!drawing) return;
        if (video.videoWidth) {
          if (canvas.width !== video.videoWidth) { canvas.width = video.videoWidth; canvas.height = video.videoHeight; }
          canvas.getContext("2d").drawImage(video, 0, 0);
          $(".cam", el).classList.add("live");
        }
        requestAnimationFrame(draw);
      };
      draw();
    } catch { /* нет доступа к камере — останется значок */ }
  })();
  function stopCam() {
    drawing = false;
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  const close = () => {
    stopCam();
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  };

  $("[data-close]", el).onclick = close;
  $("[data-gallery]", el).onclick = () => { pickGallery(); close(); };
  $("[data-video]", el).onclick = () => { pickVideo(); close(); };
  $("[data-camera]", el).onclick = async () => {
    stopCam(); // iPhone не даёт держать открытой камеру дважды
    close();
    const file = await takePhoto({ facing: "environment", chat: true });
    if (file) onPick([file]);
  };

  // --- перетаскивание за верх шторки ---
  let startY = 0, startH = 0, dragging = false;
  const grab = $(".attach-grab", el);
  grab.addEventListener("pointerdown", (e) => {
    dragging = true;
    startY = e.clientY;
    startH = panel.getBoundingClientRect().height;
    grab.setPointerCapture(e.pointerId);
    panel.style.transition = "none";
  });
  grab.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const k = Math.min(FULL, Math.max(0.15, (startH + startY - e.clientY) / vh()));
    panel.style.height = `${Math.round(k * vh())}px`;
  });
  const release = () => {
    if (!dragging) return;
    dragging = false;
    const k = panel.getBoundingClientRect().height / vh();
    if (k < HALF - 0.15) return close(); // стянули вниз
    height = k > (HALF + FULL) / 2 - 0.05 ? FULL : HALF;
    setH(height);
  };
  grab.addEventListener("pointerup", release);
  grab.addEventListener("pointercancel", release);
  return close;
}
