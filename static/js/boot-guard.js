// Сторож запуска (обычный скрипт, грузится до приложения и работает даже на старых iPhone).
// 1. Ошибки JavaScript отправляет на сервер — так видно, почему COFI не открылся у конкретного телефона.
// 2. Медленный интернет: через 6 с — спокойное «Загружаем…», и только через 25 с — подсказка, что делать.
(function () {
  var sent = 0;
  function report(kind, message, extra) {
    if (sent >= 5) return; // не засыпаем сервер
    sent++;
    try {
      var body = JSON.stringify({ kind: kind, message: String(message || "").slice(0, 500), extra: String(extra || "").slice(0, 500),
        url: location.pathname + location.hash.slice(0, 40), ua: navigator.userAgent });
      var x = new XMLHttpRequest();
      x.open("POST", "/api/client-log", true);
      x.setRequestHeader("Content-Type", "application/json");
      x.send(body);
    } catch (e) { /* отчёт не обязателен */ }
  }
  window.addEventListener("error", function (e) {
    if (e && e.message) report("error", e.message, (e.filename || "").split("/").pop() + ":" + e.lineno);
    else if (e && e.target && (e.target.src || e.target.href)) report("load", "Файл не загрузился", e.target.src || e.target.href);
  }, true);
  window.addEventListener("unhandledrejection", function (e) {
    var r = e && e.reason;
    if (window.__cofiBooted) return; // после запуска ошибки сети и т. п. показывает само приложение
    report("promise", r && r.message ? r.message : r, "");
  });
  // язык экрана загрузки — как у приложения (приложение ещё не загрузилось, словарей нет)
  var L = (function () {
    var l = "";
    try { l = localStorage.getItem("lang") || ""; } catch (e) { /* приватный режим */ }
    if (!l) {
      var tg = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initDataUnsafe && window.Telegram.WebApp.initDataUnsafe.user;
      var n = ((tg && tg.language_code) || navigator.language || "ru").toLowerCase();
      l = n.indexOf("uk") === 0 ? "uk" : /^(ru|be|kk|ky|uz|tg|hy|az|ka|tk)/.test(n) ? "ru" : "en";
    }
    var M = {
      ru: ["Загружаем COFI…", "Интернет медленный, ещё немного", "COFI не загрузился",
        "Проверьте интернет и попробуйте ещё раз. Если не помогает — обновите iOS или Android до последней версии или откройте cofilove.com в Safari или Chrome.", "Повторить"],
      uk: ["Завантажуємо COFI…", "Інтернет повільний, ще трохи", "COFI не завантажився",
        "Перевірте інтернет і спробуйте ще раз. Якщо не допомагає — оновіть iOS або Android до останньої версії чи відкрийте cofilove.com у Safari або Chrome.", "Повторити"],
      en: ["Loading COFI…", "Slow connection, almost there", "COFI didn't load",
        "Check your connection and try again. If that doesn't help, update iOS or Android or open cofilove.com in Safari or Chrome.", "Retry"],
    };
    return M[l] || M.ru;
  })();
  var STYLE = 'padding:32px 20px;text-align:center;color:#f3e9df;font:16px/1.5 -apple-system,system-ui,sans-serif';
  function empty() {
    var app = document.getElementById("app");
    return !window.__cofiBooted && app && (!app.children.length || app.getAttribute("data-boot") === "wait") ? app : null;
  }
  setTimeout(function () {
    var app = empty();
    if (!app) return;
    app.setAttribute("data-boot", "wait");
    app.innerHTML = '<div style="' + STYLE + ';padding-top:38vh">' +
      '<p style="font-size:18px;margin:0">' + L[0] + '</p>' +
      '<p style="color:#b39b8c;margin:8px 0 0">' + L[1] + '</p></div>';
  }, 6000);
  setTimeout(function () {
    if (window.__cofiBooted) return;
    report("boot-timeout", "Приложение не запустилось за 25 с", "modules=" + ("noModule" in document.createElement("script")));
    var app = empty();
    if (!app) return;
    app.removeAttribute("data-boot");
    app.innerHTML = '<div style="' + STYLE + '">' +
      '<h1 style="font-size:22px">' + L[2] + '</h1>' +
      '<p style="color:#b39b8c">' + L[3] + '</p>' +
      '<button id="cofi-retry" style="margin-top:12px;width:100%;padding:14px;border:0;border-radius:16px;background:#f2621f;color:#1a0f0b;font-weight:600;font-size:16px">' + L[4] + '</button></div>';
    var b = document.getElementById("cofi-retry");
    if (b) b.addEventListener("click", function () { location.reload(); });
  }, 25000);
})();
