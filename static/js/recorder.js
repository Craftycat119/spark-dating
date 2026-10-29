// Голосовые и «кружочки»
import { icons } from "./icons.js";
import { h, pickMime, fmtDur } from "./ui.js";

const MAX_CIRCLE_SEC = 60;
const MAX_VOICE_SEC = 300;

/** Голосовое: start() → stop() возвращает {blob, duration} либо cancel(). */
export class VoiceRecorder {
  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mime = pickMime(["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"]);
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.chunks = [];
    this.rec.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.started = performance.now();
    this.rec.start(250);
    this.limit = setTimeout(() => this.onLimit?.(), MAX_VOICE_SEC * 1000);
  }
  elapsed() { return (performance.now() - this.started) / 1000; }
  stop() {
    clearTimeout(this.limit);
    return new Promise((resolve) => {
      this.rec.onstop = () => {
        this.stream.getTracks().forEach((t) => t.stop());
        resolve({ blob: new Blob(this.chunks, { type: this.rec.mimeType || "audio/webm" }), duration: this.elapsed() });
      };
      this.rec.stop();
    });
  }
  cancel() {
    clearTimeout(this.limit);
    this.rec.onstop = null;
    try { this.rec.stop(); } catch { /* уже остановлен */ }
    this.stream.getTracks().forEach((t) => t.stop());
  }
}

/** Окно записи кружочка. Возвращает Promise<{blob, duration} | null>. */
export function recordCircle() {
  return new Promise(async (resolve) => {
    const C = 2 * Math.PI * 49;
    const el = h(`<div class="circle-recorder" role="dialog" aria-label="Запись видеосообщения">
      <div class="lens"><video playsinline muted autoplay></video>
        <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="49" fill="none" stroke="var(--accent)" stroke-width="3"
          stroke-dasharray="${C}" stroke-dashoffset="${C}" stroke-linecap="round"/></svg></div>
      <div class="timer" style="font:600 20px var(--display)">0:00</div>
      <div class="controls">
        <button class="icon-btn" data-close aria-label="Закрыть">${icons.x}</button>
        <button class="rec-button" data-rec aria-label="Начать запись"><i></i></button>
        <button class="icon-btn" data-flip aria-label="Сменить камеру">${icons.flip}</button>
      </div>
      <p class="muted small">До ${MAX_CIRCLE_SEC} секунд</p>
    </div>`);
    document.body.append(el);
    const video = el.querySelector("video");
    const ring = el.querySelector("circle");
    const timer = el.querySelector(".timer");
    const recBtn = el.querySelector("[data-rec]");
    let facing = "user";
    let stream, rec, chunks = [], started = 0, tick, done = false;

    const finish = (result) => {
      if (done) return;
      done = true;
      clearInterval(tick);
      stream?.getTracks().forEach((t) => t.stop());
      el.remove();
      resolve(result);
    };

    async function openCamera() {
      stream?.getTracks().forEach((t) => t.stop());
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: facing, width: { ideal: 480 }, height: { ideal: 480 }, aspectRatio: 1 },
          audio: true,
        });
      } catch {
        finish(null);
        alert("Нет доступа к камере или микрофону");
        return;
      }
      video.srcObject = stream;
      video.style.transform = facing === "user" ? "scaleX(-1)" : "none";
    }
    await openCamera();

    el.querySelector("[data-close]").onclick = () => { try { rec?.stop(); } catch {} finish(null); };
    el.querySelector("[data-flip]").onclick = () => { if (!rec) { facing = facing === "user" ? "environment" : "user"; openCamera(); } };

    const stop = () => {
      rec.onstop = () => finish({ blob: new Blob(chunks, { type: rec.mimeType || "video/webm" }), duration: (performance.now() - started) / 1000 });
      rec.stop();
    };

    recBtn.onclick = () => {
      if (rec) return stop();
      const mime = pickMime(["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"]);
      rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 900_000 } : undefined);
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.start(250);
      started = performance.now();
      recBtn.classList.add("on");
      recBtn.setAttribute("aria-label", "Остановить и отправить");
      tick = setInterval(() => {
        const s = (performance.now() - started) / 1000;
        timer.textContent = fmtDur(s);
        ring.setAttribute("stroke-dashoffset", C * (1 - s / MAX_CIRCLE_SEC));
        if (s >= MAX_CIRCLE_SEC) stop();
      }, 100);
    };
  });
}
