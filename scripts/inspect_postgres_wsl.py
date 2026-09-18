import os
import subprocess
import psycopg2

def get_wsl_ip():
    try:
        out = subprocess.check_output(["wsl", "-d", "Ubuntu", "-e", "hostname", "-I"], text=True)
        return out.split()[0]
    except Exception:
        return "127.0.0.1"

wsl_ip = get_wsl_ip()
pg_user = os.getenv("POSTGRES_USER", "postgres")
pg_pass = os.getenv("POSTGRES_PASSWORD", "postgres")
pg_db = os.getenv("POSTGRES_DB", "backtrace")
pg_url = f"postgresql://{pg_user}:{pg_pass}@{wsl_ip}:5432/{pg_db}"
print(f"Connecting to PostgreSQL on WSL host ({wsl_ip}:5432)...")

try:
    conn = psycopg2.connect(pg_url, connect_timeout=5)
    print("SUCCESS: Connected to PostgreSQL in WSL Docker container!")
    cur = conn.cursor()
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Public Tables found: {len(tables)}")
    for t in sorted(tables):
        cur.execute(f'SELECT count(*) FROM "{t}";')
        cnt = cur.fetchone()[0]
        print(f"  - {t}: {cnt} rows")
    conn.close()
except Exception as e:
    print(f"Error connecting/querying PostgreSQL: {e}")
