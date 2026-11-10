// Аудио- и видеозвонки через WebRTC. Сигналинг идёт через WebSocket сервера.
import { api, on, send } from "./api.js";
import { icons } from "./icons.js";
import { esc, fmtDur, h, toast } from "./ui.js";

let iceServers = [{ urls: "stun:stun.l.google.com:19302" }];
let current = null; // активный звонок
const NO_ROUTE = "Не получилось соединиться. Скорее всего, у кого-то из вас мобильный интернет: для таких звонков на сервере нужен TURN (README, раздел «Звонки»)";
let lookupPeer = () => null; // conversation_id → {name, photo_url}

export function initCalls(config, peerLookup) {
  iceServers = config.ice_servers || iceServers;
  lookupPeer = peerLookup;
  on("call:offer", onOffer);
  on("call:answer", (d) => current?.id === d.call_id && current.onAnswer(d));
  on("call:ice", (d) => current?.id === d.call_id && current.onIce(d));
  on("call:end", (d) => current?.id === d.call_id && current.close("Звонок завершён"));
  on("call:reject", (d) => current?.id === d.call_id && current.close("Собеседник отклонил звонок"));
  on("call:busy", (d) => current?.id === d.call_id && current.close("Собеседник уже разговаривает"));
  on("call:notified", (d) => current?.id === d.call_id && current.onNotified());
  on("call:gone", () => toast("Звонок уже завершён"));
  on("call:unavailable", (d) => current?.id === d.call_id && current.close(
    d.reason === "bot" ? "В демо боты не отвечают на звонки. Позвонить можно реальному человеку" : "Собеседник сейчас не в сети"));
}

/** Открыли COFI кнопкой «Ответить» из Telegram: забираем ждущий звонок, как только подключится сокет. */
export function joinPendingCall(callId) {
  const join = () => send({ type: "call:join", call_id: callId });
  if (!join()) {
    const off = on("socket:open", () => { join(); off(); });
  }
}

/** Серверы для звонка с временным паролем TURN: берём перед каждым звонком (пароль живёт час). */
async function refreshIce() {
  try { iceServers = await api.get("/api/calls/ice"); } catch { /* остаются STUN из настроек */ }
}

export async function startCall(conversationId, peer, video) {
  if (current) return toast("Сначала завершите текущий звонок", { error: true });
  await refreshIce();
  if (current) return;
  current = new Call({ conversationId, peer, video, outgoing: true });
  current.dial();
}

async function onOffer(d) {
  await refreshIce();
  if (current && current.id === d.call_id) {
    // тот же звонок пришёл ещё раз: открыли COFI кнопкой «Ответить» в Telegram, пока он звонил в приложении
    if (d.answer_now && !current.outgoing && !current.pc) current.accept();
    return;
  }
  if (current) {
    send({ type: "call:busy", conversation_id: d.conversation_id, call_id: d.call_id });
    return;
  }
  const peer = (await lookupPeer(d.conversation_id)) || { name: d.from.name };
  current = new Call({ conversationId: d.conversation_id, peer, video: !!d.video, outgoing: false, id: d.call_id, offer: d.sdp });
  if (d.answer_now) current.accept(); // уже нажали «Ответить» в Telegram
  else current.ring();
}

// Простой рингтон на WebAudio — без файлов
function ringtone() {
  try {
    const ctx = new AudioContext();
    let stopped = false;
    const beep = () => {
      if (stopped) return;
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 660;
      g.gain.setValueAtTime(0.0001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.05);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.9);
      o.connect(g).connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + 1);
      setTimeout(beep, 2200);
    };
    beep();
    return () => { if (stopped) return; stopped = true; ctx.close().catch(() => {}); };
  } catch { return () => {}; }
}

class Call {
  constructor({ conversationId, peer, video, outgoing, id, offer }) {
    this.conversationId = conversationId;
    this.peer = peer;
    this.video = video;
    this.outgoing = outgoing;
    this.id = id || crypto.randomUUID?.() || String(Math.random()).slice(2);
    this.offer = offer;
    this.pendingIce = [];
    this.render();
  }

