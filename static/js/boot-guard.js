// Сторож запуска (обычный скрипт, грузится до приложения и работает даже на старых iPhone).
// 1. Ошибки JavaScript отправляет на сервер — так видно, почему COFI не открылся у конкретного телефона.
// 2. Если приложение не запустилось за 12 секунд — вместо пустого экрана объясняет, что делать.
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
  setTimeout(function () {
    if (window.__cofiBooted) return;
    report("boot-timeout", "Приложение не запустилось за 12 с", "modules=" + ("noModule" in document.createElement("script")));
    var app = document.getElementById("app");
    if (!app || app.children.length) return;
    app.innerHTML = '<div style="padding:32px 20px;text-align:center;color:#f3e9df;font:16px/1.5 -apple-system,system-ui,sans-serif">' +
      '<h1 style="font-size:22px">COFI не загрузился</h1>' +
      '<p style="color:#b39b8c">Проверьте интернет и попробуйте ещё раз. Если не помогает — обновите iOS или Android ' +
      'до последней версии или откройте cofilove.com в Safari или Chrome.</p>' +
      '<button id="cofi-retry" style="margin-top:12px;width:100%;padding:14px;border:0;border-radius:16px;background:#f2621f;color:#1a0f0b;font-weight:600;font-size:16px">Повторить</button></div>';
    var b = document.getElementById("cofi-retry");
    if (b) b.addEventListener("click", function () { location.reload(); });
  }, 12000);
})();
