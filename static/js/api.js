// HTTP-клиент и WebSocket с автопереподключением
export class ApiError extends Error {
  constructor(status, detail) {
    const message = typeof detail === "string" ? detail : detail?.message || "Ошибка запроса";
    super(message);
    this.status = status;
    this.detail = detail;
    this.code = typeof detail === "object" ? detail?.code : undefined;
  }
}

async function request(method, url, body) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch {
    throw new ApiError(0, "Нет соединения с сервером. Проверьте интернет");
  }
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    let detail = data?.detail ?? "Ошибка сервера";
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    throw new ApiError(res.status, detail);
  }
  return data;
}

export const api = {
  get: (u) => request("GET", u),
  post: (u, b) => request("POST", u, b ?? {}),
  put: (u, b) => request("PUT", u, b),
  del: (u) => request("DELETE", u),
};

// --- События в реальном времени ---
const listeners = new Map();
let socket = null;
let retry = 0;
let pingTimer = null;
let wanted = false;

export function on(type, fn) {
  if (!listeners.has(type)) listeners.set(type, new Set());
  listeners.get(type).add(fn);
  return () => listeners.get(type).delete(fn);
}

function emit(type, data) {
  listeners.get(type)?.forEach((fn) => fn(data));
  listeners.get("*")?.forEach((fn) => fn(data));
}

export function connectSocket() {
  wanted = true;
  if (socket && socket.readyState <= 1) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onopen = () => {
    retry = 0;
    clearInterval(pingTimer);
    pingTimer = setInterval(() => send({ type: "ping" }), 25000);
    emit("socket:open", {});
  };
  socket.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      emit(data.type, data);
    } catch { /* игнорируем мусор */ }
  };
  socket.onclose = (e) => {
    clearInterval(pingTimer);
    if (!wanted || e.code === 4401) return;
    retry = Math.min(retry + 1, 6);
    setTimeout(connectSocket, 500 * 2 ** retry);
  };
}

export function disconnectSocket() {
  wanted = false;
  socket?.close();
}

export function send(payload) {
  if (socket?.readyState === 1) {
    socket.send(JSON.stringify(payload));
    return true;
  }
  return false;
}
