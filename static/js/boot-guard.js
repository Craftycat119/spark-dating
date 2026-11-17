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
      '<p style="font-size:18px;margin:0">Загружаем COFI…</p>' +
      '<p style="color:#b39b8c;margin:8px 0 0">Интернет медленный, ещё немного</p></div>';
  }, 6000);
  setTimeout(function () {
    if (window.__cofiBooted) return;
    report("boot-timeout", "Приложение не запустилось за 25 с", "modules=" + ("noModule" in document.createElement("script")));
    var app = empty();
    if (!app) return;
    app.removeAttribute("data-boot");
    app.innerHTML = '<div style="' + STYLE + '">' +
      '<h1 style="font-size:22px">COFI не загрузился</h1>' +
      '<p style="color:#b39b8c">Проверьте интернет и попробуйте ещё раз. Если не помогает — обновите iOS или Android ' +
      'до последней версии или откройте cofilove.com в Safari или Chrome.</p>' +
      '<button id="cofi-retry" style="margin-top:12px;width:100%;padding:14px;border:0;border-radius:16px;background:#f2621f;color:#1a0f0b;font-weight:600;font-size:16px">Повторить</button></div>';
    var b = document.getElementById("cofi-retry");
    if (b) b.addEventListener("click", function () { location.reload(); });
  }, 25000);
})();
