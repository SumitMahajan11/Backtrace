"""Piston Sandbox Health Monitoring and Graceful Degradation Engine (Prompt 21).

Provides:
- Non-blocking background health check task polling Piston GET /api/v2/runtimes every 30 seconds.
- In-memory health state tracking (status, last_checked_at, latency_ms, runtimes_count, error).
- Fast-fail protection preventing deadlocks/timeouts when Piston is unavailable.
- Safe lifecycle integration with FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from app.utils.logging import get_logger

logger = get_logger("piston_health", layer="monitoring")


class PistonHealthMonitor:
    """Singleton monitor tracking Piston execution sandbox operational readiness."""

    def __init__(
        self,
        piston_url: Optional[str] = None,
        check_interval_seconds: float = 30.0,
        request_timeout_seconds: float = 3.0,
    ) -> None:
        self.piston_url = (piston_url or os.getenv("PISTON_URL", "http://127.0.0.1:2000")).rstrip("/")
        self.check_interval_seconds = check_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        
        # In-memory health state (optimistic initial state before first polling tick)
        self._is_healthy: bool = True
        self._last_checked_at: Optional[str] = None
        self._latency_ms: float = 0.0
        self._runtimes_count: int = 0
        self._error_message: Optional[str] = None
        
        # Async background task handle
        self._bg_task: Optional[asyncio.Task] = None
        self._is_running: bool = False

    @property
    def is_healthy(self) -> bool:
        """Returns immediate boolean readiness flag for fast-fail execution gates."""
        return self._is_healthy

    def check_health_sync(self) -> Dict[str, Any]:
        """Synchronously probes Piston /api/v2/runtimes endpoint and updates state."""
        url = f"{self.piston_url}/api/v2/runtimes"
        start_time = time.perf_counter()
        now_iso = datetime.now(timezone.utc).isoformat()
        
        try:
            with httpx.Client(timeout=self.request_timeout_seconds) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
                
            latency = round((time.perf_counter() - start_time) * 1000.0, 2)
            runtimes_count = len(data) if isinstance(data, list) else 0
            
            self._is_healthy = True
            self._last_checked_at = now_iso
            self._latency_ms = latency
            self._runtimes_count = runtimes_count
            self._error_message = None
            
            return self.get_status()
        except Exception as exc:
            # Try WSL IP fallback if on Windows localhost
            if "127.0.0.1" in url or "localhost" in url:
                try:
                    import subprocess
                    wsl_ip = subprocess.check_output(["wsl", "-d", "Ubuntu", "-e", "hostname", "-I"], text=True, timeout=1.0).split()[0]
                    fallback_url = f"http://{wsl_ip}:2000/api/v2/runtimes"
                    with httpx.Client(timeout=self.request_timeout_seconds) as client:
                        resp = client.get(fallback_url)
                        resp.raise_for_status()
                        data = resp.json()
                    self.piston_url = f"http://{wsl_ip}:2000"
                    self._is_healthy = True
                    self._last_checked_at = now_iso
                    self._latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                    self._runtimes_count = len(data) if isinstance(data, list) else 0
                    self._error_message = None
                    return self.get_status()
                except Exception:
                    pass

            latency = round((time.perf_counter() - start_time) * 1000.0, 2)
            self._is_healthy = False
            self._last_checked_at = now_iso
            self._latency_ms = latency
            self._runtimes_count = 0
            self._error_message = f"Piston unreachable at {url}: {exc}"
            
            return self.get_status()

    async def check_health_async(self) -> Dict[str, Any]:
        """Asynchronously probes Piston /api/v2/runtimes endpoint and updates state."""
        url = f"{self.piston_url}/api/v2/runtimes"
        start_time = time.perf_counter()
        now_iso = datetime.now(timezone.utc).isoformat()
        
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout_seconds) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                
            latency = round((time.perf_counter() - start_time) * 1000.0, 2)
            runtimes_count = len(data) if isinstance(data, list) else 0
            
            self._is_healthy = True
            self._last_checked_at = now_iso
            self._latency_ms = latency
            self._runtimes_count = runtimes_count
            self._error_message = None
            
            return self.get_status()
        except Exception as exc:
            latency = round((time.perf_counter() - start_time) * 1000.0, 2)
            self._is_healthy = False
            self._last_checked_at = now_iso
            self._latency_ms = latency
            self._runtimes_count = 0
            self._error_message = f"Piston unreachable at {url}: {exc}"
            
            return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        """Returns structured health report dictionary."""
        status_str = "healthy" if self._is_healthy else "unhealthy"
        payload: Dict[str, Any] = {
            "status": status_str,
            "is_available": self._is_healthy,
            "last_checked_at": self._last_checked_at or datetime.now(timezone.utc).isoformat(),
            "latency_ms": self._latency_ms,
            "runtimes_count": self._runtimes_count,
        }
        if self._error_message:
            payload["error"] = self._error_message
        return payload

    async def _health_check_loop(self) -> None:
        """Internal background loop running every check_interval_seconds."""
        logger.info(f"Piston health check loop started (interval={self.check_interval_seconds}s, url={self.piston_url})")
        while self._is_running:
            try:
                await self.check_health_async()
            except Exception as e:
                logger.error(f"Error in Piston health check loop: {e}")
            try:
                await asyncio.sleep(self.check_interval_seconds)
            except asyncio.CancelledError:
                break

    def start_background_task(self) -> None:
        """Spawns background polling task in current asyncio event loop."""
        if self._is_running:
            return
        self._is_running = True
        # Perform immediate synchronous/initial check so state is primed
        try:
            self.check_health_sync()
        except Exception:
            pass
        self._bg_task = asyncio.create_task(self._health_check_loop())

    def stop_background_task(self) -> None:
        """Cancels background polling task on application shutdown."""
        self._is_running = False
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()


# Global singleton instance for application use
piston_health_monitor = PistonHealthMonitor()
