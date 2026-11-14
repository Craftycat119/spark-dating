// Голосовые и «кружочки»
import { icons } from "./icons.js";
import { getCamera, getMic, release } from "./media.js";
import { h, pickMime, fmtDur, toast } from "./ui.js";

const MAX_CIRCLE_SEC = 60;
const MAX_VOICE_SEC = 300;

/** Голосовое: start() → stop() возвращает {blob, duration} либо cancel(). */
export class VoiceRecorder {
  async start() {
    this.stream = await getMic();
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
        release("audio");
        resolve({ blob: new Blob(this.chunks, { type: this.rec.mimeType || "audio/webm" }), duration: this.elapsed() });
      };
      this.rec.stop();
    });
  }
  cancel() {
    clearTimeout(this.limit);
    this.rec.onstop = null;
    try { this.rec.stop(); } catch { /* уже остановлен */ }
    release("audio");
  }
}

const SIDE = 480; // кружок записывается квадратом SIDE×SIDE
const CIRCLE_MIME = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"];

/** Рисует кадр видео в квадрат по центру; для фронтальной камеры зеркально, как в превью. */
function drawSquare(ctx, video, mirror) {
  const w = video.videoWidth, hgt = video.videoHeight;
  if (!w || !hgt) return;
  const side = Math.min(w, hgt);
  ctx.save();
  if (mirror) { ctx.translate(SIDE, 0); ctx.scale(-1, 1); }
  ctx.drawImage(video, (w - side) / 2, (hgt - side) / 2, side, side, 0, 0, SIDE, SIDE);
  ctx.restore();
}

/** Chrome пишет webm без длительности: заставляем браузер её посчитать, иначе не работает перемотка. */
function fixDuration(video) {
  return new Promise((resolve) => {
    const done = () => { video.currentTime = 0; resolve(); };
    if (Number.isFinite(video.duration)) return resolve();
    video.addEventListener("timeupdate", function once() { video.removeEventListener("timeupdate", once); done(); });
    video.currentTime = 1e101;
  });
}

/**
 * Кружочек как в Telegram: запись начинается сразу; пауза и продолжение; «Стоп» открывает просмотр
 * с обрезкой начала и конца; отправить можно и сразу во время записи.
 * Возвращает Promise<{blob, duration} | null>.
 */
