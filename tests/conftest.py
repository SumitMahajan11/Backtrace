import os
import subprocess
import pytest
import httpx
from app.services.piston_health import piston_health_monitor

_discovered_piston_health = False

def pytest_configure(config):
    """Discover reachable Piston URL once for test session and isolate Sentry monitoring."""
    os.environ["SENTRY_DSN"] = ""
    os.environ["ENVIRONMENT"] = "testing"
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
    piston_health_monitor._is_healthy = True
    if os.environ.get("PISTON_URL"):
        piston_health_monitor.piston_url = os.environ["PISTON_URL"]

    # Provide an in-memory fakeredis client to rate limiter if real redis is unavailable
    from app.security.rate_limiter import execution_rate_limiter
    import fakeredis
    if not execution_rate_limiter.is_redis_healthy():
        execution_rate_limiter._redis = fakeredis.FakeRedis(decode_responses=True)
    execution_rate_limiter.reset_all()

    yield
    piston_health_monitor._is_healthy = _discovered_piston_health
    execution_rate_limiter.reset_all()
