#!/usr/bin/env bash
# Установка COFI на чистый сервер Ubuntu 22.04 / 24.04 одной командой:
#
#   sudo bash deploy/install.sh
#
# Скрипт спросит домен, почту для сертификата и (по желанию) токен Telegram-бота,
# затем поставит всё нужное: Python-окружение, автозапуск, nginx с https, TURN для звонков,
# файрвол и ежедневные резервные копии. Подробности — в deploy/DEPLOY.md.
# Повторный запуск безопасен: настройки и данные пользователей не затираются.
set -euo pipefail

# ---------- 0. Проверки и вопросы ----------
if [[ $EUID -ne 0 ]]; then echo "Запустите через sudo: sudo bash deploy/install.sh"; exit 1; fi
if ! grep -qE 'Ubuntu (22|24)\.' /etc/os-release; then
  echo "Внимание: скрипт проверен на Ubuntu 22.04 и 24.04. Продолжить? [y/N]"; read -r ok; [[ $ok == y ]] || exit 1
fi

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # папка проекта, откуда запущен скрипт
APP_DIR=/opt/cofi            # код приложения (меняется при обновлениях)
DATA_DIR=/var/lib/cofi       # база, фото, видео (не трогается при обновлениях)
BACKUP_DIR=/var/backups/cofi # резервные копии
ENV_FILE=$APP_DIR/.env       # настройки и секреты
APP_USER=cofi                # отдельный пользователь без прав администратора

ask() { local var=$1 prompt=$2 def=${3:-}; local val; read -r -p "$prompt${def:+ [$def]}: " val; printf -v "$var" '%s' "${val:-$def}"; }

existing() { [[ -f $ENV_FILE ]] && grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }

DOMAIN=${DOMAIN:-$(existing BASE_URL | sed 's#https\?://##')}
until [[ ${DOMAIN:-} =~ ^[a-z0-9.-]+\.[a-z]{2,}$ ]]; do   # пустой или с https:// — спросим ещё раз
  ask DOMAIN "Домен сайта, например cofi-app.ru (он уже должен указывать на IP этого сервера)"
  DOMAIN=$(echo "$DOMAIN" | tr 'A-Z' 'a-z' | sed 's#^https\?://##; s#/.*##; s/[[:space:]]//g')
done
ask LE_EMAIL "Почта для сертификата Let's Encrypt (придут письма, если сертификат не продлится)" "${LE_EMAIL:-$(existing ADMIN_EMAILS | cut -d, -f1)}"
ask ADMIN_EMAILS "Почта администратора COFI" "${ADMIN_EMAILS:-$(existing ADMIN_EMAILS)}"
ask BOT_TOKEN "Токен Telegram-бота от @BotFather (Enter — пропустить)" "$(existing TELEGRAM_BOT_TOKEN)"

