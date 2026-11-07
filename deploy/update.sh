#!/usr/bin/env bash
# Обновление COFI на сервере: новый код → зависимости → перезапуск → проверка.
# База, фото и настройки (.env) не трогаются.
#
#   cd ~/spark-dating && git pull && sudo bash deploy/update.sh
#   (или распакуйте новый архив поверх папки проекта и запустите тот же скрипт)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите через sudo"; exit 1; }
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/cofi

echo "Резервная копия перед обновлением"
/usr/local/bin/cofi-backup || true

echo "Копирую новый код"
rsync -a --delete --exclude venv --exclude data --exclude .env --exclude .git --exclude __pycache__ \
  --exclude tests --exclude tools --exclude '*.pyc' "$SRC"/ $APP_DIR/
echo "Зависимости"
$APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt
chown -R cofi:cofi $APP_DIR

echo "Перезапуск"
systemctl restart cofi
for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/api/config >/dev/null 2>&1; then
    echo "✓ COFI работает"; exit 0
  fi
  sleep 1
done
echo "✗ COFI не ответил. Последние строки журнала:"
journalctl -u cofi -n 40 --no-pager
exit 1
