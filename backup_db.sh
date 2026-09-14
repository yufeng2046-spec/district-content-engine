#!/bin/bash
# Daily backup: local rotation + CubeMini sync + integrity check
# Run: ./backup_db.sh
set -euo pipefail
cd "$(dirname "$0")"

TIMESTAMP=$(date +%Y%m%d_%H%M)
BACKUP_DIR="backups"
LOG_FILE="$BACKUP_DIR/backup.log"
# 本地保留天数：CubeMini 已保留 7 天远程副本，本地只需留少量用于快速恢复，
# 避免每日全量备份在本地堆积占用磁盘。
RETENTION_DAYS=3

DB_FILE="district_content.db"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

mkdir -p "$BACKUP_DIR"

log "========== Backup Start =========="

# ── Integrity check ──
log "Running integrity check..."
INTEGRITY=$(python3 -c "
from db.connection import get_db
conn = get_db()
r = conn.execute('PRAGMA integrity_check').fetchone()[0]
conn.close()
print(r)
")
if [ "$INTEGRITY" != "ok" ]; then
    log "❌ Integrity check FAILED: $INTEGRITY"
    exit 1
fi
log "  ✅ Integrity: $INTEGRITY"

# ── Local backup ──
LOCAL_BACKUP="$BACKUP_DIR/district_content_${TIMESTAMP}.db"
log "Creating local backup: $LOCAL_BACKUP"
cp "$DB_FILE" "$LOCAL_BACKUP"
LOCAL_SIZE=$(ls -lh "$LOCAL_BACKUP" | awk '{print $5}')
log "  ✅ Local: $LOCAL_BACKUP ($LOCAL_SIZE)"

# ── Rotate old backups ──
DELETED=$(find "$BACKUP_DIR" -name "district_content_*.db" -mtime +$RETENTION_DAYS -delete -print | wc -l)
log "  🧹 Rotated $DELETED old backup(s) (${RETENTION_DAYS}d retention)"

# ── Clean orphan ad-hoc backups ──
# 手动 `cp district_content.db district_content.db.backup-*` 产生的临时快照，
# 命名不匹配上面的轮转规则，会永久堆积；这里按同样的保留期一并清理。
ORPHANS=$(find "$BACKUP_DIR" -name "district_content.db.backup-*" -mtime +$RETENTION_DAYS -delete -print | wc -l)
if [ "$ORPHANS" -gt 0 ]; then
    log "  🧹 Cleaned $ORPHANS orphan ad-hoc backup(s)"
fi

# ── CubeMini sync ──
log "Syncing to CubeMini..."
REMOTE_FILE="/home/frank/backups/district_content_$(date +%Y%m%d).db"

python3 -c "
import paramiko, sys, os

JUMP_HOST = '120.12.31.54'  # 2026-08-28 跳板机新 IP
JUMP_PORT = 2222
JUMP_USER = 'frank'
JUMP_PASS = '0808'
TARGET_HOST = '192.168.31.101'
TARGET_USER = 'frank'
TARGET_PASS = '0808'

LOCAL = '$DB_FILE'
REMOTE = '$REMOTE_FILE'
SIZE_MB = os.path.getsize(LOCAL) / 1024 / 1024

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(JUMP_HOST, JUMP_PORT, JUMP_USER, JUMP_PASS,
               allow_agent=False, look_for_keys=False, timeout=15)

transport = client.get_transport()
channel = transport.open_channel('direct-tcpip', (TARGET_HOST, 22), ('127.0.0.1', 0), timeout=15)

target = paramiko.SSHClient()
target.set_missing_host_key_policy(paramiko.AutoAddPolicy())
target.connect(TARGET_HOST, 22, TARGET_USER, TARGET_PASS,
               sock=channel, allow_agent=False, look_for_keys=False, timeout=15)

# Ensure backup dir exists
target.exec_command('mkdir -p /home/frank/backups', timeout=10)

# Transfer
sftp = target.open_sftp()
last_pct = [-1]
def cb(sent, total):
    pct = int(sent/total*10)
    if pct != last_pct[0]:
        print('  %d%%' % (pct*10), end='', flush=True)
        last_pct[0] = pct

sftp.put(LOCAL, REMOTE, callback=cb)
print()

# Verify
remote_stat = sftp.stat(REMOTE)
print(f'  ✅ CubeMini: {remote_stat.st_size/1024/1024:.0f}MB')

# Rotate old on CubeMini
stdin, stdout, stderr = target.exec_command(
    'find /home/frank/backups -name \"district_content_*.db\" -mtime +7 -delete -print'
)
deleted = stdout.read().decode().strip()
if deleted:
    for line in deleted.split('\n'):
        if line.strip():
            print(f'  🧹 CubeMini rotated: {line.strip()}')

sftp.close()
target.close()
channel.close()
client.close()
print('  CubeMini sync done.')
" 2>&1 | while IFS= read -r line; do log "  $line"; done

if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log "⚠️  CubeMini sync had issues, but local backup is safe."
fi

# ── Summary ──
log "========== Backup Complete =========="
echo ""
echo "Backup summary:"
echo "  Local:  $LOCAL_BACKUP ($LOCAL_SIZE)"
echo "  Remote: $REMOTE_FILE"
echo "  Log:    $LOG_FILE"
