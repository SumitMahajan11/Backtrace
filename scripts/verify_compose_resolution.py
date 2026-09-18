import subprocess
import yaml

for cmd_name, cmd in [
    ("Default docker-compose.yml (.env)", ["docker", "compose", "config"]),
    ("Production docker-compose.prod.yml (.env.production)", ["docker", "compose", "-f", "docker-compose.prod.yml", "--env-file", ".env.production", "config"])
]:
    try:
        out = subprocess.check_output(cmd, text=True, cwd=".")
        data = yaml.safe_load(out)
        services = data.get("services", {})
        print(f"=== Config Resolution: {cmd_name} ===")
        for sname, sdef in sorted(services.items()):
            ports = sdef.get("ports", [])
            expose = sdef.get("expose", [])
            env = sdef.get("environment", {})
            has_db_pass = "POSTGRES_PASSWORD" in str(env) or "DATABASE_URL" in str(env)
            has_redis_pass = "REDIS_PASSWORD" in str(env) or "REDIS_URL" in str(env)
            print(f"  Service '{sname}':")
            print(f"    - Published Host Ports: {ports if ports else 'NONE (Zero public host exposure)'}")
            print(f"    - Internal Expose: {expose if expose else 'NONE'}")
            print(f"    - Has Non-Empty Postgres Password Configured: {has_db_pass}")
            print(f"    - Has Non-Empty Redis Password Configured: {has_redis_pass}")
    except Exception as e:
        print(f"Error checking {cmd_name}: {e}")
