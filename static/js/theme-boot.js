// Тема до первой отрисовки, чтобы не мигало. Отдельным файлом, а не внутри HTML: так строгая CSP запрещает любые встроенные скрипты
try{var t=localStorage.getItem("theme")||"dark";if(t==="system")t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark";document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="dark"}
