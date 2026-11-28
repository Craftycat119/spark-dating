// Выполняется раньше приложения: навигация в памяти и тема по умолчанию как у зрителя
import { useMemoryRouting } from "../../static/js/router.js";

useMemoryRouting("#/");
try {
  if (!localStorage.getItem("theme")) {
    const host = document.documentElement.dataset.theme;
    localStorage.setItem("theme", host === "light" || host === "dark" ? host : "system");
  }
} catch { /* без хранилища будет тёмная */ }