  signal(type, extra = {}) {
    send({ type, conversation_id: this.conversationId, call_id: this.id, ...extra });
  }

  render() {
    this.el = h(`<div class="call ${this.outgoing ? "" : "ringing"}" role="dialog" aria-label="Звонок">
      <video class="remote" playsinline autoplay hidden></video>
      <video class="local" playsinline autoplay muted hidden></video>
      <div class="persona">
        ${this.peer.photo_url ? `<img src="${esc(this.peer.photo_url)}" alt="">` : ""}
        <div><h2>${esc(this.peer.name)}</h2>
        <p class="status muted"></p></div>
      </div>
      <div class="bar"></div>
      <audio autoplay></audio>
    </div>`);
    this.status = this.el.querySelector(".status");
    this.remoteVideo = this.el.querySelector(".remote");
    this.localVideo = this.el.querySelector(".local");
    this.audio = this.el.querySelector("audio");
    document.body.append(this.el);
  }

  setBar(buttons) {
    const bar = this.el.querySelector(".bar");
    bar.replaceChildren(...buttons.map(([cls, icon, label, fn]) => {
      const b = h(`<button class="${cls}" aria-label="${label}">${icon}</button>`);
      b.onclick = fn;
      return b;
    }));
  }

  activeBar() {
    const buttons = [
      ["", icons.mic, "Выключить микрофон", (e) => this.toggle("audio", e.currentTarget, icons.mic, icons.micOff)],
    ];
    if (this.video) buttons.push(["", icons.video, "Выключить камеру", (e) => this.toggle("video", e.currentTarget, icons.video, icons.videoOff)]);
    buttons.push(["hang", icons.hang, "Завершить", () => this.hangup()]);
    this.setBar(buttons);
  }

  toggle(kind, btn, onIcon, offIcon) {
    const tracks = kind === "audio" ? this.local.getAudioTracks() : this.local.getVideoTracks();
    const enabled = !tracks[0]?.enabled;
    tracks.forEach((t) => (t.enabled = enabled));
    btn.classList.toggle("off", !enabled);
    btn.innerHTML = enabled ? onIcon : offIcon;
  }

