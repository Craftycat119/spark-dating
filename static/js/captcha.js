// Проверка на робота в формах входа, регистрации и сброса пароля.
// Своя картинка с цифрами (CAPTCHA=image) или Cloudflare Turnstile (CAPTCHA=turnstile), настройка — в /api/config.
import { api } from "./api.js";
import { icons } from "./icons.js";
import { $, h } from "./ui.js";

let turnstileLoading = null;

function loadTurnstile() {
  if (!turnstileLoading) turnstileLoading = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    s.async = true;
    s.onload = () => resolve(window.turnstile);
    s.onerror = reject;
    document.head.append(s);
  });
  return turnstileLoading;
}

/**
 * Вставляет проверку в box. Возвращает { values(), refresh() }:
 * values() — поля для запроса (captcha_id, captcha), refresh() — новая картинка после неудачной попытки.
 */
export function mountCaptcha(box, config) {
  const mode = config?.mode || "off";
  if (mode === "off") return { values: () => ({}), refresh: () => {} };

  if (mode === "turnstile") {
    let token = "", widget = null;
    loadTurnstile().then((ts) => {
      widget = ts.render(box, { sitekey: config.site_key, language: "ru", callback: (t) => (token = t), "expired-callback": () => (token = "") });
    }).catch(() => (box.textContent = "Не загрузилась проверка Cloudflare. Обновите страницу"));
    return {
      values: () => ({ captcha: token }),
      refresh: () => { token = ""; if (widget !== null) window.turnstile?.reset(widget); },
    };
  }

  let id = "";
  box.replaceChildren(h(`<div class="captcha-box">
    <span class="captcha-label">Проверка, что вы не робот</span>
    <div class="captcha-row">
      <img alt="Цифры для проверки" width="220" height="80">
      <button type="button" class="icon-btn" data-refresh aria-label="Другая картинка">${icons.undo}</button>
    </div>
    <input class="input" name="captcha" inputmode="numeric" autocomplete="off" maxlength="5" placeholder="Цифры с картинки" required>
  </div>`));
  const img = $("img", box), input = $("input", box);
  const refresh = async () => {
    input.value = "";
    try {
      const c = await api.get("/api/auth/captcha");
      id = c.id;
      img.src = c.image;
    } catch { img.alt = "Картинка не загрузилась, нажмите обновить"; }
  };
  $("[data-refresh]", box).onclick = refresh;
  refresh();
  return { values: () => ({ captcha_id: id, captcha: input.value.trim() }), refresh };
}
