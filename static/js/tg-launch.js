// Страница-ярлык /tg: открыли с экрана «Домой» — сразу уходим в Telegram, где откроется COFI (главное мини-приложение бота).
// Открыли в браузере — показываем, как добавить такой ярлык.
(function () {
  var bot = document.body.getAttribute("data-bot") || "";
  var tg = "tg://resolve?domain=" + encodeURIComponent(bot) + "&startapp=home";
  var web = "https://t.me/" + encodeURIComponent(bot) + "?startapp=home";
  var btn = document.getElementById("open");
  btn.href = tg;
  btn.addEventListener("click", function () {
    // Telegram не установлен — через секунду откроем обычную ссылку t.me
    setTimeout(function () { if (!document.hidden) location.href = web; }, 1200);
  });
  var fromHome = window.navigator.standalone === true || window.matchMedia("(display-mode: standalone)").matches;
  if (fromHome && bot) {
    document.getElementById("launch").hidden = false;
    location.href = tg;
  } else {
    document.getElementById("setup").hidden = false;
  }
})();
