// Лента «Животные»: листаем вперёд и назад, вместо лайков одна кнопка «Помочь»
import { api } from "./api.js";
import { icons } from "./icons.js";
import { $, $$, esc, h, toast } from "./ui.js";

const CATS = [["", "Все"], ["charity", "Помощь и сборы"], ["foster", "Передержка"], ["adoption", "Ищут дом"]];
const CAT_TITLE = { charity: "Помощь и сборы", foster: "Передержка", adoption: "Ищет хозяина" };
const SPECIES = ["Кошка", "Собака", "Другое"];

export function feedTabs(active, me) {
  const people = me.age_group === "teen" ? "Дружба 14–17" : "Знакомства 18+";
  return `<div class="feed-tabs" role="tablist">
    <a href="#/feed" role="tab" class="${active === "people" ? "on" : ""}">${people}</a>
    <a href="#/animals" role="tab" class="${active === "animals" ? "on" : ""}">${icons.paw} Животные</a></div>`;
}

export async function renderAnimals({ screen, state, go }) {
  let category = sessionStorage.getItem("animals-cat") || "";
  let items = [], index = 0;
  const adult = state.me.age_group === "adult";
  const root = screen(`
    <div class="topbar"><span class="logo">cofi<span>°</span></span>${adult ? `<a class="chip add-post" href="#/animals/new">${icons.plus} Объявление</a>` : ""}</div>
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
      stage.innerHTML = `<div class="empty"><h1>Пока пусто</h1><p class="lead">В этой категории ещё нет объявлений.${adult ? " Разместите первое: кнопка «Объявление» сверху." : ""}</p></div>`;
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
        ${p.is_mine ? `<div class="owner-tools">
          ${p.category === "charity" ? `<div class="seg"><button class="chip" data-fund="1" aria-pressed="${p.fundraising_open}">Сбор открыт</button><button class="chip" data-fund="0" aria-pressed="${!p.fundraising_open}">Сбор закрыт</button></div>` : ""}
          <button class="btn danger" data-remove>Снять с публикации</button></div>` : ""}
      </div></article>`));
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
  let x0 = null;
  stage.addEventListener("pointerdown", (e) => { if (!e.target.closest(".track")) x0 = e.clientX; });
  stage.addEventListener("pointerup", (e) => {
    if (x0 === null) return;
    const dx = e.clientX - x0;
    x0 = null;
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

function helpSheet(p, adult) {
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Помочь">
    <div class="bottom-sheet">
      <h2>Помочь: <span translate="no">${esc(p.name)}</span></h2>
      ${adult ? `
        <p class="muted">Напишите автору в Telegram или оставьте заявку: она придёт волонтёрам в Telegram.</p>
        ${p.contact_url ? `<a class="btn tg block" href="${esc(p.contact_url)}" target="_blank" rel="noopener">${icons.send} Написать в Telegram</a>` : ""}
        <div class="divider">или</div>
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
      toast("Заявка отправлена волонтёрам. Спасибо!");
      close();
    } catch (ex) { toast(ex.message, { error: true }); }
  });
  document.body.append(el);
}

export function renderAnimalForm({ screen, go }) {
  let category = "charity", species = "Кошка";
  const files = [];
  const root = screen(`
    <div class="guide-top"><a class="icon-btn" href="#/animals" aria-label="Назад">${icons.back}</a><span class="logo">cofi<span>°</span></span><span style="width:44px"></span></div>
    <h1>Новое объявление</h1>
    <form class="stack" style="margin-top:18px">
      <div class="field"><span>Категория</span><div class="choice-grid" style="grid-template-columns:repeat(3,1fr)">
        ${Object.entries(CAT_TITLE).map(([k, l]) => `<button type="button" class="chip" data-c="${k}" aria-pressed="${k === category}">${l}</button>`).join("")}</div></div>
      <label class="field"><span>Кличка или название</span><input class="input" name="name" maxlength="64" required></label>
      <div class="field"><span>Кто это</span><div class="choice-grid" style="grid-template-columns:repeat(3,1fr)">
        ${SPECIES.map((s) => `<button type="button" class="chip" data-s="${s}" aria-pressed="${s === species}">${s}</button>`).join("")}</div></div>
      <div class="row" style="align-items:flex-start">
        <label class="field" style="flex:1"><span>Возраст</span><input class="input" name="age_text" maxlength="32" placeholder="2 года"></label>
        <label class="field" style="flex:1"><span>Город</span><input class="input" name="city" maxlength="64"></label>
      </div>
      <label class="field"><span>Описание</span><textarea class="input" name="description" maxlength="3000" placeholder="Характер, здоровье, что нужно: лечение, корм, временный дом"></textarea></label>
      <label class="field" data-goal><span>Цель сбора</span><input class="input" name="fundraising_goal" maxlength="64" placeholder="Например, 40 000 ₽ на операцию"></label>
      <label class="field"><span>Telegram для связи</span><input class="input" name="contact" maxlength="128" required placeholder="@username или ссылка t.me/… на группу"></label>
      <p class="hint">Сюда придут заявки от тех, кто захочет помочь.</p>
      <div class="field"><span>Фото, до 5</span><div class="gallery-edit" data-photos></div><input type="file" accept="image/*" multiple hidden></div>
      <p class="error-text" hidden></p>
      <button class="btn block">Опубликовать</button>
    </form>`, { nav: false });
  const form = $("form", root);
  const input = $("input[type=file]", root);
  const err = $(".error-text", root);
  const drawPhotos = () => {
    $("[data-photos]", root).innerHTML = files.map((f, i) => `<div class="ph-cell"><img src="${URL.createObjectURL(f)}" alt=""><button type="button" class="del" data-del="${i}" aria-label="Убрать фото">${icons.x}</button></div>`).join("")
      + (files.length < 5 ? `<button type="button" class="ph-cell add" data-add aria-label="Добавить фото">${icons.plus}</button>` : "");
    $("[data-add]", root)?.addEventListener("click", () => input.click());
    $$("[data-del]", root).forEach((b) => (b.onclick = () => { files.splice(+b.dataset.del, 1); drawPhotos(); }));
  };
  input.onchange = () => { files.push(...[...input.files].slice(0, 5 - files.length)); input.value = ""; drawPhotos(); };
  drawPhotos();
  const syncGoal = () => ($("[data-goal]", root).hidden = category !== "charity");
  $$("[data-c]", root).forEach((b) => (b.onclick = () => { category = b.dataset.c; $$("[data-c]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b))); syncGoal(); }));
  $$("[data-s]", root).forEach((b) => (b.onclick = () => { species = b.dataset.s; $$("[data-s]", root).forEach((x) => x.setAttribute("aria-pressed", String(x === b))); }));
  syncGoal();
  form.onsubmit = async (e) => {
    e.preventDefault();
    err.hidden = true;
    const fd = new FormData();
    fd.append("category", category);
    fd.append("species", species);
    for (const k of ["name", "age_text", "city", "description", "contact"]) fd.append(k, form[k].value);
    if (category === "charity") fd.append("fundraising_goal", form.fundraising_goal.value);
    files.forEach((f) => fd.append("files", f));
    try {
      await api.post("/api/animals", fd);
      toast("Объявление опубликовано");
      go("#/animals");
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  };
}
