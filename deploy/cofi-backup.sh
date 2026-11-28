#!/bin/sh
# Ночная резервная копия COFI (ставится в /usr/local/bin/cofi-backup, запускается cron в 04:15).
#
#  * база данных — полная копия каждый день, сжатая, хранится 14 дней (она маленькая);
#  * фото, кружки, голосовые — одно зеркало media/, каждую ночь дописываются только новые файлы.
#    Раньше каждую ночь делался полный архив всех файлов и хранилось 14 таких архивов: каждый файл лежал
#    на диске 15 раз и диск заполнялся за пару недель.
#
# Копии лежат на том же диске, поэтому от поломки самого сервера защищает резервное копирование
# в панели Selectel (см. deploy/DEPLOY.md, «Резервные копии»).
set -eu
DATA_DIR=${DATA_DIR:-/var/lib/cofi}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/cofi}
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR/media"
chmod 700 "$BACKUP_DIR"
STAMP=$(date +%F)

# 1. База: согласованная копия без остановки сервера
if [ -f "$DATA_DIR/spark.db" ]; then
  sqlite3 "$DATA_DIR/spark.db" ".backup '$BACKUP_DIR/db-$STAMP.sqlite'"
  gzip -f "$BACKUP_DIR/db-$STAMP.sqlite"
fi

# 2. Файлы: зеркало. Удалённые пользователями файлы (удалённая анкета, чат) из зеркала тоже уходят
rsync -a --delete --exclude 'models/' --exclude '.uploads/' --exclude 'spark.db*' "$DATA_DIR/" "$BACKUP_DIR/media/"

# 3. Старые копии базы — прочь; полные архивы файлов от прежней версии скрипта — тоже
find "$BACKUP_DIR" -maxdepth 1 -name 'db-*.sqlite*' -mtime +$KEEP_DAYS -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'media-*.tar.gz' -delete

echo "$(date '+%F %T') резервная копия готова: база $(du -sh "$BACKUP_DIR"/db-$STAMP.sqlite.gz 2>/dev/null | cut -f1), файлы $(du -sh "$BACKUP_DIR/media" | cut -f1)"
