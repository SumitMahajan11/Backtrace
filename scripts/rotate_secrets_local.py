import os
import secrets

def generate_secure_secret(length: int = 32) -> str:
    return secrets.token_hex(length)

for env_file in [".env", ".env.production"]:
    if not os.path.exists(env_file):
        continue
    with open(env_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new_lines = []
    rotated_keys = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("POSTGRES_PASSWORD="):
            new_lines.append(f"POSTGRES_PASSWORD={generate_secure_secret(24)}\n")
            rotated_keys.append("POSTGRES_PASSWORD")
        elif stripped.startswith("REDIS_PASSWORD="):
            new_lines.append(f"REDIS_PASSWORD={generate_secure_secret(24)}\n")
            rotated_keys.append("REDIS_PASSWORD")
        elif stripped.startswith("JWT_SECRET="):
            new_lines.append(f"JWT_SECRET={generate_secure_secret(32)}\n")
            rotated_keys.append("JWT_SECRET")
        elif stripped.startswith("SECRET_KEY="):
            new_lines.append(f"SECRET_KEY={generate_secure_secret(32)}\n")
            rotated_keys.append("SECRET_KEY")
        else:
            new_lines.append(line)
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"Rotated {len(rotated_keys)} secrets in {env_file}: {', '.join(rotated_keys)} (values kept confidential)")
