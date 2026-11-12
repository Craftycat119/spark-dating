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

# Новая версия скрипта резервных копий (старая хранила 14 полных архивов файлов и забивала диск)
command -v rsync >/dev/null || apt-get install -y -qq rsync
command -v ffmpeg >/dev/null || { echo "Ставлю ffmpeg (кружки и голосовые для iPhone)"; apt-get install -y -qq ffmpeg >/dev/null; }
install -m 700 "$SRC/deploy/cofi-backup.sh" /usr/local/bin/cofi-backup
grep -q '^DATA_DIR=' /etc/cron.d/cofi-backup 2>/dev/null || printf 'DATA_DIR=/var/lib/cofi\nBACKUP_DIR=/var/backups/cofi\n15 4 * * * root /usr/local/bin/cofi-backup >> /var/log/cofi-backup.log 2>&1\n' > /etc/cron.d/cofi-backup

echo "Резервная копия перед обновлением"
/usr/local/bin/cofi-backup || true

echo "Копирую новый код"
rsync -a --delete --exclude venv --exclude data --exclude .env --exclude .git --exclude __pycache__ \
  --exclude tests --exclude tools --exclude '*.pyc' "$SRC"/ $APP_DIR/
echo "Зависимости"
$APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt
chown -R cofi:cofi $APP_DIR

echo "nginx: сжатие и HTTP/2"
bash "$SRC/deploy/nginx-speed.sh" || true

echo "Перезапуск"
# старые кружки и голосовые в webm → mp4/m4a, чтобы играли на iPhone (уже перекодированные пропускаются)
(cd $APP_DIR && sudo -u cofi venv/bin/python -m app.cli convert-media) || true
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
