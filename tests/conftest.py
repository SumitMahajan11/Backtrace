import os
import subprocess
import pytest
import httpx

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SANDBOX_ENABLED", "true")
os.environ.setdefault("RETENTION_CLEANUP_ENABLED", "false")

from app.core.config import get_settings
get_settings.cache_clear()

from app.services.piston_health import piston_health_monitor

_discovered_piston_health = False

def pytest_configure(config):
    """Discover reachable Piston URL once for test session and isolate Sentry monitoring."""
    os.environ["SENTRY_DSN"] = ""
    os.environ["DEBUG"] = "false"
    os.environ["ENVIRONMENT"] = "test"
    os.environ["SANDBOX_ENABLED"] = "true"
    os.environ["RETENTION_CLEANUP_ENABLED"] = "false"
    get_settings.cache_clear()
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
    global _discovered_piston_health
    piston_found = False
    try:
        httpx.get("http://127.0.0.1:2000/api/v2/runtimes", timeout=0.5)
        os.environ["PISTON_URL"] = "http://127.0.0.1:2000"
        piston_found = True
    except Exception:
        pass

    if not piston_found:
        try:
            wsl_ips = subprocess.check_output(["wsl", "hostname", "-I"], text=True).split()
            for ip in wsl_ips:
                test_url = f"http://{ip}:2000"
                try:
                    httpx.get(f"{test_url}/api/v2/runtimes", timeout=0.5)
                    os.environ["PISTON_URL"] = test_url
                    piston_health_monitor.piston_url = test_url
                    piston_found = True
                    break
                except Exception:
                    continue
        except Exception:
            pass

    piston_health_monitor.check_health_sync()
    _discovered_piston_health = piston_health_monitor.is_healthy


@pytest.fixture(autouse=True)
def reset_piston_health_state():
    """Ensure singleton piston health state and rate limiters are clean before each test."""
    from app.db.session import Base, engine
    import app.models.db  # noqa: F401
    Base.metadata.create_all(bind=engine)
    piston_health_monitor._is_healthy = True
    if os.environ.get("PISTON_URL"):
        piston_health_monitor.piston_url = os.environ["PISTON_URL"]

    # Provide an in-memory fakeredis client to rate limiters
    import fakeredis
    fake_r = fakeredis.FakeRedis(decode_responses=True)
    from app.security.rate_limiter import execution_rate_limiter
    execution_rate_limiter._redis = fake_r
    execution_rate_limiter.reset_all()

    yield
    piston_health_monitor._is_healthy = _discovered_piston_health
    execution_rate_limiter.reset_all()


@pytest.fixture
def billing_on(monkeypatch):
    """Enable Stripe billing and set mock credentials for billing test runs."""
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("PRO_PRICE_DISPLAY", "$19/mo")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mock_secret_key_12345")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_mock_webhook_secret_12345")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def rewards_on(monkeypatch):
    """Enable rewards subsystem for rewards test runs."""
    monkeypatch.setenv("REWARDS_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