  async getMedia() {
    this.local = await navigator.mediaDevices.getUserMedia({
      // эхоподавление, шумоподавление и автоусиление браузера; моно — меньше эха и трафика
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: { ideal: 1 } },
      video: this.video ? { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } } : false,
    });
    if (this.video) {
      this.localVideo.srcObject = this.local;
      this.localVideo.hidden = false;
    }
  }

  createPeer() {
    this.pc = new RTCPeerConnection({ iceServers });
    this.local.getTracks().forEach((t) => this.pc.addTrack(t, this.local));
    this.pc.onicecandidate = (e) => e.candidate && this.signal("call:ice", { candidate: e.candidate });
    this.pc.ontrack = (e) => {
      const stream = e.streams[0];
      this.audio.srcObject = stream;
      if (e.track.kind === "video") {
        this.remoteVideo.srcObject = stream;
        this.remoteVideo.hidden = false;
        this.remoteVideo.muted = true; // звук идёт через <audio>
        this.el.classList.add("has-video");
      }
    };
    const onState = () => {
      const s = this.pc.connectionState || this.pc.iceConnectionState;
      if (s === "connected" || s === "completed") {
        clearTimeout(this.connectTimeout);
        this.startTimer();
        // на компьютере звук из динамиков снова попадает в микрофон: подсказываем про наушники
        if (!this.video && !matchMedia("(pointer: coarse)").matches) {
          this.el.querySelector(".persona").insertAdjacentHTML("beforeend", `<p class="call-tip">Если собеседник слышит эхо, наденьте наушники или убавьте звук</p>`);
        }
      }
      if (s === "failed") this.hangup(this.timer ? "Соединение потеряно" : NO_ROUTE);
    };
    this.pc.onconnectionstatechange = onState;
    this.pc.oniceconnectionstatechange = onState; // старые Safari не знают connectionState
  }

  async dial() {
    this.status.textContent = this.video ? "Видеозвонок…" : "Звоним…";
    this.setBar([["hang", icons.hang, "Отменить", () => this.hangup()]]);
    try {
      await this.getMedia();
    } catch {
      return this.close("Нет доступа к микрофону или камере");
    }
    this.createPeer();
    const offer = await this.pc.createOffer();
    await this.pc.setLocalDescription(offer);
    this.signal("call:offer", { sdp: this.pc.localDescription, video: this.video });
    this.noAnswer = setTimeout(() => this.hangup("Никто не ответил"), 45000);
  }

  ring() {
    this.status.textContent = this.video ? "Входящий видеозвонок" : "Входящий звонок";
    this.stopRing = ringtone();
    this.setBar([
      ["hang", icons.hang, "Отклонить", () => { this.signal("call:reject"); this.close(); }],
      ["accept", this.video ? icons.video : icons.phone, "Ответить", () => this.accept()],
    ]);
    this.noAnswer = setTimeout(() => this.close("Пропущенный звонок"), 45000);
  }

  async accept() {
    this.stopRing?.();
    clearTimeout(this.noAnswer);
    this.el.classList.remove("ringing");
    this.status.textContent = "Соединяем…";
    try {
      await this.getMedia();
    } catch {
      this.signal("call:reject");
      return this.close("Нет доступа к микрофону или камере");
    }
    this.createPeer();
    await this.pc.setRemoteDescription(this.offer);
    await this.flushIce();
    const answer = await this.pc.createAnswer();
    await this.pc.setLocalDescription(answer);
    this.signal("call:answer", { sdp: this.pc.localDescription });
    this.activeBar();
    this.watchConnect();
  }

  onNotified() {
    // собеседник не в сети: ему ушёл звонок в Telegram, ждём подольше
    this.status.textContent = "Собеседник не в сети. Звонок отправлен в Telegram, ждём ответа…";
    clearTimeout(this.noAnswer);
    this.noAnswer = setTimeout(() => this.hangup("Никто не ответил"), 75000);
  }

  async onAnswer(d) {
    clearTimeout(this.noAnswer);
    await this.pc.setRemoteDescription(d.sdp);
    await this.flushIce();
    this.status.textContent = "Соединяем…";
    this.activeBar();
    this.watchConnect();
  }

  /** Если за 20 секунд связь не установилась, не висим на «Соединяем…», а честно говорим почему. */
  watchConnect() {
    clearTimeout(this.connectTimeout);
    this.connectTimeout = setTimeout(() => !this.timer && this.hangup(NO_ROUTE), 20000);
  }

  async onIce(d) {
    if (!this.pc || !this.pc.remoteDescription) return this.pendingIce.push(d.candidate);
    try { await this.pc.addIceCandidate(d.candidate); } catch { /* устаревший кандидат */ }
  }

  async flushIce() {
    for (const c of this.pendingIce.splice(0)) {
      try { await this.pc.addIceCandidate(c); } catch { /* пропускаем */ }
    }
  }

  startTimer() {
    if (this.timer) return;
    const t0 = Date.now();
    const tick = () => (this.status.textContent = fmtDur((Date.now() - t0) / 1000));
    tick();
    this.timer = setInterval(tick, 1000);
  }

  hangup(message) {
    this.signal("call:end");
    this.close(message);
  }

  close(message) {
    this.stopRing?.();
    clearTimeout(this.noAnswer);
    clearInterval(this.timer);
    clearTimeout(this.connectTimeout);
    this.local?.getTracks().forEach((t) => t.stop());
    this.pc?.close();
    this.el.remove();
    if (current === this) current = null;
    if (message) toast(message);
  }
}
