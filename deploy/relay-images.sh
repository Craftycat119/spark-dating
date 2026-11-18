#!/usr/bin/env bash
# Запуск на сервере-посреднике (tg.cofilove.com), уже настроенном через tg-relay.sh:
#   sudo bash relay-images.sh
# Добавляет открытый адрес /pub/broadcast/ — картинки рассылок, которые Telegram скачивает для превью.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }
CONF=/etc/nginx/sites-available/tg-relay
grep -q "location /pub/broadcast/" "$CONF" && { echo "Уже настроено"; exit 0; }
cp "$CONF" "$CONF.bak"
python3 - "$CONF" <<'PY'
import sys
path = sys.argv[1]
s = open(path).read()
block = """location /pub/broadcast/ {
        proxy_pass https://cofilove.com;
        proxy_ssl_server_name on;
        proxy_set_header Host cofilove.com;
        proxy_read_timeout 30s;
    }
    """
parts = s.split("server {")
for i, b in enumerate(parts):
    if "listen 443" in b and "location / {" in b:
        parts[i] = b.replace("location / {", block + "location / {", 1)
        break
else:
    sys.exit("Не нашёл https-блок в " + path)
open(path, "w").write("server {".join(parts))
PY
if nginx -t; then systemctl reload nginx; echo "Готово"; else cp "$CONF.bak" "$CONF"; echo "Ошибка — вернул как было"; exit 1; fi
