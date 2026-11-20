// Камера и микрофон — один раз на сессию.
// Telegram и Safari спрашивают разрешение при каждом новом запросе к камере. Поэтому поток не закрываем сразу,
// а держим ещё немного после использования: следующий кружок, фото или проверка лица берут уже открытую камеру
// без нового вопроса. Через IDLE_MS без дела камера и микрофон выключаются (гаснет индикатор).

const IDLE_MS = 45000;
const live = { video: null, audio: null };
const timers = { video: 0, audio: 0 };

const alive = (s) => s && s.getTracks().some((t) => t.readyState === "live");

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

/** Микрофон для голосовых и кружков. */
export async function getMic() {
  clearTimeout(timers.audio);
  if (alive(live.audio)) return live.audio;
  live.audio = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  return live.audio;
}

/** Камера/микрофон больше не нужны прямо сейчас: выключим чуть позже, если никто не попросит снова. */
export function release(kind = "video") {
  clearTimeout(timers[kind]);
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
