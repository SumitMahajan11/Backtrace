import glob
import os
import sqlite3

for db_file in sorted(glob.glob("*.db")):
    size = os.path.getsize(db_file)
    print(f"=== {db_file} ({size:,} bytes) ===")
    try:
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = [r[0] for r in c.fetchall()]
        for t in sorted(tables):
            c.execute(f'SELECT count(*) FROM "{t}"')
            cnt = c.fetchone()[0]
            print(f"  - {t}: {cnt} rows")
        conn.close()
    except Exception as e:
        print(f"  Error reading {db_file}: {e}")
