# 🛠️ Backtrace Utility Scripts (`scripts/`)

This directory contains standalone operational, maintenance, benchmarking, and verification tools used across the Backtrace ecosystem.

---

## 📂 Category Breakdown

### 1. 🗄️ Database Operations & Disaster Recovery
- **`backup_postgres.py`**: Creates timestamped, gzip-compressed PostgreSQL dumps with retention management.
- **`restore_postgres.py`**: Safely restores database dumps into target PostgreSQL instances.
- **`backup_db.py` / `restore_db.py`**: SQLite database backup and recovery utilities.
- **`migrate_sqlite_to_postgres.py`**: Migrates existing SQLite analysis jobs, accounts, and milestones to PostgreSQL.
- **`cron_backup.sh`**: Shell script suitable for automated cron jobs.

### 2. ⚡ Performance, Concurrency & Benchmarking
- **`benchmark_postgres_concurrency.py`**: Measures DB read/write throughput under high concurrency.
- **`load_test_concurrency_ramp.py`**: Simulates concurrent user analysis submissions and loads.
- **`verify_redis_rate_limiter_live.py`**: Tests Redis sliding-window rate limiting under spike traffic.

### 3. 🧪 Production Readiness & Verification
- **`verify_production_deployment.py`**: End-to-end sanity audit for Docker compose production deployments.
- **`verify_live_delivery.py`**: Validates pipeline delivery on real GitHub repositories.
- **`verify_piston_health_degradation.py`**: Verifies graceful fallback if Piston sandbox is temporarily offline.
- **`rotate_secrets_local.py`**: Validates secret rotation workflows.

### 4. 🐳 Sandbox & Execution Environment
- **`install_piston_runtimes.py`**: Automates pulling and installing all language packages into the local Piston engine.
- **`test_piston_executions_all_langs.py`**: Runs test execution batches across all supported languages (Python, JS, Go, Rust, Java, C++, Bash).
- **`redeploy_piston_hardened.sh`**: Deploys Piston container with custom seccomp security profiles.

### 5. 🔍 Native AST Parsers (Source Code)
- **`go_parser/`**: Source Go code (`main.go`) for extracting Go AST declarations.
- **`rust_parser/`**: Rust Cargo crate using `syn` to parse Rust crates and modules.

---

## 🏃‍♂️ How to Run a Script

Ensure your virtual environment is active and dependencies are installed:

```bash
# Example: Install Piston runtimes
python scripts/install_piston_runtimes.py

# Example: Run live rate limiter verification
python scripts/verify_redis_rate_limiter_live.py

# Example: Backup PostgreSQL database
python scripts/backup_postgres.py
```
