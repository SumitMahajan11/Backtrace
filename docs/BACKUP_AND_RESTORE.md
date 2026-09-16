# Layer 9: Database Backup, Retention & Disaster Recovery Runbook

## 1. Automated Daily Backup

### Schedule & Architecture
- **Frequency**: Daily at 02:00 UTC (cron: `0 2 * * *`).
- **Mechanism**: Online SQLite backup snapshot via `scripts/backup_db.py`.
- **Format**: Gzip-compressed snapshot (`reverse_db_<YYYYMMDD_HHMMSSZ>.sqlite.gz`) with SHA-256 integrity checksum (`.sha256`).
- **Retention**: Local storage / Cloud bucket retains rolling 30 daily backups.

### Triggering Manual or Scheduled Backup
```bash
python -m scripts.backup_db --dest backups
```

---

## 2. Retention Policy & Auto-Delete Worker

### 30-Day Auto-Delete Policy
In accordance with user privacy guidelines:
- Repositories and analysis results older than 30 days are automatically purged by `scripts/cleanup_worker.py`.
- If a user has opted to retain an analysis, the `keep_longer` flag is set to `True` on the `repos` table, which exempts that record and its analysis results from automatic expiration cleanup.
- Associated foreign-key rows in `ingestion_results` and `analysis_results` are deleted atomically via database cascading deletes.

### Running the Retention Worker
```bash
python -m scripts.cleanup_worker
```

---

## 3. Disaster Recovery & Restore Procedure

### Step-by-Step Restore Drill
1. Identify the target backup archive to restore:
   ```bash
   ls -la backups/
   ```
2. Run the restore utility with automated SHA-256 verification:
   ```bash
   python -m scripts.restore_db --backup-path backups/reverse_db_<TIMESTAMP>.sqlite.gz --target-db storage.db
   ```
3. The restore utility will:
   - Verify the SHA-256 checksum against `<archive>.sha256`.
   - Decompress to a staging sandbox.
   - Run `PRAGMA integrity_check;` to verify B-tree and database consistency.
   - Create a rollback safety copy of the existing target database (`storage.db.pre_restore.bak`).
   - Atomically replace the database file.
4. Verify table integrity:
   ```bash
   python -c "from app.db.session import get_db_session; from app.models.db import RepoModel; \
   with get_db_session() as s: print('Active repos:', s.query(RepoModel).count())"
   ```
