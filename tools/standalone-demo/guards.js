// На странице по ссылке браузер не даёт камеру и микрофон: честно говорим об этом вместо ошибки
import { toast } from "../../static/js/ui.js";

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
