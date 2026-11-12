#!/usr/bin/env bash
# Ускорение отдачи сайта через nginx: сжатие текста (gzip) и HTTP/2 (все файлы по одному соединению разом).
# Безопасно запускать повторно. Если nginx не принимает настройку — всё возвращается как было.
set -uo pipefail
SITE=/etc/nginx/sites-available/cofi
CONF=/etc/nginx/conf.d/cofi-speed.conf
nginx -t >/dev/null 2>&1 || { echo "⚠ nginx уже с ошибкой в настройках, ускорение пропущено"; exit 0; }

# 1. Сжатие. «gzip on» уже включён в стандартном nginx.conf Ubuntu, здесь — что и как сжимать
cat > $CONF <<'NGX'
gzip_vary on;
gzip_proxied any;
gzip_comp_level 5;
gzip_min_length 1024;
gzip_types text/css text/plain application/javascript text/javascript application/json image/svg+xml application/manifest+json;
NGX
if ! nginx -t >/dev/null 2>&1; then
  rm -f $CONF
  echo "⚠ Сжатие не включено: nginx не принял настройку (возможно, она уже задана в nginx.conf)"
fi

# 2. HTTP/2 на https (строки listen 443 дописал certbot)
if [[ -f $SITE ]] && grep -q 'listen .*443 ssl' $SITE && ! grep -q 'http2' $SITE; then
  cp $SITE /tmp/cofi-nginx.bak
  sed -i -E 's/(listen (\[::\]:)?443 ssl)( |;)/\1 http2\3/' $SITE
  if ! nginx -t >/dev/null 2>&1; then
    cp /tmp/cofi-nginx.bak $SITE
    echo "⚠ HTTP/2 не включён: nginx не принял настройку"
  fi
fi

# 3. Видео с телефона до 200 МБ (раньше nginx пропускал только 64 МБ)
if [[ -f $SITE ]] && grep -q 'client_max_body_size 64m' $SITE; then
  sed -i 's/client_max_body_size 64m;.*/client_max_body_size 210m;   # видео с телефона до 200 МБ/' $SITE
  nginx -t >/dev/null 2>&1 || sed -i 's/client_max_body_size 210m;.*/client_max_body_size 64m;/' $SITE
fi

nginx -t >/dev/null 2>&1 && systemctl reload nginx && echo "✓ nginx: сжатие и HTTP/2 включены"
