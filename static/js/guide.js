// Инструкция: анимированный «ролик» на настоящих компонентах ленты + короткое описание функций
import { icons } from "./icons.js";
import { mountThread } from "./threads.js";
import { $, $$, esc, h } from "./ui.js";

const PEOPLE = {
  alina: { name: "Алина", age: 26, km: 1, bio: "Плёнка, бег по набережной и пуровер по субботам.", tags: ["Кофейни", "Бег", "Техно", "Фотография"] },
  igor: { name: "Игорь", age: 35, km: 6, bio: "Зал, рэп и ночной город.", tags: ["Юмор"] },
  vera: { name: "Вероника", age: 24, km: 3, bio: "Рисую обложки для релизов и смотрю аниме без стыда.", tags: ["Аниме", "Фантастика", "Кофейни"] },
  max: { name: "Максим", age: 29, km: 2, bio: "Походы выходного дня и велосипед за городом.", tags: ["Походы", "Бег", "Фотография", "Техно", "Путешествия"] },
};

const SCENES = [
  { who: "alina", title: "Свайп вниз", text: "Нравится. Бусины общих интересов стягиваются в сердце", run: "like" },
  { who: "igor", title: "Свайп вверх", text: "Дальше. Анкета уходит, общие интересы осыпаются", run: "skip" },
  { who: "vera", title: "Нажмите на фото", text: "Откроется анкета: фото, описание, все интересы", run: "open" },
  { who: "max", title: "Взаимная симпатия", text: "Если вы понравились друг другу, открывается чат", run: "match" },
  { who: "igor", title: "Кнопка «Вернуть»", text: "Пролистали случайно? Анкета вернётся, лайк можно отменить", run: "undo" },
  { who: null, title: "Лента «Питомцы»", text: "Листайте влево и вправо, а кнопка «Помочь» свяжет с волонтёрами", run: "pets" },
];

const PETS = [
  { name: "Барсик", cat: "Помощь и сборы", meta: "Кошка · 3 года · Москва", goal: "38 000 ₽", text: "Нужна операция на лапе", fund: true },
  { name: "Луна", cat: "Передержка", meta: "Собака · 2 года · Москва", goal: "", text: "Ищем передержку на две недели", fund: false },
];

function miniPets() {
  const card = (p, cls = "") => `<article class="pet ${cls}">
      <div class="pet-photos"><div class="track"><div class="pet-noimg">${icons.paw}</div></div>
        <span class="pet-cat">${p.cat}</span>${p.fund ? '<span class="fund open">Сбор открыт</span>' : ""}</div>
      <div class="pet-body"><h2 class="pet-name">${p.name}</h2><p class="muted small">${p.meta}</p>
        ${p.goal ? `<p class="pet-goal">Цель сбора: <b>${p.goal}</b></p>` : ""}<p class="pet-desc">${p.text}</p></div></article>`;
  return `
    <div class="topbar"><span class="logo">cofi<span>°</span></span></div>
    <div class="feed-tabs"><a>Знакомства</a><a class="on">${icons.paw} Питомцы</a></div>
    <div class="pet-stage">${card(PETS[0])}</div>
    <div class="pet-nav"><span class="icon-btn">${icons.back}</span><span class="btn help-btn fake-help">${icons.heart} Помочь</span><span class="icon-btn flip">${icons.back}</span></div>
    <div class="mini-sheet help"><h2>Помочь: Луна</h2><p>Напишите автору в Telegram или оставьте заявку</p>
      <span class="wide tg">Написать в Telegram</span><span class="wide">Отправить заявку</span></div>
    <div class="finger" aria-hidden="true"></div>
    <template data-next>${card(PETS[1], "from-right")}</template>`;
}

const wait = (ms, token) => new Promise((res, rej) => setTimeout(() => (token.stop ? rej(new Error("stop")) : res()), ms));

function miniPerson(p) {
  return `
    <div class="topbar"><span class="logo">cofi<span>°</span></span><span class="counter">2 из 10 рядом</span></div>
    <article class="person enter">
      <div class="ava" data-ava>${esc(p.name.charAt(0))}</div>
      <div class="pname">${esc(p.name)}<span>, ${p.age}</span></div>
      <div class="meta">${p.km} км от вас · фото подтверждено</div>
      <p class="pbio">${esc(p.bio)}</p>
    </article>
    <div class="shared-lbl">У вас общего: <b>${p.tags.length}</b></div>
    <div class="thread"></div>
    <div class="btns">
      <div class="bw"><span class="fake-btn undo">${icons.undo}</span><span>Вернуть</span></div>
      <div class="bw"><span class="fake-btn skip">${icons.x}</span><span>Дальше</span></div>
      <div class="bw"><span class="fake-btn like">${icons.heart}</span><span>Нравится</span></div>
    </div>
    <div class="mini-profile">
      <div class="mp-photo"></div>
      <div class="mp-body"><div class="pname">${esc(p.name)}<span>, ${p.age}</span></div>
        <div class="chips">${p.tags.map((t) => `<span class="chip static hot">${esc(t)}</span>`).join("")}<span class="chip static ghost">Рисование</span></div>
        <p class="note">Написать можно после взаимной симпатии</p></div>
    </div>
    <div class="mini-sheet"><h2>Взаимно</h2><p>Вы и ${esc(p.name)} понравились друг другу</p><span class="wide">Написать сообщение</span></div>
    <div class="finger" aria-hidden="true"></div>`;
}