PUBLIC_IP=$(curl -fsS4 https://api.ipify.org || hostname -I | awk '{print $1}')
DNS_IP=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1{print $1}' || true)
if [[ "$DNS_IP" != "$PUBLIC_IP" ]]; then
  echo "⚠ Домен $DOMAIN указывает на ${DNS_IP:-ничего}, а IP сервера $PUBLIC_IP."
  echo "  Добавьте у регистратора A-запись $DOMAIN → $PUBLIC_IP и подождите 5–30 минут, иначе https не выпустится."
  echo "  Продолжить всё равно? [y/N]"; read -r ok; [[ $ok == y ]] || exit 1
fi

step() { echo; echo "=== $* ==="; }

# ---------- 1. Системные пакеты ----------
step "1/9 Устанавливаю пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx certbot python3-certbot-nginx coturn ufw sqlite3 ffmpeg fail2ban \
  rsync curl ca-certificates libglib2.0-0 >/dev/null

# Подкачка: при установке OpenCV и при проверке лица нужна память. На сервере с 1–2 ГБ без неё процесс может упасть
if [[ $(free -m | awk '/Mem:/{print $2}') -lt 3000 && ! -f /swapfile ]]; then
  step "Добавляю файл подкачки 2 ГБ (мало памяти)"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# ---------- 2. Пользователь и папки ----------
step "2/9 Пользователь $APP_USER и папки"
id -u $APP_USER >/dev/null 2>&1 || useradd --system --home $APP_DIR --shell /usr/sbin/nologin $APP_USER
mkdir -p $APP_DIR $DATA_DIR $BACKUP_DIR
# Код копируем без мусора: окружение, база и кэши остаются на своих местах
rsync -a --delete --exclude venv --exclude data --exclude .env --exclude .git --exclude __pycache__ \
  --exclude tests --exclude tools --exclude '*.pyc' "$SRC"/ $APP_DIR/
[[ -d "$SRC/models" ]] && rsync -a "$SRC/models/" $DATA_DIR/models/

# ---------- 3. Python-окружение ----------
step "3/9 Python-окружение и зависимости (2–5 минут)"
[[ -d $APP_DIR/venv ]] || python3 -m venv $APP_DIR/venv
$APP_DIR/venv/bin/pip install -q --upgrade pip
$APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt

# ---------- 4. Настройки (.env) ----------
step "4/9 Настройки в $ENV_FILE"
TURN_PASS=$(existing TURN_SECRET); [[ -n $TURN_PASS ]] || TURN_PASS=$(existing TURN_CREDENTIAL); [[ -n $TURN_PASS ]] || TURN_PASS=$(openssl rand -hex 24)
if [[ ! -f $ENV_FILE ]]; then
  cat > $ENV_FILE <<EOF
# Настройки COFI. После изменений: sudo systemctl restart cofi
APP_NAME=COFI
BASE_URL=https://$DOMAIN
SECRET_KEY=$(openssl rand -hex 32)
DEV_MODE=0
COOKIE_SECURE=1
DATA_DIR=$DATA_DIR
FACE_MODELS_DIR=$DATA_DIR/models
FACE_MODE=opencv
ADMIN_EMAILS=$ADMIN_EMAILS
CAPTCHA=image
# Звонки пока выключены; включить: CALLS_ENABLED=1 и sudo systemctl restart cofi
CALLS_ENABLED=0
# Часовой пояс статистики в админке (7 — Вьетнам, 3 — Москва)
STATS_TZ_HOURS=7

# Telegram: вход, уведомления, заявки. Домен в @BotFather указывать не нужно
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
# Куда бот шлёт уведомления (id группы -100… или @username; пусто — админам в личку). Подробно: .env.example
TELEGRAM_ADMIN_CHAT_ID=
TELEGRAM_SUPPORT_CHAT_ID=
TELEGRAM_COMPLAINTS_CHAT_ID=
TELEGRAM_ADS_CHAT_ID=
TELEGRAM_REQUESTS_CHAT_ID=
TELEGRAM_PETS_CONTACT=

# Звонки: свой TURN на этом же сервере (coturn)
TURN_URLS=turn:$DOMAIN:3478,turn:$DOMAIN:3478?transport=tcp,turns:$DOMAIN:5349?transport=tcp
# Общий секрет coturn: приложение выдаёт из него временные пароли на час только вошедшим пользователям
TURN_SECRET=$TURN_PASS

# Почта для кодов. Без неё регистрация по почте не работает (вход через Telegram работает).
# Яндекс: SMTP_HOST=smtp.yandex.ru, SMTP_PORT=465, SMTP_SSL=1 и пароль приложения
SMTP_AUTH=password
SMTP_HOST=
SMTP_PORT=465
SMTP_SSL=1
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
EOF
else
  echo "Файл уже есть, оставляю как есть (обновлю только BASE_URL и токен бота, если вы их ввели)"
  sed -i "s#^BASE_URL=.*#BASE_URL=https://$DOMAIN#" $ENV_FILE
  [[ -n $BOT_TOKEN ]] && sed -i "s#^TELEGRAM_BOT_TOKEN=.*#TELEGRAM_BOT_TOKEN=$BOT_TOKEN#" $ENV_FILE
fi
chown -R $APP_USER:$APP_USER $APP_DIR $DATA_DIR
chmod 600 $ENV_FILE   # секреты читает только пользователь cofi

if [[ ! -f $DATA_DIR/models/face_recognition_sface_2021dec.onnx ]]; then
  step "Скачиваю нейросети для проверки лица"
  # запускаем из папки приложения: иначе Python не найдёт модуль app (скрипт запускают из папки с архивом)
  (cd $APP_DIR && sudo -u $APP_USER env DATA_DIR=$DATA_DIR FACE_MODELS_DIR=$DATA_DIR/models $APP_DIR/venv/bin/python -m app.cli download-models)
fi

# ---------- 5. Автозапуск (systemd) ----------
step "5/9 Служба cofi (автозапуск и перезапуск при сбое)"
cat > /etc/systemd/system/cofi.service <<EOF
[Unit]
Description=COFI — знакомства по интересам
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
# Слушаем только 127.0.0.1: снаружи приложение доступно лишь через nginx с https
Environment=HOST=127.0.0.1 PORT=8000
ExecStart=$APP_DIR/venv/bin/python run.py
Restart=always
RestartSec=3
# Защита: процесс не получает новых прав и не может менять систему, писать можно только в папку данных
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now cofi
systemctl restart cofi

# ---------- 6. nginx и https ----------
step "6/9 nginx и сертификат https"
cat > /etc/nginx/sites-available/cofi <<EOF
# Ограничение частоты на уровне nginx: второй рубеж после защиты в самом приложении
limit_req_zone \$binary_remote_addr zone=cofi_api:10m rate=20r/s;

server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 210m;   # видео с телефона до 200 МБ

    location / {
        limit_req zone=cofi_api burst=60 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        # WebSocket: сообщения в реальном времени и звонки
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        # Настоящий адрес посетителя и то, что он пришёл по https (приложение доверяет этому только от 127.0.0.1)
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;   # WebSocket не рвётся через минуту тишины
    }
}
EOF
ln -sf /etc/nginx/sites-available/cofi /etc/nginx/sites-enabled/cofi
rm -f /etc/nginx/sites-enabled/default
sed -i 's/# server_tokens off;/server_tokens off;/' /etc/nginx/nginx.conf   # не показываем версию nginx
nginx -t && systemctl reload nginx
# certbot сам допишет https в конфиг nginx, включит переадресацию с http и будет продлевать сертификат
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$LE_EMAIL" --redirect --keep-until-expiring || \
  echo "⚠ Сертификат не выпущен. Проверьте, что домен указывает на $PUBLIC_IP, и запустите: sudo certbot --nginx -d $DOMAIN"
