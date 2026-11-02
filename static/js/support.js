// Поддержка (помощь, жалобы, предложения) и помощник по рекламе
import { api, on } from "./api.js";
import { icons } from "./icons.js";
import { $, $$, esc, fmtShort, fmtTime, h, toast } from "./ui.js";

const CAT = { help: "Помощь", complaint: "Жалоба", suggestion: "Предложение", ads: "Реклама" };
const ADS_QUICK = ["Какие форматы рекламы?", "Сколько стоит?", "Какая аудитория?", "Оставить заявку"];

export async function renderSupportHub({ screen, go, back = "#/settings" }) {
  const root = screen(`
    <div class="guide-top"><a class="icon-btn" href="${back}" aria-label="Назад">${icons.back}</a><span class="logo">cofi<span>°</span></span><span style="width:44px"></span></div>
    <h1>Поддержка</h1>
    <p class="lead" style="margin-top:10px">Оператор отвечает прямо в чате, обычно в течение часа.</p>
    <div class="support-new">
      <button class="row-link" data-new="help"><span><b>Нужна помощь</b><br><span class="muted small">Вопрос по приложению или аккаунту</span></span>${icons.headset}</button>
      <button class="row-link" data-new="complaint"><span><b>Пожаловаться</b><br><span class="muted small">Спам, оскорбления, фейковая анкета</span></span>${icons.flag}</button>
      <button class="row-link" data-new="suggestion"><span><b>Предложить идею</b><br><span class="muted small">Что добавить или улучшить</span></span>${icons.sparkle}</button>
    </div>
    <h3 style="margin:26px 0 8px">Мои обращения</h3>
    <div class="thread-list"><p class="muted small">Загружаем…</p></div>`, { nav: false });
  $$("[data-new]", root).forEach((b) => (b.onclick = async () => {
    try {
      const t = await api.post("/api/support/threads", { topic: "support", category: b.dataset.new });
      go(`#/support/${t.id}`);
    } catch (ex) { toast(ex.message, { error: true }); }
  }));
  try {
    const list = (await api.get("/api/support/threads")).filter((t) => t.topic === "support");
    $(".thread-list", root).innerHTML = list.length
      ? list.map((t) => `<a class="chat-item" href="#/support/${t.id}"><span class="body"><span class="top"><b>${CAT[t.category]} №${t.id}</b><span class="time">${fmtShort(t.updated_at)}</span></span>
          <span class="preview">${t.status === "open" ? "Открыто" : "Решено"}</span></span></a>`).join("")
      : `<p class="muted small">Обращений пока нет.</p>`;
  } catch (ex) { toast(ex.message, { error: true }); }
}

/** Открыть жалобу на анкету и сразу перейти в чат с поддержкой. */
export async function reportUser(user, go) {
  try {
    const t = await api.post("/api/support/threads", { topic: "support", category: "complaint", about_user_id: user.id });
    go(`#/support/${t.id}`);
  } catch (ex) { toast(ex.message, { error: true }); }
}

export async function renderAds({ screen, go, loggedIn }) {
  try {
    const mine = (await api.get("/api/support/threads")).find((t) => t.topic === "ads");
    const t = mine || (await api.post("/api/support/threads", { topic: "ads" }));
    renderThread({ screen, threadId: t.id, back: loggedIn ? "#/settings" : "#/", ads: true });
  } catch (ex) { toast(ex.message, { error: true }); go("#/"); }
}

export async function renderThread({ screen, threadId, back = "#/support", ads = false }) {
  let t;
  try { t = await api.get(`/api/support/threads/${threadId}`); } catch (ex) { return toast(ex.message, { error: true }); }
  ads = ads || t.topic === "ads";
  const root = screen(`
    <div class="support-chat">
      <header class="chat-header">
        <a class="icon-btn" href="${back}" aria-label="Назад">${icons.back}</a>
        <span class="avatar support-ava">${ads ? icons.megaphone : icons.headset}</span>
        <div class="who"><b>${ads ? "Реклама в COFI" : `${CAT[t.category]} №${t.id}`}</b><small class="status">${ads ? "Помощник и менеджер" : t.status === "open" ? "Оператор на связи" : "Решено"}</small></div>
      </header>
      <div class="messages" tabindex="0"></div>
      ${ads ? `<div class="quick">${ADS_QUICK.map((q) => `<button class="chip" data-q="${q}">${q}</button>`).join("")}</div>` : ""}
      <form class="composer"><textarea rows="1" placeholder="Сообщение" aria-label="Сообщение" maxlength="4000"></textarea>
        <button class="icon-btn send" aria-label="Отправить">${icons.send}</button></form>
    </div>`, { nav: false });
  const list = $(".messages", root);
  const seen = new Set();
  const label = { bot: ads ? "Помощник" : "Поддержка", staff: ads ? "Менеджер" : "Оператор" };
  const add = (m) => {
    if (seen.has(m.id)) return;
    seen.add(m.id);
    const mine = m.author === "user";
    list.append(h(`<div class="msg ${mine ? "mine" : ""}">${mine ? "" : `<div class="who-label">${label[m.author]}</div>`}
      <div class="bubble text" ${mine || m.author === "staff" ? 'translate="no"' : ""}>${esc(m.text)}<span class="time">${fmtTime(m.created_at)}</span></div></div>`));
    list.scrollTop = list.scrollHeight;
  };
  t.messages.forEach(add);
  const sendText = async (text) => {
    text = text.trim();
    if (!text) return;
    try {
      await api.post(`/api/support/threads/${t.id}/messages`, { text });
      await refresh();
    } catch (ex) { toast(ex.message, { error: true }); }
  };
  async function refresh() {
    try { (await api.get(`/api/support/threads/${t.id}`)).messages.forEach(add); } catch { /* сеть */ }
  }
  const form = $("form", root);
  const ta = $("textarea", form);
  form.onsubmit = (e) => { e.preventDefault(); const v = ta.value; ta.value = ""; sendText(v); };
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); form.requestSubmit(); }
  });
  $$("[data-q]", root).forEach((b) => (b.onclick = () => sendText(b.dataset.q)));
  // ответы оператора: через WebSocket для вошедших, опросом для рекламодателей без аккаунта
  const off = on("support", (d) => d.thread_id === t.id && add(d.message));
  const timer = setInterval(() => (root.isConnected ? refresh() : (clearInterval(timer), off())), 6000);
}
