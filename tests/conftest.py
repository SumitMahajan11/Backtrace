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
            wsl_ip = subprocess.check_output(["wsl", "-d", "Ubuntu", "-e", "hostname", "-I"], text=True).split()[0]
            test_url = f"http://{wsl_ip}:2000"
            httpx.get(f"{test_url}/api/v2/runtimes", timeout=1.0)
            os.environ["PISTON_URL"] = test_url
            piston_health_monitor.piston_url = test_url
            piston_found = True
        except Exception:
            pass

    piston_health_monitor.check_health_sync()
    _discovered_piston_health = piston_health_monitor.is_healthy


@pytest.fixture(autouse=True)
def reset_piston_health_state():
    """Ensure singleton piston health state is clean before each test."""
    piston_health_monitor._is_healthy = _discovered_piston_health
    if os.environ.get("PISTON_URL"):
        piston_health_monitor.piston_url = os.environ["PISTON_URL"]
    yield
    piston_health_monitor._is_healthy = _discovered_piston_health
