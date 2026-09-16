"""Layer 9 30-Day Retention Cleanup Worker.

Scheduled background worker that purges expired analysis results and repository caches
older than 30 days, unless a user has set keep_longer=True.
"""

import sys
import time
from app.db.session import get_db_session, init_db
from app.storage.repository import StorageRepository


def run_retention_cleanup() -> int:
    """Executes retention cleanup pass. Returns number of purged records."""
    init_db()
    start_time = time.time()
    with get_db_session() as session:
        purged_count = StorageRepository.cleanup_expired_records(session)

    elapsed = round(time.time() - start_time, 3)
    print(f"[RetentionWorker] Purged {purged_count} expired repository record(s) in {elapsed}s.")
    return purged_count


if __name__ == "__main__":
    count = run_retention_cleanup()
    sys.exit(0)
