// Лента «Питомцы»: листаем вперёд и назад, вместо лайков одна кнопка «Помочь».
// Объявления добавляет администрация через админ-панель.
import { api } from "./api.js";
import { icons } from "./icons.js";
import { $, $$, esc, h, toast } from "./ui.js";

const CATS = [["", "Все"], ["adoption", "Ищут дом"], ["foster", "Передержка"], ["charity", "Помощь и сборы"]];
const CAT_TITLE = { charity: "Помощь и сборы", foster: "Передержка", adoption: "Ищет хозяина" };

export function feedTabs(active, me) {
  const people = me.age_group === "teen" ? "Дружба" : "Знакомства";
  return `<div class="feed-tabs" role="tablist">
    <a href="#/feed" role="tab" class="${active === "people" ? "on" : ""}">${people}</a>
    <a href="#/animals" role="tab" class="${active === "animals" ? "on" : ""}">${icons.paw} Питомцы</a></div>`;
}

export async function renderAnimals({ screen, state, go }) {
  let category = sessionStorage.getItem("animals-cat") || "";
  let items = [], index = 0;
  const adult = state.me.age_group === "adult";
  const root = screen(`
    <div class="topbar"><span class="logo">cofi<span>°</span></span></div>
    ${feedTabs("animals", state.me)}
    <div class="cat-chips">${CATS.map(([k, l]) => `<button class="chip" data-cat="${k}" aria-pressed="${k === category}">${l}</button>`).join("")}</div>
    <div class="pet-stage"><div class="skeleton" style="position:relative;height:420px"></div></div>
    <div class="pet-nav" hidden>
      <button class="icon-btn" data-prev aria-label="Назад">${icons.back}</button>
      <button class="btn help-btn" data-help>${icons.heart} Помочь</button>
      <button class="icon-btn flip" data-next aria-label="Вперёд">${icons.back}</button>
    </div>
    <p class="swipe-hint pet-count"></p>`, { cls: "animals" });
  const stage = $(".pet-stage", root);
  const nav = $(".pet-nav", root);
  const count = $(".pet-count", root);

  async function load() {
    try {
      const r = await api.get(`/api/animals?category=${category}`);
      items = r.items;
      index = 0;
      draw();
    } catch (ex) {
      stage.innerHTML = `<div class="empty"><h2>Лента не загрузилась</h2><p class="muted">${esc(ex.message)}</p></div>`;
    }
  }

  function draw(dir = 0) {
    const p = items[index];
    if (!p) {
      nav.hidden = true;
      count.textContent = "";
      stage.innerHTML = `<div class="empty"><h1>Пока пусто</h1><p class="lead">В этой категории ещё нет объявлений.</p></div>`;
      return;
    }
    nav.hidden = false;
    $("[data-prev]", nav).disabled = index === 0;
    $("[data-next]", nav).disabled = index >= items.length - 1;
    const help = $("[data-help]", nav);
    const closed = p.category === "charity" && !p.fundraising_open;
    help.disabled = closed;
    help.innerHTML = closed ? "Сбор закрыт" : `${icons.heart} Помочь`;
    count.textContent = `${index + 1} из ${items.length}. Листайте влево и вправо`;
    const meta = [p.species, p.age_text, p.city, p.distance_km != null ? `${Math.round(p.distance_km)} км` : ""].filter(Boolean).join(" · ");
    stage.replaceChildren(h(`<article class="pet ${dir > 0 ? "from-right" : dir < 0 ? "from-left" : ""}">
      <div class="pet-photos">
        <div class="track">${(p.photos.length ? p.photos : [null]).map((u) => u ? `<img src="${esc(u)}" alt="">` : `<div class="pet-noimg">${icons.paw}</div>`).join("")}</div>
        ${p.photos.length > 1 ? `<span class="pet-photo-count">1/${p.photos.length}</span>` : ""}
        <span class="pet-cat">${CAT_TITLE[p.category]}</span>
        ${p.category === "charity" ? `<span class="fund ${p.fundraising_open ? "open" : "closed"}">${p.fundraising_open ? "Сбор открыт" : "Сбор закрыт"}</span>` : ""}
      </div>
      <div class="pet-body">
        <h2 class="pet-name" translate="no">${esc(p.name)}</h2>
        ${meta ? `<p class="muted small">${esc(meta)}</p>` : ""}
        ${p.fundraising_goal ? `<p class="pet-goal">Цель сбора: <b translate="no">${esc(p.fundraising_goal)}</b></p>` : ""}
        ${p.description ? `<p class="pet-desc" translate="no">${esc(p.description)}</p>` : ""}
        <p class="muted small">Разместил: <span translate="no">${esc(p.author.name)}</span></p>
        <button class="link more-link" data-more>Подробнее и все фото ${icons.arrow}</button>
        ${p.can_manage ? `<div class="owner-tools">
          ${p.category === "charity" ? `<div class="seg"><button class="chip" data-fund="1" aria-pressed="${p.fundraising_open}">Сбор открыт</button><button class="chip" data-fund="0" aria-pressed="${!p.fundraising_open}">Сбор закрыт</button></div>` : ""}
          <button class="btn danger" data-remove>Снять с публикации</button></div>` : ""}
      </div></article>`));
    $("[data-more]", stage).onclick = () => openPet(p.id, { adult, onChange: (np) => { items[index] = np; draw(); } });
    const track = $(".track", stage);
    const pc = $(".pet-photo-count", stage);
    track.addEventListener("scroll", () => pc && (pc.textContent = `${Math.round(track.scrollLeft / track.clientWidth) + 1}/${p.photos.length}`), { passive: true });
    $$("[data-fund]", stage).forEach((b) => (b.onclick = async () => {
      try {
        items[index] = await api.patch(`/api/animals/${p.id}`, { fundraising_open: b.dataset.fund === "1" });
        toast(items[index].fundraising_open ? "Сбор открыт" : "Сбор закрыт");
        draw();
      } catch (ex) { toast(ex.message, { error: true }); }
    }));
    $("[data-remove]", stage)?.addEventListener("click", async () => {
      try {
        await api.patch(`/api/animals/${p.id}`, { active: false });
        items.splice(index, 1);
        index = Math.min(index, items.length - 1);
        toast("Объявление снято с публикации");
        draw();
      } catch (ex) { toast(ex.message, { error: true }); }
    });
  }

  const step = (d) => {
    const n = index + d;
    if (n < 0 || n >= items.length) return;
    index = n;
    draw(d);
  };
  $("[data-prev]", nav).onclick = () => step(-1);
  $("[data-next]", nav).onclick = () => step(1);
  $("[data-help]", nav).onclick = () => items[index] && helpSheet(items[index], adult);
  $$("[data-cat]", root).forEach((b) => (b.onclick = () => {
    category = b.dataset.cat;
    try { sessionStorage.setItem("animals-cat", category); } catch { /* не страшно */ }
    $$("[data-cat]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    load();
  }));
  // свайп влево/вправо по карточке (кроме листания фото внутри)
  let x0 = null, y0 = 0, onTrack = false;
  stage.addEventListener("pointerdown", (e) => { x0 = e.clientX; y0 = e.clientY; onTrack = !!e.target.closest(".track"); });
  stage.addEventListener("pointerup", (e) => {
    if (x0 === null) return;
    const dx = e.clientX - x0, dy = e.clientY - y0;
    x0 = null;
    // короткое касание карточки (не по кнопкам) открывает подробности
    if (Math.abs(dx) < 8 && Math.abs(dy) < 8 && !e.target.closest("button, a") && items[index]) {
      openPet(items[index].id, { adult, onChange: (np) => { items[index] = np; draw(); } });
      return;
    }
    if (onTrack) return; // по фото листаются фото
    if (dx < -70) step(1);
    else if (dx > 70) step(-1);
  });
  const keys = (e) => {
    if (!document.body.contains(stage)) return document.removeEventListener("keydown", keys);
    if (e.target.closest("input, textarea")) return;
    if (e.key === "ArrowRight") step(1);
    if (e.key === "ArrowLeft") step(-1);
  };
  document.addEventListener("keydown", keys);
  load();
}

/** Подробная карточка животного: все фото, описание, подробности, отклики и «Помочь». */
export async function openPet(postId, { adult, onChange = () => {} }) {
  let p;
  try { p = await api.get(`/api/animals/${postId}`); } catch (ex) { return toast(ex.message, { error: true }); }
  const photos = p.photos.length ? p.photos : [null];
  const closed = p.category === "charity" && !p.fundraising_open;
  const posted = new Date(p.created_at).toLocaleDateString(document.documentElement.lang === "en" ? "en-GB" : "ru-RU", { day: "numeric", month: "long", year: "numeric" });
  const rows = [
    ["Кто это", p.species], ["Возраст", p.age_text], ["Город", p.city],
    ["Расстояние", p.distance_km != null ? `${Math.round(p.distance_km)} км от вас` : ""],
    ["Разместил", p.author.name, true], ["Опубликовано", posted],
    ["Telegram", p.contact_url ? p.contact_url.replace("https://", "") : "", true],
  ].filter(([, v]) => v);
  const el = h(`<section class="profile-view pet-view" role="dialog" aria-label="${esc(p.name)}">
    <div class="gallery">
      <div class="track">${photos.map((u, i) => u ? `<img src="${esc(u)}" alt="Фото ${i + 1}">` : `<div class="pet-noimg">${icons.paw}</div>`).join("")}</div>
      ${photos.length > 1 ? `<div class="dots">${photos.map((_, i) => `<i class="${i ? "" : "on"}"></i>`).join("")}</div>` : ""}
    </div>
    <button class="icon-btn close" aria-label="Закрыть">${icons.back}</button>
    <div class="profile-body">
      <div class="chips"><span class="chip static ghost">${CAT_TITLE[p.category]}</span>${p.category === "charity"
        ? `<span class="chip static ${p.fundraising_open ? "ok" : "ghost"}">${p.fundraising_open ? "Сбор открыт" : "Сбор закрыт"}</span>` : ""}</div>
      <div class="pname" translate="no" style="margin-top:12px">${esc(p.name)}</div>
      <div class="match-strip">
        ${p.category === "charity" ? `<div><b translate="no">${esc(p.fundraising_goal || "—")}</b><span>цель сбора</span></div>` : `<div><b translate="no">${esc(p.age_text || "—")}</b><span>возраст</span></div>`}
        <div><b>${p.help_count}</b><span>уже откликнулись</span></div>
        <div><b>${p.photos.length}</b><span>фото</span></div>
      </div>
      ${p.description ? `<h3>Описание</h3><p class="pet-full" translate="no">${esc(p.description)}</p>` : ""}
      <h3>Подробности</h3>
      <dl class="pet-facts">${rows.map(([k, v, raw]) => `<dt>${k}</dt><dd ${raw ? 'translate="no"' : ""}>${esc(v)}</dd>`).join("")}</dl>
      ${p.can_manage ? `<h3>Управление</h3><div class="owner-tools">
        ${p.category === "charity" ? `<div class="seg"><button class="chip" data-fund="1" aria-pressed="${p.fundraising_open}">Сбор открыт</button><button class="chip" data-fund="0" aria-pressed="${!p.fundraising_open}">Сбор закрыт</button></div>` : ""}
      </div>` : ""}
    </div>
    <div class="profile-actions">
      <button class="btn block" data-help ${closed ? "disabled" : ""}>${closed ? "Сбор закрыт, спасибо!" : `${icons.heart} Помочь`}</button>
    </div>
  </section>`);
  const close = () => { el.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => e.key === "Escape" && close();
  $(".close", el).onclick = close;
  document.addEventListener("keydown", onKey);
  $("[data-help]", el).onclick = () => helpSheet(p, adult);
  $$("[data-fund]", el).forEach((b) => (b.onclick = async () => {
    try {
      const np = await api.patch(`/api/animals/${p.id}`, { fundraising_open: b.dataset.fund === "1" });
      toast(np.fundraising_open ? "Сбор открыт" : "Сбор закрыт");
      onChange(np);
      close();
      openPet(p.id, { adult, onChange });
    } catch (ex) { toast(ex.message, { error: true }); }
  }));
  const track = $(".track", el);
  const dots = $$(".dots i", el);
  track.addEventListener("scroll", () => {
    const i = Math.round(track.scrollLeft / track.clientWidth);
    dots.forEach((d, k) => d.classList.toggle("on", k === i));
  }, { passive: true });
  track.addEventListener("click", (e) => {
    const right = e.clientX > track.getBoundingClientRect().left + track.clientWidth / 2;
    track.scrollBy({ left: right ? track.clientWidth : -track.clientWidth, behavior: "smooth" });
  });
  document.body.append(el);
  $(".close", el).focus();
}

function helpSheet(p, adult) {
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Помочь">
    <div class="bottom-sheet">
      <h2>Помочь: <span translate="no">${esc(p.name)}</span></h2>
      ${adult ? `
        <p class="muted">${p.contact_url ? "Напишите автору в Telegram или оставьте заявку: она придёт администрации COFI и волонтёрам." : "Оставьте заявку: она придёт администрации COFI, с вами свяжутся."}</p>
        ${p.contact_url ? `<a class="btn tg block" href="${esc(p.contact_url)}" target="_blank" rel="noopener">${icons.send} Написать в Telegram</a>
        <div class="divider">или</div>` : ""}
        <form class="stack">
          <label class="field"><span>Сообщение</span><textarea class="input" name="message" maxlength="1000" placeholder="Например: могу забрать на передержку на две недели"></textarea></label>
          <label class="field"><span>Как с вами связаться</span><input class="input" name="contact" maxlength="128" placeholder="@telegram или телефон"></label>
          <button class="btn block">Отправить заявку</button>
        </form>`
      : `<p class="muted">Связаться с волонтёрами можно с 18 лет. Расскажите об объявлении взрослым, они смогут помочь.</p>`}
      <button class="btn ghost block" data-close>Закрыть</button>
    </div></div>`);
  const close = () => el.remove();
  $("[data-close]", el).onclick = close;
  el.addEventListener("click", (e) => e.target === el && close());
  $("form", el)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    try {
      await api.post(`/api/animals/${p.id}/help`, { message: f.message.value, contact: f.contact.value });
      toast("Заявка отправлена. Спасибо!");
      close();
    } catch (ex) { toast(ex.message, { error: true }); }
  });
  document.body.append(el);
}
