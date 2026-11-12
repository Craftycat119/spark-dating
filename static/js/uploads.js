// Отправка фото, видео, голосовых и кружков в чат по частям.
// * Каждая часть — отдельный запрос: после обрыва или закрытия приложения загрузка продолжается с того же места.
// * Недокачанные файлы лежат на телефоне (IndexedDB). При следующем открытии чата они видны на паузе:
//   нажатие на плитку — продолжить, ещё нажатие — пауза.
// * Строка «Загрузка 2 из 5 · 40%» над полем ввода, крестик справа отменяет всё.
import { ApiError, api } from "./api.js";
import { icons } from "./icons.js";
import { $, h, toast } from "./ui.js";

const CHUNK = 1024 * 1024; // 1 МБ: на медленном интернете кусок доходит за секунды, при обрыве теряется немного
const DB_NAME = "cofi-uploads";

// ---------- хранилище на телефоне ----------
let dbPromise = null;
function db() {
  if (!window.indexedDB) return Promise.reject(new Error("no idb"));
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore("items", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}
async function store(mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const tx = d.transaction("items", mode);
    const req = fn(tx.objectStore("items"));
    tx.oncomplete = () => resolve(req?.result);
    tx.onerror = tx.onabort = () => reject(tx.error);
  });
}
const saveItem = (it) => store("readwrite", (s) => s.put(pick(it))).catch(() => {}); // нет места — просто без продолжения после закрытия
const dropItem = (id) => store("readwrite", (s) => s.delete(id)).catch(() => {});
const loadItems = (convId) => store("readonly", (s) => s.getAll()).then((all) => (all || []).filter((x) => x.convId === convId)).catch(() => []);
const pick = ({ id, convId, kind, blob, name, type, size, duration, uid, created }) => ({ id, convId, kind, blob, name, type, size, duration, uid, created });

