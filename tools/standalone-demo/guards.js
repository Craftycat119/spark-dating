// На странице по ссылке браузер не даёт камеру и микрофон, а Telegram недоступен:
// честно говорим об этом и показываем имитацию бота
import { icons } from "../../static/js/icons.js";
import { $, h, toast } from "../../static/js/ui.js";

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

// «Открыть Telegram» в окне входа: показываем имитацию бота вместо перехода на t.me
function telegramSheet(token) {
  const el = h(`<div class="overlay sheet-overlay" role="dialog" aria-label="Бот COFI в Telegram">
    <div class="bottom-sheet tg-sheet">
      <div class="tg-head"><span class="tg-logo">${icons.send}</span><b>Telegram · бот COFI</b></div>
      <h2>Войти в COFI?</h2>
      <p class="muted">Так выглядит сообщение бота. Сайт получит ваше имя и username в Telegram.</p>
      <form class="stack">
        <label class="field"><span>Имя в Telegram</span><input class="input" name="first" value="Андрей" maxlength="64" required></label>
        <label class="field"><span>@username</span><input class="input" name="user" value="andrey_tg" maxlength="32"></label>
        <button class="btn tg block">✅ Войти</button>
      </form>
      <p class="hint">Это имитация бота: в демо по ссылке настоящий Telegram недоступен. В приложении откроется чат с ботом COFI.</p>
      <button class="btn ghost block" data-close>Отмена</button>
    </div></div>`);
  $("[data-close]", el).onclick = () => el.remove();
  $("form", el).onsubmit = (e) => {
    e.preventDefault();
    const f = e.target;
    el.remove();
    window.__cofiTgConfirm?.(token, { id: 7000000 + Math.floor(Math.random() * 999999), first_name: f.first.value.trim(),
      username: f.user.value.replace(/^@/, "").trim() });
  };
  document.body.append(el);
}

document.addEventListener("click", (e) => {
  const a = e.target.closest?.('a[href^="#tg-demo:"]');
  if (!a) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  telegramSheet(a.getAttribute("href").slice("#tg-demo:".length));
}, true);
