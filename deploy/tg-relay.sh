#!/usr/bin/env bash
# Посредник для Telegram Bot API на маленьком сервере за рубежом (например, FirstVDS Амстердам).
# Нужен, если с основного сервера в России api.telegram.org недоступен.
#
# Запуск на сервере-посреднике (Ubuntu 24.04):  sudo bash tg-relay.sh
# Затем в .env основного сервера:  TELEGRAM_API_URL=https://<домен посредника>   и  sudo systemctl restart cofi
#
# Посредник принимает запросы только с IP основного сервера, весь трафик шифруется (https).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }

ask() { local var=$1 prompt=$2; local val; read -r -p "$prompt: " val; printf -v "$var" '%s' "$val"; }
ask DOMAIN "Домен посредника, например tg.cofilove.com (A-запись уже должна указывать на IP этого сервера)"
ask MAIN_IP "IP основного сервера COFI (только ему разрешён доступ)"
ask LE_EMAIL "Почта для сертификата Let's Encrypt"

apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx ufw >/dev/null

cat > /etc/nginx/sites-available/tg-relay <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    location /.well-known/acme-challenge/ { root /var/www/html; }   # для выпуска сертификата
    location / { return 404; }
}
EOF
ln -sf /etc/nginx/sites-available/tg-relay /etc/nginx/sites-enabled/tg-relay
rm -f /etc/nginx/sites-enabled/default
sed -i 's/# server_tokens off;/server_tokens off;/' /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$LE_EMAIL" --redirect --keep-until-expiring

# После выпуска сертификата: https-блок пересылает запросы в Telegram, но только с IP основного сервера
python3 - "$DOMAIN" "$MAIN_IP" <<'PY'
import re, sys
domain, ip = sys.argv[1], sys.argv[2]
path = "/etc/nginx/sites-available/tg-relay"
s = open(path).read()
relay = f"""location / {{
        allow {ip};
        deny all;
        proxy_pass https://api.telegram.org;
        proxy_ssl_server_name on;
        proxy_set_header Host api.telegram.org;
        proxy_read_timeout 60s;
        access_log off;   # в адресе запроса есть токен бота: в журнал не пишем
    }}"""
# в https-блоке (его добавил certbot) заменяем заглушку на пересылку
blocks = s.split("server {")
for i, b in enumerate(blocks):
    if "listen 443" in b:
        blocks[i] = b.replace("location / { return 404; }", relay, 1)
open(path, "w").write("server {".join(blocks))
PY
nginx -t && systemctl reload nginx

ufw allow OpenSSH >/dev/null
ufw allow 80,443/tcp >/dev/null
ufw --force enable >/dev/null

echo
echo "Готово. Проверка с ОСНОВНОГО сервера:"
echo "  curl -sS -m 10 https://$DOMAIN/ -o /dev/null -w '%{http_code}\\n'    (ожидается 302 или 200)"
echo "Затем в /opt/cofi/.env основного сервера:"
echo "  TELEGRAM_API_URL=https://$DOMAIN"
echo "  sudo systemctl restart cofi"
