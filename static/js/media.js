// Камера и микрофон — один раз на сессию.
// Telegram и Safari спрашивают разрешение при каждом новом запросе к камере. Поэтому поток не закрываем сразу,
// а держим ещё немного после использования: следующий кружок, фото или проверка лица берут уже открытую камеру
// без нового вопроса. Через IDLE_MS без дела камера и микрофон выключаются (гаснет индикатор).

const IDLE_MS = 45000;
const live = { video: null, audio: null };
const timers = { video: 0, audio: 0 };

// «Живой» — дорожка не остановлена и не заглушена системой (входящий звонок, другое приложение забрало микрофон):
// заглушённый микрофон пишет тишину, поэтому такой поток не переиспользуем, а просим новый
const alive = (s) => s && s.getTracks().some((t) => t.readyState === "live" && !t.muted);

/** Камера: facing — "user" (фронтальная) или "environment" (основная). Возвращает общий поток — не останавливайте его сами. */
export async function getCamera(facing = "user") {
  clearTimeout(timers.video);
  const cur = live.video;
  if (alive(cur) && cur._facing === facing) return cur;
  if (cur) cur.getTracks().forEach((t) => t.stop()); // другая камера — переключаемся
  const s = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 1280 } }, audio: false,
  });
  s._facing = facing;
  live.video = s;
  return s;
}

// ---------- Звук при беззвучном режиме iPhone ----------
// Как в Telegram: голосовые, кружки и видео слышно, даже если переключатель «беззвучно» включён.
// iOS 17+ даёт странице выбрать тип звука: «playback» — проигрывание (беззвучный режим его не глушит),
// «play-and-record» — во время записи. На других телефонах и браузерах свойства нет — ничего не делаем.
export const audioSessionSupported = () => typeof navigator !== "undefined" && "audioSession" in navigator;
export function audioMode(type) {
  try { if (audioSessionSupported() && navigator.audioSession.type !== type) navigator.audioSession.type = type; } catch { /* не поддерживается */ }
}
// Любое видео или аудио со звуком на странице — в режиме проигрывания
document.addEventListener("play", (e) => {
  const m = e.target;
  if ((m instanceof HTMLMediaElement) && !m.muted && !alive(live.audio)) audioMode("playback");
}, true);
// нажатие на ролик, голосовое или кружок — режим проигрывания ещё до старта звука
document.addEventListener("pointerdown", (e) => {
  if (e.target.closest?.("video, audio, .voice, .circle-msg") && !alive(live.audio)) audioMode("playback");
}, true);
document.addEventListener("volumechange", (e) => {
  const m = e.target;
  if ((m instanceof HTMLMediaElement) && !m.muted && !m.paused && !alive(live.audio)) audioMode("playback");
}, true);

/** Микрофон для голосовых и кружков.
 *  Эхоподавление выключено: на Android оно переводит телефон в «режим звонка» — запись в Telegram местами
 *  выходит тишиной, а своё голосовое или кружок потом играют еле слышно в разговорный динамик.
 *  Голосовым оно не нужно: во время записи ничего не играет. Шумоподавление и автогромкость оставляем. */
export async function getMic() {
  clearTimeout(timers.audio);
  if (alive(live.audio)) return live.audio;
  audioMode("play-and-record");
  try {
    live.audio = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
  } catch (ex) {
    if (ex?.name === "NotAllowedError" || ex?.name === "SecurityError") throw ex;
    live.audio = await navigator.mediaDevices.getUserMedia({ audio: true }); // старый телефон не понял настройки
  }
  return live.audio;
}

/** Камера/микрофон больше не нужны прямо сейчас: выключим чуть позже, если никто не попросит снова.
 *  Микрофон выключаем сразу: пока он включён, iPhone и Android переводят звук в «режим разговора» —
 *  голосовые и кружки играют еле слышно в разговорный динамик или не играют вовсе. */
export function release(kind = "video") {
  clearTimeout(timers[kind]);
  if (kind === "audio") {
    live.audio?.getTracks().forEach((t) => t.stop());
    live.audio = null;
    audioMode("playback"); // запись закончена — дальше только слушаем
    return;
  }
  timers[kind] = setTimeout(() => {
    live[kind]?.getTracks().forEach((t) => t.stop());
    live[kind] = null;
  }, IDLE_MS);
}

/** Разрешение на камеру уже дано? (чтобы не спрашивать просто так, например при открытии меню «Прикрепить») */
export async function cameraAllowed() {
  if (alive(live.video)) return true;
  try {
    const st = await navigator.permissions?.query({ name: "camera" });
    return st?.state === "granted";
  } catch {
    return false; // браузер не умеет сообщать — не спрашиваем заранее
  }
}

// Приложение свернули/закрыли — камеру выключаем сразу
document.addEventListener("visibilitychange", () => {
  if (document.hidden) for (const k of ["video", "audio"]) { live[k]?.getTracks().forEach((t) => t.stop()); live[k] = null; }
});