function player(root) {
  const screen = $(".mini", root);
  const caption = $(".reel-caption", root);
  const bars = $$(".reel-bars i", root);
  const toggle = $(".reel-toggle", root);
  const token = { stop: false };
  let paused = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const fit = () => {
    const ps = $(".phone-screen", root);
    const k = ps.clientWidth / 390;
    screen.style.transform = `scale(${k})`;
    screen.style.height = `${ps.clientHeight / k}px`; // мини-экран точно по высоте телефона
  };
  new ResizeObserver(fit).observe($(".phone-screen", root));

  function finger(fromY, toY, dur, x = 195) {
    const f = $(".finger", screen);
    return f.animate([
      { opacity: 0, transform: `translate(${x - 22}px, ${fromY}px) scale(1.3)` },
      { opacity: 1, transform: `translate(${x - 22}px, ${fromY}px) scale(1)`, offset: 0.2 },
      { opacity: 1, transform: `translate(${x - 22}px, ${toY}px) scale(1)`, offset: 0.85 },
      { opacity: 0, transform: `translate(${x - 22}px, ${toY}px) scale(.9)` },
    ], { duration: dur, easing: "cubic-bezier(.4,0,.2,1)" }).finished;
  }

  async function scene(i) {
    const s = SCENES[i];
    bars.forEach((b, k) => { b.className = k < i ? "done" : k === i ? "on" : ""; });
    caption.innerHTML = `<b>${s.title}</b><span>${s.text}</span>`;
    if (s.run === "pets") {
      screen.innerHTML = miniPets();
      await wait(1000, token);
      const f = $(".finger", screen);
      await f.animate([{ opacity: 0, transform: "translate(278px,330px)" }, { opacity: 1, transform: "translate(278px,330px)", offset: 0.2 },
        { opacity: 1, transform: "translate(68px,330px)", offset: 0.85 }, { opacity: 0, transform: "translate(68px,330px)" }], { duration: 900, easing: "cubic-bezier(.4,0,.2,1)" }).finished;
      $(".pet-stage", screen).innerHTML = $("template[data-next]", screen).innerHTML;
      await wait(1200, token);
      await finger(640, 640, 700);
      $(".fake-help", screen).classList.add("press");
      $(".mini-sheet.help", screen).classList.add("show");
      await wait(2400, token);
      return;
    }
    screen.innerHTML = miniPerson(PEOPLE[s.who]);
    const thread = mountThread($(".thread", screen), PEOPLE[s.who].tags);
    await wait(900, token);
    if (s.run === "undo") {
      await finger(520, 330, 900);
      $(".fake-btn.skip", screen).classList.add("press");
      await thread.play("skip");
      $(".person", screen).style.opacity = "0.15";
      await wait(500, token);
      await finger(560, 560, 700, 100);
      $(".fake-btn.undo", screen).classList.add("press");
      screen.innerHTML = miniPerson(PEOPLE[s.who]);
      mountThread($(".thread", screen), PEOPLE[s.who].tags);
      await wait(1800, token);
      return;
    }
    if (s.run === "like" || s.run === "match") {
      await finger(330, 520, 900);
      $(".fake-btn.like", screen).classList.add("press");
      await thread.play("like");
      if (s.run === "match") {
        $(".mini-sheet", screen).classList.add("show");
        await wait(1100, token);
        await finger(700, 700, 700);
      }
    } else if (s.run === "skip") {
      await finger(520, 330, 900);
      $(".fake-btn.skip", screen).classList.add("press");
      await thread.play("skip");
    } else {
      await finger(150, 150, 700);
      $(".mini-profile", screen).classList.add("show");
      await wait(2200, token);
    }
    await wait(1300, token);
  }

  async function loop() {
    for (let i = 0; !token.stop; i = (i + 1) % SCENES.length) {
      while (paused && !token.stop) await wait(200, token).catch(() => {});
      try { await scene(i); } catch { return; }
      if (!root.isConnected) token.stop = true;
    }
  }

  const syncToggle = () => {
    toggle.innerHTML = paused ? icons.play : icons.pause;
    toggle.setAttribute("aria-label", paused ? "Смотреть ролик" : "Пауза");
  };
  toggle.onclick = () => { paused = !paused; syncToggle(); };
  syncToggle();
  fit();
  if (paused) { // при «уменьшить движение» показываем первый кадр без анимации
    screen.innerHTML = miniPerson(PEOPLE.alina);
    mountThread($(".thread", screen), PEOPLE.alina.tags);
    caption.innerHTML = `<b>${SCENES[0].title}</b><span>${SCENES[0].text}</span>`;
  }
  loop();
  return () => (token.stop = true);
}

