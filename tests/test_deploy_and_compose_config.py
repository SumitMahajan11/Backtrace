from pathlib import Path
import yaml
import pytest


def test_deploy_scripts_use_env_as_single_source_of_truth():
    root = Path(__file__).resolve().parent.parent
    deploy_sh = (root / "deploy.sh").read_text(encoding="utf-8")
    deploy_ps1 = (root / "deploy.ps1").read_text(encoding="utf-8")

    # deploy.sh
    assert 'ENV_FILE=".env"' in deploy_sh, "deploy.sh must target .env as single source of truth"
    assert 'ENV_FILE=".env.production"' not in deploy_sh, "deploy.sh must not target .env.production"

    # deploy.ps1
    assert '$EnvFile = ".env"' in deploy_ps1, "deploy.ps1 must target .env as single source of truth"
    assert '$EnvFile = ".env.production"' not in deploy_ps1, "deploy.ps1 must not target .env.production"


def test_docker_compose_nginx_has_profile_opt_in():
    root = Path(__file__).resolve().parent.parent
    compose_path = root / "docker-compose.yml"
    compose_content = compose_path.read_text(encoding="utf-8")
    data = yaml.safe_load(compose_content)

    assert "services" in data, "docker-compose.yml must have services"
    assert "nginx" in data["services"], "docker-compose.yml must have nginx service"
    nginx = data["services"]["nginx"]
    assert "profiles" in nginx, "nginx service must define profiles to make it opt-in"
    assert "nginx" in nginx["profiles"], "nginx service profile must be 'nginx'"


def test_env_has_all_required_compose_and_app_keys():
    root = Path(__file__).resolve().parent.parent
    env_content = (root / ".env").read_text(encoding="utf-8")
    env_keys = set()
    for line in env_content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            env_keys.add(line.split("=", 1)[0].strip())

    required_keys = {
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "REDIS_PASSWORD",
        "REDIS_URL",
        "JWT_SECRET_KEY",
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
    }
    for key in required_keys:
        assert key in env_keys, f"Missing required key {key} in single source of truth .env"


def test_env_production_has_no_duplicate_secrets():
    root = Path(__file__).resolve().parent.parent
    prod_env_path = root / ".env.production"
    assert prod_env_path.exists(), ".env.production must exist"

    prod_content = prod_env_path.read_text(encoding="utf-8")
    active_keys = set()
    for line in prod_content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            active_keys.add(line.split("=", 1)[0].strip())

    duplicate_secrets = {
        "JWT_SECRET_KEY",
        "GITHUB_CLIENT_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "POSTGRES_PASSWORD",
        "REDIS_PASSWORD",
        "POSTHOG_API_KEY",
        "CLOUDFLARE_TUNNEL_TOKEN",
    }
    for secret in duplicate_secrets:
        assert secret not in active_keys, (
            f"Secret {secret} should be removed from .env.production to eliminate duplicate secrets"
        )