export function recordCircle() {
  return new Promise(async (resolve) => {
    const C = 2 * Math.PI * 49;
    const el = h(`<div class="circle-recorder" role="dialog" aria-label="Запись видеосообщения">
      <div class="lens">
        <video class="live" playsinline muted autoplay></video>
        <video class="preview" playsinline muted loop hidden></video>
        <svg class="ring" viewBox="0 0 100 100"><circle cx="50" cy="50" r="49" fill="none" stroke="var(--orange)" stroke-width="3"
          stroke-dasharray="${C}" stroke-dashoffset="${C}" stroke-linecap="round"/></svg>
        <span class="sound-hint" hidden>Нажмите, чтобы включить звук</span>
        <button class="icon-btn lens-flip" data-flipcam aria-label="Сменить камеру">${icons.flip}</button>
      </div>
      <div class="timer"><i class="rec-dot"></i><span>0:00</span></div>
      <div class="trim" hidden>
        <div class="trim-track"><div class="film"></div><div class="trim-sel"></div><div class="trim-pos"></div></div>
        <input type="range" class="trim-a" min="0" max="1000" value="0" aria-label="Начало">
        <input type="range" class="trim-b" min="0" max="1000" value="1000" aria-label="Конец">
        <div class="trim-times"><span data-a>0:00</span><span data-len></span><span data-b></span></div>
      </div>
      <div class="controls rec-mode">
        <button class="icon-btn" data-cancel aria-label="Отменить">${icons.x}</button>
        <button class="icon-btn big" data-pause aria-label="Пауза">${icons.pause}</button>
        <button class="icon-btn big" data-stop aria-label="Остановить и посмотреть">${icons.stop}</button>
        <button class="icon-btn send" data-send aria-label="Отправить">${icons.send}</button>
      </div>
      <div class="controls preview-mode" hidden>
        <button class="icon-btn" data-delete aria-label="Удалить">${icons.trash}</button>
        <button class="icon-btn big" data-resume aria-label="Продолжить запись" hidden>${icons.circle}</button>
        <button class="icon-btn send" data-send2 aria-label="Отправить">${icons.send}</button>
      </div>
      <p class="muted small hint">До ${MAX_CIRCLE_SEC} секунд</p>
    </div>`);
    document.body.append(el);
    const $q = (sel) => el.querySelector(sel);
    const live = $q("video.live"), preview = $q("video.preview"), ring = $q("circle"), timer = $q(".timer span");
    // Этот же канвас и пишется в кружок, и показывается вместо <video>: в Telegram на iPhone видео с камеры бывает чёрным
    const canvas = document.createElement("canvas");
    canvas.className = "live-canvas";
    canvas.width = canvas.height = SIDE;
    live.after(canvas);
    const ctx = canvas.getContext("2d");

    let facing = "user", camStream = null, micStream = null, rec = null, chunks = [], frame = 0, tick = 0;
    let recorded = 0, spanStart = 0, paused = false, closed = false;
    let blob = null, total = 0, a = 0, b = 0;

    const elapsed = () => recorded + (paused || !spanStart ? 0 : (performance.now() - spanStart) / 1000);
    const stopTracks = () => { if (camStream) release("video"); if (micStream) release("audio"); }; // общие потоки — гаснут сами чуть позже
    const close = (result) => {
      if (closed) return;
      closed = true;
      cancelAnimationFrame(frame);
      clearInterval(tick);
      try { if (rec && rec.state !== "inactive") { rec.onstop = null; rec.stop(); } } catch { /* уже остановлен */ }
      stopTracks();
      if (preview.src) URL.revokeObjectURL(preview.src);
      el.remove();
      resolve(result);
    };

    async function openCamera() {
      camStream = await getCamera(facing);
      live.muted = true;
      live.playsInline = true;
      live.setAttribute("playsinline", "");
      live.srcObject = camStream;
      live.play().catch(() => {}); // iPhone: картинка камеры может не стартовать сама
      live.style.transform = facing === "user" ? "scaleX(-1)" : "none";
    }
    try {
      // звук отдельным потоком: при смене камеры во время записи он не прерывается
      micStream = await getMic();
      await openCamera();
    } catch {
      close(null);
      return toast("Нет доступа к камере или микрофону", { error: true });
    }

    const draw = () => { drawSquare(ctx, live, facing === "user"); frame = requestAnimationFrame(draw); };
    const showTime = () => {
      const s = elapsed();
      timer.textContent = fmtDur(s);
      ring.setAttribute("stroke-dashoffset", C * (1 - Math.min(s, MAX_CIRCLE_SEC) / MAX_CIRCLE_SEC));
      if (s >= MAX_CIRCLE_SEC) finishRecording(false);
    };

    // запись стартует сразу, как только камера дала первый кадр
    await new Promise((r) => (live.readyState >= 2 ? r() : (live.onloadeddata = r)));
    draw();
    const mime = pickMime(CIRCLE_MIME);
    const out = new MediaStream([...canvas.captureStream(30).getVideoTracks(), ...micStream.getAudioTracks()]);
    rec = new MediaRecorder(out, mime ? { mimeType: mime, videoBitsPerSecond: 900_000 } : undefined);
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.start(250);
    spanStart = performance.now();
    tick = setInterval(showTime, 100);

    const pauseBtn = $q("[data-pause]");
    pauseBtn.onclick = async () => {
      if (!rec || rec.state === "inactive" || paused) return;
      rec.pause();
      recorded = elapsed();
      paused = true;
      // всё записанное до паузы — в файл: покажем раскадровку, можно обрезать с любой стороны и отправить
      await new Promise((r) => {
        const done = () => { rec.removeEventListener("dataavailable", done); setTimeout(r, 0); };
        rec.addEventListener("dataavailable", done);
        try { rec.requestData(); } catch { r(); }
        setTimeout(r, 800);
      });
      if (closed) return;
      blob = new Blob(chunks, { type: rec.mimeType || mime || "video/webm" });
      total = recorded;
      cancelAnimationFrame(frame); // камера в канвас больше не рисует: он понадобится для обрезки
      $q("[data-resume]").hidden = false;
      openPreview();
    };
    $q("[data-resume]").onclick = () => {
      // продолжаем запись: обрезка сбрасывается, кружок пишется дальше
      if (!rec || rec.state !== "paused") return;
      preview.pause();
      if (preview.src) URL.revokeObjectURL(preview.src);
      preview.removeAttribute("src");
      blob = null;
      el.classList.remove("previewing");
      preview.hidden = true;
      canvas.hidden = false;
      $q("[data-flipcam]").hidden = false;
      $q(".rec-mode").hidden = false;
      $q(".preview-mode").hidden = true;
      $q("[data-resume]").hidden = true;
      $q(".trim").hidden = true;
      $q(".sound-hint").hidden = true;
      $q(".hint").textContent = `До ${MAX_CIRCLE_SEC} секунд`;
      ia.value = 0; ib.value = 1000;
      draw(); // снова рисуем камеру в канвас, который пишется в кружок
      rec.resume();
      spanStart = performance.now();
      paused = false;
      tick = setInterval(showTime, 100);
    };

    // смена камеры работает и во время записи: пишем канвас, а звук идёт отдельным потоком
    $q("[data-flipcam]").onclick = async () => {
      facing = facing === "user" ? "environment" : "user";
      try { await openCamera(); } catch { facing = facing === "user" ? "environment" : "user"; }
    };

    function stopRecorder() {
      return new Promise((r) => {
        if (!rec || rec.state === "inactive") return r();
        if (!paused) recorded = elapsed();
        paused = true;
        rec.onstop = r;
        rec.stop();
      });
    }

    async function finishRecording(sendNow) {
      if (closed || blob) return;
      clearInterval(tick);
      await stopRecorder();
      cancelAnimationFrame(frame);
      stopTracks();
      total = recorded;
      blob = new Blob(chunks, { type: rec.mimeType || mime || "video/webm" });
      if (sendNow) return close(total > 0.6 ? { blob, duration: total } : null);
      openPreview();
    }

    $q("[data-cancel]").onclick = () => close(null);
    $q("[data-stop]").onclick = () => finishRecording(false);
    $q("[data-send]").onclick = () => finishRecording(true);
    $q("[data-delete]").onclick = () => close(null);

    // ---- просмотр и обрезка ----
    const ia = $q(".trim-a"), ib = $q(".trim-b"), sel = $q(".trim-sel"), pos = $q(".trim-pos");
    const fmtT = (t) => fmtDur(Math.max(0, t));

    async function openPreview() {
      clearInterval(tick);
      el.classList.remove("paused");
      el.classList.add("previewing");
      live.hidden = true;
      canvas.hidden = true;
      preview.hidden = false;
      preview.muted = true;
      preview.playsInline = true;
      $q("[data-flipcam]").hidden = true;
      $q(".rec-mode").hidden = true;
      $q(".preview-mode").hidden = false;
      $q(".trim").hidden = false;
      $q(".sound-hint").hidden = false;
      $q(".hint").textContent = rec && rec.state === "paused"
        ? "Потяните края полосы, чтобы обрезать. ◎ — продолжить запись"
        : "Потяните края полосы, чтобы обрезать начало и конец";
      ring.setAttribute("stroke-dashoffset", 0);
      preview.src = URL.createObjectURL(blob);
      await new Promise((r) => (preview.readyState >= 1 ? r() : (preview.onloadedmetadata = r)));
      await fixDuration(preview);
      if (Number.isFinite(preview.duration) && preview.duration > 0) total = preview.duration;
      a = 0; b = total;
      updateTrim();
      preview.play().catch(() => {});
      drawFilm();
    }

    // Раскадровка: 8 кадров из записанного — под полосой обрезки
    async function drawFilm() {
      const film = $q(".film");
      film.replaceChildren();
      const N = 8;
      const v = document.createElement("video");
      v.muted = true;
      v.playsInline = true;
      v.preload = "auto";
      v.src = preview.src;
      try {
        await new Promise((r, j) => { v.onloadeddata = r; v.onerror = j; setTimeout(r, 3000); });
        await fixDuration(v);
        const dur = Number.isFinite(v.duration) && v.duration > 0 ? v.duration : total;
        const c = document.createElement("canvas");
        c.width = c.height = 64;
        const cx = c.getContext("2d");
        for (let i = 0; i < N && !closed; i++) {
          v.currentTime = Math.min(dur - 0.05, ((i + 0.5) / N) * dur);
          await new Promise((r) => { v.onseeked = r; setTimeout(r, 1500); });
          const s = Math.min(v.videoWidth, v.videoHeight) || 1;
          cx.drawImage(v, (v.videoWidth - s) / 2, (v.videoHeight - s) / 2, s, s, 0, 0, 64, 64);
          film.append(Object.assign(document.createElement("img"), { src: c.toDataURL("image/jpeg", 0.7), alt: "" }));
        }
      } catch { /* без раскадровки обрезка всё равно работает */ }
      v.removeAttribute("src");
    }

    function updateTrim(which) {
      let va = +ia.value, vb = +ib.value;
      const minGap = Math.min(1000, (1 / total) * 1000); // не короче секунды
      if (va > vb - minGap) { if (which === "a") va = ia.value = Math.max(0, vb - minGap); else vb = ib.value = Math.min(1000, va + minGap); }
      a = (va / 1000) * total;
      b = (vb / 1000) * total;
      sel.style.left = va / 10 + "%";
      sel.style.right = 100 - vb / 10 + "%";
      $q("[data-a]").textContent = fmtT(a);
      $q("[data-b]").textContent = fmtT(b);
      $q("[data-len]").textContent = fmtT(b - a);
      if (which === "a") preview.currentTime = a;
      if (which === "b") preview.currentTime = Math.max(a, b - 0.8);
    }
    ia.oninput = () => updateTrim("a");
    ib.oninput = () => updateTrim("b");
    preview.ontimeupdate = () => {
      if (preview.currentTime >= b || preview.currentTime < a - 0.05) preview.currentTime = a; // крутим только выбранный кусок
      pos.style.left = (preview.currentTime / total) * 100 + "%";
    };
    preview.onclick = () => { preview.muted = !preview.muted; $q(".sound-hint").hidden = true; };

    $q("[data-send2]").onclick = async () => {
      const trimmed = a > 0.15 || b < total - 0.15;
      if (!trimmed) return close({ blob, duration: total });
      // Обрезка: проигрываем выбранный кусок и записываем его заново (на устройстве, без сервера).
      // AudioContext создаём прямо в нажатии — так iPhone разрешает звук.
      const btn = $q("[data-send2]");
      btn.disabled = true;
      $q(".hint").textContent = "Обрезаем кружок…";
      el.classList.add("busy");
      try {
        const ac = new (window.AudioContext || window.webkitAudioContext)();
        const src = ac.createMediaElementSource(preview);
        const dest = ac.createMediaStreamDestination();
        src.connect(dest); // звук идёт только в запись, не в динамик
        preview.loop = false;
        preview.muted = false;
        preview.ontimeupdate = () => (pos.style.left = (preview.currentTime / total) * 100 + "%");
        preview.currentTime = a;
        await new Promise((r) => (preview.onseeked = r));
        const out = new MediaStream([...canvas.captureStream(30).getVideoTracks(), ...dest.stream.getAudioTracks()]);
        const r2 = new MediaRecorder(out, mime ? { mimeType: mime, videoBitsPerSecond: 900_000 } : undefined);
        const parts = [];
        r2.ondataavailable = (e) => e.data.size && parts.push(e.data);
        const loop = () => {
          drawSquare(ctx, preview, false); // кадры уже зеркальные
          if (preview.currentTime >= b || preview.ended) { r2.state !== "inactive" && r2.stop(); return; }
          frame = requestAnimationFrame(loop);
        };
        const stopped = new Promise((r) => (r2.onstop = r));
        r2.start(250);
        await preview.play();
        loop();
        await stopped;
        preview.pause();
        ac.close().catch(() => {});
        close({ blob: new Blob(parts, { type: r2.mimeType || blob.type }), duration: b - a });
      } catch {
        close({ blob, duration: total }); // не вышло обрезать — отправляем целиком, чем ничего
      }
    };
  });
}
