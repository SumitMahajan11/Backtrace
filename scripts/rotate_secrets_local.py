import os
import secrets

def generate_secure_secret(length: int = 32) -> str:
    return secrets.token_hex(length)

for env_file in [".env", ".env.production"]:
    if not os.path.exists(env_file):
        continue
    with open(env_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    existing_keys = set()
    new_lines = []
    rotated_keys = []
    
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        
        k = stripped.split("=")[0].strip()
        existing_keys.add(k)
        
        if k in ("POSTGRES_PASSWORD", "REDIS_PASSWORD"):
            new_lines.append(f"{k}={generate_secure_secret(24)}\n")
            rotated_keys.append(k)
        elif k in ("JWT_SECRET", "JWT_SECRET_KEY", "SECRET_KEY"):
            new_lines.append(f"{k}={generate_secure_secret(32)}\n")
            rotated_keys.append(k)
        else:
            new_lines.append(line)
            
    # Add any missing required keys
    if "POSTGRES_USER" not in existing_keys:
        new_lines.append("POSTGRES_USER=postgres\n")
        rotated_keys.append("POSTGRES_USER")
    if "POSTGRES_PASSWORD" not in existing_keys:
        new_lines.append(f"POSTGRES_PASSWORD={generate_secure_secret(24)}\n")
        rotated_keys.append("POSTGRES_PASSWORD")
    if "POSTGRES_DB" not in existing_keys:
        new_lines.append("POSTGRES_DB=backtrace\n")
        rotated_keys.append("POSTGRES_DB")
    if "REDIS_PASSWORD" not in existing_keys:
        new_lines.append(f"REDIS_PASSWORD={generate_secure_secret(24)}\n")
        rotated_keys.append("REDIS_PASSWORD")
    if "JWT_SECRET_KEY" not in existing_keys and "JWT_SECRET" not in existing_keys:
        new_lines.append(f"JWT_SECRET_KEY={generate_secure_secret(32)}\n")
        rotated_keys.append("JWT_SECRET_KEY")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"Ensured & Rotated secrets in {env_file}: {', '.join(rotated_keys)} (values kept confidential)")