// ---------- вид ----------
export const fmtSize = (b) => (b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} КБ` : `${(b / 1024 / 1024).toFixed(b < 10 * 1024 * 1024 ? 1 : 0).replace(".", ",")} МБ`);
const R = 22, C = 2 * Math.PI * R;

function tileEl(it) {
  const url = URL.createObjectURL(it.blob);
  const media = it.kind === "image" ? `<img src="${url}" alt="">`
    : it.kind === "video" || it.kind === "circle" ? `<video src="${url}#t=0.1" muted playsinline preload="metadata"></video>`
      : `<div class="pend-voice">${icons.mic}</div>`;
  const el = h(`<div class="msg media mine pending-msg ${it.kind === "circle" ? "circle" : ""}">
    <div class="bubble"><div class="pend-media">${media}</div>
      <button class="pend-btn" aria-label="Пауза или продолжить">
        <svg viewBox="0 0 50 50"><circle cx="25" cy="25" r="${R}" class="track"/><circle cx="25" cy="25" r="${R}" class="bar" stroke-dasharray="${C}" stroke-dashoffset="${C}"/></svg>
        <span class="ico"></span>
      </button>
      <span class="pend-size"></span>
    </div></div>`);
  el._url = url;
  return el;
}

/** Очередь загрузок одного чата. hooks: {box, status, convId, onSent(message)} */
export function createUploader({ box, status, convId, onSent }) {
  const items = []; // в порядке добавления
  let active = null, xhr = null, batchDone = 0;

  const statusText = $(":scope > span", status), statusBar = $(":scope > i > b", status);
  $("[data-cancel-all]", status).onclick = cancelAll;

  function render(it) {
    const el = it.el;
    const p = it.size ? it.sent / it.size : 0;
    $(".bar", el).setAttribute("stroke-dashoffset", C * (1 - p));
    el.classList.toggle("paused", it.state === "paused");
    el.classList.toggle("running", it.state === "running");
    $(".ico", el).innerHTML = it.state === "paused" ? icons.arrow : icons.pause; // в очереди тоже можно поставить на паузу
    $(".pend-size", el).textContent = it.sent && it.state !== "queued" ? `${fmtSize(it.sent)} / ${fmtSize(it.size)}` : fmtSize(it.size);
    renderStatus();
  }
  function renderStatus() {
    const live = items.filter((x) => x.state !== "paused");
    if (!live.length) { status.hidden = true; return; }
    const total = batchDone + live.length, n = batchDone + 1;
    const cur = active || live[0];
    const p = cur.size ? cur.sent / cur.size : 0;
    status.hidden = false;
    statusText.textContent = `Загрузка ${total > 1 ? `${n} из ${total} · ` : ""}${Math.round(p * 100)}% · ${fmtSize(cur.sent)} из ${fmtSize(cur.size)}`;
    statusBar.style.width = `${((batchDone + p) / total) * 100}%`;
  }

  function addTile(it) {
    it.el = tileEl(it);
    $(".pend-btn", it.el).onclick = (e) => { e.stopPropagation(); toggle(it); };
    $(".pend-media", it.el).onclick = () => toggle(it);
    box.append(it.el);
    render(it);
    it.el.scrollIntoView?.({ block: "end" });
  }
  function remove(it) {
    const i = items.indexOf(it);
    if (i >= 0) items.splice(i, 1);
    URL.revokeObjectURL(it.el?._url);
    it.el?.remove();
    dropItem(it.id);
    renderStatus();
  }

  function toggle(it) {
    if (it.state === "paused") { it.state = "queued"; it.tries = 0; render(it); pump(); return; }
    // идёт или ждёт очереди — на паузу
    if (it === active) xhr?.abort();
    it.state = "paused";
    render(it);
  }

  function cancelAll() {
    xhr?.abort();
    for (const it of [...items]) {
      if (it.uid) api.del(`/api/chats/${convId}/uploads/${it.uid}`).catch(() => {});
      remove(it);
    }
    active = null;
    batchDone = 0;
    renderStatus();
  }

  function send(method, url, body, onProgress) {
    return new Promise((resolve, reject) => {
      xhr = new XMLHttpRequest();
      xhr.open(method, url);
      xhr.withCredentials = true;
      xhr.responseType = "json";
      if (body && !(body instanceof Blob)) xhr.setRequestHeader("Content-Type", "application/json");
      xhr.upload.onprogress = (e) => onProgress?.(e.loaded);
      xhr.onabort = () => reject(new ApiError(-1, "aborted"));
      xhr.onerror = () => reject(new ApiError(0, "Нет соединения с сервером"));
      xhr.onload = () => {
        const data = xhr.response;
        if (xhr.status >= 200 && xhr.status < 300) return resolve(data);
        reject(new ApiError(xhr.status, data?.detail ?? (xhr.status === 413 ? "Файл слишком большой" : "Ошибка сервера")));
      };
      xhr.send(body instanceof Blob ? body : body ? JSON.stringify(body) : null);
    });
  }

  async function run(it) {
    const base = `/api/chats/${convId}/uploads`;
    if (it.uid) {
      try {
        it.sent = (await send("GET", `${base}/${it.uid}`)).received;
      } catch (ex) {
        if (ex.status !== 404) throw ex;
        it.uid = null; // на сервере загрузка устарела — начинаем заново
      }
    }
    if (!it.uid) {
      const r = await send("POST", base, { kind: it.kind, size: it.size, filename: it.name, content_type: it.type, duration: it.duration });
      it.uid = r.id;
      it.sent = 0;
      saveItem(it);
    }
    while (it.sent < it.size) {
      if (it.state !== "running") return false;
      const from = it.sent;
      try {
        const r = await send("PUT", `${base}/${it.uid}?offset=${from}`, it.blob.slice(from, from + CHUNK), (loaded) => {
          it.shown = from + loaded;
          renderProgress(it);
        });
        it.sent = r.received;
      } catch (ex) {
        if (ex.status === 409 && ex.detail?.received != null) { it.sent = ex.detail.received; continue; }
        throw ex;
      }
      render(it);
    }
    const msg = await send("POST", `${base}/${it.uid}/finish`);
    onSent(msg);
    return true;
  }
  function renderProgress(it) {
    const sent = it.sent;
    it.sent = Math.min(it.shown, it.size);
    render(it);
    it.sent = sent;
  }

  async function pump() {
    if (active) return;
    const it = items.find((x) => x.state === "queued");
    if (!it) { batchDone = 0; renderStatus(); return; }
    active = it;
    it.state = "running";
    render(it);
    try {
      if (await run(it)) { batchDone++; remove(it); }
    } catch (ex) {
      if (ex.status === -1) { /* пауза или отмена */ } else if (ex.status === 0 || ex.status >= 500 || ex.status === 429) {
        // связь пропала или приложение свернули — не ошибка, а пауза; при хорошей связи пробуем ещё пару раз сами
        it.tries = (it.tries || 0) + 1;
        it.state = it.tries <= 3 && document.visibilityState === "visible" && navigator.onLine !== false ? "queued" : "paused";
        if (it.state === "queued") await new Promise((r) => setTimeout(r, 1500 * it.tries));
      } else {
        toast(`Не отправлено: ${ex.message}`, { error: true });
        if (it.uid) api.del(`/api/chats/${convId}/uploads/${it.uid}`).catch(() => {});
        remove(it);
      }
    } finally {
      xhr = null;
      active = null;
      if (items.includes(it) && it.state === "running") it.state = "paused";
      if (items.includes(it)) render(it);
      pump();
    }
  }

  return {
    /** Новый файл в очередь. blob — уже готовый к отправке (фото уменьшено). */
    add(kind, blob, { name = "file", duration = null } = {}) {
      const it = { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, convId, kind, blob, name, type: blob.type || "",
        size: blob.size, duration, uid: null, created: Date.now(), sent: 0, state: "queued" };
      items.push(it);
      addTile(it);
      saveItem(it);
      queueMicrotask(pump); // сначала в очередь попадут все выбранные файлы — счётчик сразу «1 из 5»
    },
    /** Недокачанное с прошлого раза: показываем на паузе. */
    async restore() {
      for (const saved of (await loadItems(convId)).sort((a, b) => a.created - b.created)) {
        const it = { ...saved, sent: 0, state: "paused" };
        items.push(it);
        addTile(it);
        if (it.uid) api.get(`/api/chats/${convId}/uploads/${it.uid}`).then((r) => { it.sent = r.received; render(it); }).catch(() => {});
      }
    },
    /** Закрыли чат: текущую загрузку на паузу (продолжится, когда откроют снова). */
    stop() {
      for (const it of items) if (it.state !== "paused") it.state = "paused";
      xhr?.abort();
      for (const it of items) URL.revokeObjectURL(it.el?._url);
    },
  };
}