bash "$SRC/deploy/nginx-speed.sh" || true   # сжатие и HTTP/2: быстрее открывается издалека

# ---------- 7. TURN для звонков (coturn) ----------
step "7/9 TURN-сервер для звонков через мобильный интернет"
mkdir -p /etc/coturn /etc/letsencrypt/renewal-hooks/deploy
# Сертификат для turns: (TURN по TLS на порту 5349). coturn не может читать файлы Let's Encrypt напрямую — копируем
cat > /etc/letsencrypt/renewal-hooks/deploy/coturn.sh <<EOF
#!/bin/sh
cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/coturn/cert.pem
cp /etc/letsencrypt/live/$DOMAIN/privkey.pem /etc/coturn/key.pem
chown turnserver:turnserver /etc/coturn/*.pem && chmod 600 /etc/coturn/key.pem
systemctl restart coturn
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/coturn.sh
[[ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]] && /etc/letsencrypt/renewal-hooks/deploy/coturn.sh || true
TURN_PASS=$(grep -E '^TURN_(SECRET|CREDENTIAL)=' $ENV_FILE | head -1 | cut -d= -f2-)
grep -q '^TURN_SECRET=' $ENV_FILE || echo "TURN_SECRET=$TURN_PASS" >> $ENV_FILE   # старые установки: переходим на временные пароли
cat > /etc/turnserver.conf <<EOF
# coturn для COFI: пересылает звук и видео, когда телефоны не могут соединиться напрямую
listening-port=3478
tls-listening-port=5349
external-ip=$PUBLIC_IP
realm=$DOMAIN
server-name=$DOMAIN
fingerprint
# временные пароли (TURN REST API): постоянного пароля, который можно украсть из приложения, нет
use-auth-secret
static-auth-secret=$TURN_PASS
min-port=49160
max-port=49200
cert=/etc/coturn/cert.pem
pkey=/etc/coturn/key.pem
no-cli
no-multicast-peers
# Нельзя использовать TURN, чтобы добраться до внутренних адресов сервера и локальной сети
denied-peer-ip=0.0.0.0-0.255.255.255
denied-peer-ip=10.0.0.0-10.255.255.255
denied-peer-ip=100.64.0.0-100.127.255.255
denied-peer-ip=127.0.0.0-127.255.255.255
denied-peer-ip=169.254.0.0-169.254.255.255
denied-peer-ip=172.16.0.0-172.31.255.255
denied-peer-ip=192.168.0.0-192.168.255.255
user-quota=12
total-quota=1200
EOF
sed -i 's/^#\?TURNSERVER_ENABLED=.*/TURNSERVER_ENABLED=1/' /etc/default/coturn 2>/dev/null || true
systemctl enable --now coturn
systemctl restart coturn