const SECTIONS = [
  ["Ленты и жесты", [
    ["stack", "Три ленты", "«Знакомства» (с 18 лет), «Дружба» (до 18 лет) и «Питомцы» переключаются вкладками сверху. Подростки и взрослые никогда не видят друг друга."],
    ["hand-arrow-down", "Свайп по нитке вниз: нравится", "Нитка с бусинами общих интересов. Или кнопка с сердцем. Если симпатия взаимная, появится экран «Взаимно». В ленте «Дружба» кнопка называется «Дружить»."],
    ["hand-arrow-up", "Свайп по нитке вверх: дальше", "Или кнопка с крестиком. Остальную часть экрана, включая фото, можно спокойно листать пальцем: на анкету это не отвечает. На компьютере работают стрелки ↓ и ↑."],
    ["arrow-counter-clockwise", "Кнопка «Вернуть»", "Слева от «Дальше». Возвращает случайно пролистанную анкету или отменяет лайк, до 20 шагов назад."],
    ["user-circle", "Нажмите на фото", "Откроется подробная анкета: все фото, описание и интересы. Оранжевым отмечено общее."],
    ["sparkle", "Подбор по интересам", "Сначала вы видите людей с наибольшим совпадением, при равенстве ближайших. Интересы меняются в профиле."],
  ]],
  ["Питомцы", [
    ["paw-print", "Три категории", "«Помощь и сборы», «Передержка» и «Ищут дом». Листайте влево и вправо, стрелками на экране или клавишами ← →."],
    ["hand-heart", "Кнопка «Помочь»", "Открывает Telegram автора или группы и форму заявки: её получат волонтёры в Telegram. Помогать можно с 18 лет."],
    ["plus-circle", "Подробная карточка", "Нажмите на объявление: все фото, полное описание, цель сбора и сколько человек уже откликнулось. Объявления проверяет и добавляет администрация COFI."],
  ]],
  ["Общение и помощь", [
    ["chats-circle", "Чат только после пары", "Написать можно тому, с кем симпатия взаимная. В чате текст, фото и видео, голосовые, кружочки, стикеры и звонки."],
    ["headset", "Поддержка", "Профиль, затем «Поддержка»: помощь, жалобы и идеи. В любой анкете есть «Пожаловаться на анкету». Оператор отвечает прямо в чате."],
    ["megaphone", "Реклама в COFI", "Для рекламодателей: ссылка на экране входа и в профиле. Помощник отвечает про форматы, цены и аудиторию, аккаунт не нужен."],
  ]],
  ["Аккаунт", [
    ["telegram-logo", "Вход через Telegram", "Кнопка на экране входа: почта и пароль не нужны, останется указать дату рождения и подтвердить фото."],
    ["identification-card", "Дата рождения", "Указывается один раз и сама не меняется. С 12 до 17 лет открыта только «Дружба», с 18 лет знакомства. Исправить дату можно через поддержку."],
    ["shield-check", "Настоящие люди", "Главное фото каждого проверено сканером лица: человек на камере совпадает с фото."],
    ["globe", "Язык и тема", "Русский или English, тёмная или светлая тема: в профиле. На экране входа есть кнопки EN и смены темы."],
  ]],
];

export function renderGuide(main, { loggedIn, onDemo }) {
  main.innerHTML = `
    <div class="guide-top">
      <a class="icon-btn" href="#/${loggedIn ? "settings" : ""}" aria-label="Назад">${icons.back}</a>
      <span class="logo">cofi<span>°</span></span>
      <span style="width:44px"></span>
    </div>
    <h1 class="guide-title">Как пользоваться</h1>
    <section class="reel" aria-label="Ролик с примерами жестов">
      <div class="phone"><div class="phone-screen"><div class="reel-bars">${SCENES.map(() => "<i></i>").join("")}</div><div class="mini"></div></div></div>
      <div class="reel-side">
        <div class="reel-caption" aria-live="polite"></div>
        <button class="icon-btn reel-toggle"></button>
      </div>
    </section>
    ${SECTIONS.map(([heading, items]) => `
      <h2 class="guide-section">${heading}</h2>
      <div class="features">${items.map(([icon, title, text]) => `
        <div class="feature"><i class="ph ph-${icon}" aria-hidden="true"></i><div><b>${title}</b><p>${text}</p></div></div>`).join("")}
      </div>`).join("")}
    <div class="stack" style="margin-top:28px">
      ${loggedIn ? `<a class="btn block" href="#/feed">К анкетам</a>`
        : `<button class="btn block" data-demo>Открыть демо без регистрации</button><a class="btn ghost block" href="#/">Создать аккаунт</a>`}
    </div>`;
  $("[data-demo]", main)?.addEventListener("click", onDemo);
  return player(main);
}
