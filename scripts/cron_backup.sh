#!/usr/bin/env bash
# ==============================================================================
# Automated Database Backup Cron Runner with Off-Disk Replication (Prompt 29)
# ==============================================================================
# Schedule: 0 2 * * * (Daily at 02:00 UTC)
#
# Execution Flow:
# 1. Runs scripts/backup_postgres.py to create compressed .sql.gz dump + SHA256 + .meta.json.
# 2. Prunes backups older than 7 days from primary backup volume.
# 3. Copies new archive and sidecars to off-disk backup target (mounted volume or S3/MinIO).
# 4. Logs execution timestamp, file sizes, and replication status.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PRIMARY_BACKUP_DIR="${PRIMARY_BACKUP_DIR:-backups/postgres}"
OFF_DISK_BACKUP_DIR="${OFF_DISK_BACKUP_DIR:-/tmp/off_disk_backtrace_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_FILE="${PRIMARY_BACKUP_DIR}/backup_cron.log"

mkdir -p "${PRIMARY_BACKUP_DIR}"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting automated backup run..." | tee -a "${LOG_FILE}"

# Step 1: Execute Python backup manager
cd "${PROJECT_ROOT}"
DB_URL_ARG=""
if [ -n "${DATABASE_URL:-}" ]; then
  DB_URL_ARG="--db-url ${DATABASE_URL}"
fi
BACKUP_OUTPUT=$("${PYTHON_BIN}" "scripts/backup_postgres.py" --dest "${PRIMARY_BACKUP_DIR}" --retention "${RETENTION_DAYS}" ${DB_URL_ARG})
echo "${BACKUP_OUTPUT}" >> "${LOG_FILE}"

# Extract filename
BACKUP_FILENAME=$(echo "${BACKUP_OUTPUT}" | grep -o '"backup_filename": "[^"]*' | cut -d'"' -f4 || true)

if [ -z "${BACKUP_FILENAME}" ]; then
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Failed to obtain backup filename from manager output." | tee -a "${LOG_FILE}"
  exit 1
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Primary backup created: ${BACKUP_FILENAME}" | tee -a "${LOG_FILE}"

# Step 2: Off-disk Replication (Backblaze B2 / Rclone / Mounted Volume)
B2_REMOTE="${RCLONE_REMOTE:-${B2_BUCKET:-}}"

if command -v rclone &> /dev/null && [ -n "${B2_REMOTE}" ]; then
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Syncing archive to Backblaze B2 / off-disk object storage via rclone (${B2_REMOTE})" | tee -a "${LOG_FILE}"
  rclone copy "${PRIMARY_BACKUP_DIR}/${BACKUP_FILENAME}" "${B2_REMOTE}"
  rclone copy "${PRIMARY_BACKUP_DIR}/${BACKUP_FILENAME}.sha256" "${B2_REMOTE}"
  rclone copy "${PRIMARY_BACKUP_DIR}/${BACKUP_FILENAME}.meta.json" "${B2_REMOTE}"
  
  # Prune Backblaze B2 bucket files older than retention policy
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Pruning remote B2 backups older than ${RETENTION_DAYS} days..." | tee -a "${LOG_FILE}"
  rclone delete --min-age "${RETENTION_DAYS}d" "${B2_REMOTE}" || true
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Backblaze B2 off-disk replication and pruning complete." | tee -a "${LOG_FILE}"
elif [ -d "${OFF_DISK_BACKUP_DIR}" ]; then
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Replicating archive to off-disk mount: ${OFF_DISK_BACKUP_DIR}" | tee -a "${LOG_FILE}"
  cp -p "${PRIMARY_BACKUP_DIR}/${BACKUP_FILENAME}" "${OFF_DISK_BACKUP_DIR}/"
  cp -p "${PRIMARY_BACKUP_DIR}/${BACKUP_FILENAME}.sha256" "${OFF_DISK_BACKUP_DIR}/"
  cp -p "${PRIMARY_BACKUP_DIR}/${BACKUP_FILENAME}.meta.json" "${OFF_DISK_BACKUP_DIR}/"
  
  # Prune off-disk location older than retention days
  find "${OFF_DISK_BACKUP_DIR}" -name "backtrace_backup_*" -mtime "+${RETENTION_DAYS}" -delete || true
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Off-disk replication complete." | tee -a "${LOG_FILE}"
else
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] NOTE: Neither rclone remote nor secondary mount was provided; archive retained on primary volume." | tee -a "${LOG_FILE}"
fi

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Backup and replication cycle completed successfully." | tee -a "${LOG_FILE}"