# ---------- 8. Файрвол ----------
step "8/9 Файрвол: открыты только нужные порты"
ufw allow OpenSSH >/dev/null          # чтобы не потерять доступ к серверу
ufw allow 80,443/tcp >/dev/null       # сайт
ufw allow 3478 >/dev/null             # TURN (udp и tcp)
ufw allow 5349/tcp >/dev/null         # TURN по TLS
ufw allow 49160:49200/udp >/dev/null  # порты, через которые идёт звук и видео
ufw --force enable >/dev/null

# SSH: fail2ban блокирует адреса, которые подбирают пароль; вход по паролю выключаем, только если уже есть SSH-ключ
cat > /etc/fail2ban/jail.d/cofi-sshd.local <<EOF
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF
systemctl enable --now fail2ban >/dev/null 2>&1 && systemctl restart fail2ban
# Вход по паролю выключаем ТОЛЬКО по явной просьбе (SSH_KEY_ONLY=1) и если вы сейчас вошли по ключу:
# в authorized_keys может лежать служебный ключ хостинга, и тогда вы потеряли бы доступ к серверу
if [[ ${SSH_KEY_ONLY:-0} == 1 && -s /root/.ssh/authorized_keys ]]; then
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/10-cofi.conf
  systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
  echo "  SSH: вход только по ключу, подбор пароля заблокирован"
else
  echo "  SSH: вход по паролю оставлен, подбор пароля блокирует fail2ban."
  echo "       Когда настроите вход по своему ключу: SSH_KEY_ONLY=1 bash deploy/install.sh"
fi

# ---------- 9. Резервные копии ----------
step "9/9 Ежедневные резервные копии"
# база — каждый день, хранится 14 дней; файлы — одно зеркало, которое дополняется (см. deploy/cofi-backup.sh)
install -m 700 "$SRC/deploy/cofi-backup.sh" /usr/local/bin/cofi-backup
printf 'DATA_DIR=%s\nBACKUP_DIR=%s\n15 4 * * * root /usr/local/bin/cofi-backup >> /var/log/cofi-backup.log 2>&1\n' "$DATA_DIR" "$BACKUP_DIR" > /etc/cron.d/cofi-backup
mkdir -p $BACKUP_DIR && chmod 700 $BACKUP_DIR

# ---------- Итог ----------
sleep 2
STATUS=$(systemctl is-active cofi || true)
echo
echo "============================================================"
echo " Готово. COFI: $STATUS"
echo " Сайт:          https://$DOMAIN"
echo " Админ-панель:  https://$DOMAIN/admin  (войдите почтой $ADMIN_EMAILS)"
echo
echo " Осталось:"
echo "  1. Почта для кодов: впишите SMTP в $ENV_FILE и выполните sudo systemctl restart cofi"
echo "  2. Telegram-группы и контакты (TELEGRAM_*_CHAT_ID, TELEGRAM_PETS_CONTACT) — там же, в $ENV_FILE"
echo "  3. Проверка: откройте сайт, зарегистрируйтесь, откройте COFI из бота (кнопка меню обновится сама)"
echo
echo " Журнал: sudo journalctl -u cofi -f      Обновление: sudo bash deploy/update.sh"
echo "============================================================"
