// На странице по ссылке браузер не даёт камеру и микрофон, а виджет Telegram не загружается:
// честно говорим об этом и показываем имитацию окна Telegram
import { icons } from "../../static/js/icons.js";
import { $, esc, h, toast } from "../../static/js/ui.js";

const RULES = [
  ["[data-voice]", "Голосовые записываются в приложении. На странице по ссылке браузер не даёт доступ к микрофону"],
  ["[data-circle]", "Кружочки записываются в приложении. На странице по ссылке браузер не даёт доступ к камере"],
  ["[data-call]", "Звонки работают в приложении между живыми людьми. Боты в демо не отвечают на звонки"],
];
document.addEventListener("click", (e) => {
  for (const [sel, text] of RULES) {
    if (e.target.closest?.(sel)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      toast(text, { timeout: 5000 });
      return;
    }
  }
}, true);

function telegramSheet() {
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Вход через Telegram">
    <div class="bottom-sheet tg-sheet">
      <div class="tg-head"><span class="tg-logo">${icons.send}</span><b>Telegram</b></div>
      <h2>Вход через Telegram</h2>
      <p class="muted">Сайт COFI запрашивает вход через ваш аккаунт Telegram. Он получит ваше имя, username и фото профиля.</p>
      <form class="stack">
        <label class="field"><span>Имя в Telegram</span><input class="input" name="first" value="Андрей" maxlength="64" required></label>
        <label class="field"><span>@username</span><input class="input" name="user" value="andrey_tg" maxlength="32"></label>
        <button class="btn tg block">Принять</button>
      </form>
      <p class="hint">Это имитация окна Telegram: в демо по ссылке настоящий Telegram недоступен. В приложении здесь откроется официальное окно Telegram.</p>
      <button class="btn ghost block" data-close>Отмена</button>
    </div></div>`);
  $("[data-close]", el).onclick = () => el.remove();
  $("form", el).onsubmit = (e) => {
    e.preventDefault();
    const f = e.target;
    el.remove();
    window.onTelegramAuth?.({ id: 7000000 + Math.floor(Math.random() * 999999), first_name: f.first.value.trim(),
      username: f.user.value.replace(/^@/, "").trim(), auth_date: Math.floor(Date.now() / 1000), hash: "demo" });
  };
  document.body.append(el);
}

// приложение вставляет официальный виджет в #tg-login; меняем его на нашу кнопку
new MutationObserver(() => {
  const box = document.getElementById("tg-login");
  if (!box || box.dataset.demo) return;
  box.dataset.demo = "1";
  box.replaceChildren(h(`<button class="btn tg block" type="button">${icons.send} Войти через Telegram</button>`));
  box.firstElementChild.onclick = telegramSheet;
}).observe(document.documentElement, { childList: true, subtree: true });
