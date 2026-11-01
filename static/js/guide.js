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
];

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
    const k = $(".phone-screen", root).clientWidth / 390;
    screen.style.transform = `scale(${k})`;
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
    screen.innerHTML = miniPerson(PEOPLE[s.who]);
    const thread = mountThread($(".thread", screen), PEOPLE[s.who].tags);
    await wait(900, token);
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

const FEATURES = [
  ["hand-arrow-down", "Свайп вниз: нравится", "Или кнопка с сердцем. Если симпатия взаимная, появится экран «Взаимно»."],
  ["hand-arrow-up", "Свайп вверх: дальше", "Или кнопка с крестиком. На компьютере работают стрелки ↓ и ↑."],
  ["user-circle", "Нажмите на фото", "Откроется подробная анкета: все фото, описание и интересы. Оранжевым отмечено общее."],
  ["chats-circle", "Чат только после пары", "Написать можно тому, с кем симпатия взаимная. В чате текст, фото и видео, голосовые, кружочки, стикеры и звонки."],
  ["sparkle", "Подбор по интересам", "Сначала вы видите людей с наибольшим совпадением, при равенстве ближайших. Интересы меняются в профиле."],
  ["shield-check", "Настоящие люди", "Главное фото каждого проверено сканером лица: человек на камере совпадает с фото."],
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
    <div class="features">${FEATURES.map(([icon, title, text]) => `
      <div class="feature"><i class="ph ph-${icon}" aria-hidden="true"></i><div><b>${title}</b><p>${text}</p></div></div>`).join("")}
    </div>
    <div class="stack" style="margin-top:28px">
      ${loggedIn ? `<a class="btn block" href="#/feed">К анкетам</a>`
        : `<button class="btn block" data-demo>Открыть демо без регистрации</button><a class="btn ghost block" href="#/">Создать аккаунт</a>`}
    </div>`;
  $("[data-demo]", main)?.addEventListener("click", onDemo);
  return player(main);
}
