"""Distributed Token-Bucket Rate Limiting Engine (Prompt 27).

Provides:
- Distributed, atomic Token-Bucket rate limiting backed by Redis and Lua scripts.
- Eliminates race conditions across multiple worker processes and horizontally scaled containers.
- Continuous fractional token refill with burst capacity support.
- Comprehensive headers (Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset).
- Fail-open resilience strategy: Redis connection or execution failures fail open to protect user traffic.
- Circuit-Breaker & Security Alerting: Tracks fail-open bypass counts in a sliding window and triggers
  structured security alerts when bypass thresholds are breached.
- Strict isolation: Ensures heavy load from one user never degrades or blocks another user.
"""

from __future__ import annotations

import collections
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Tuple

from app.utils.logging import get_logger

logger = get_logger("rate_limiter", layer="security")

try:
    import redis
except ImportError:
    redis = None

try:
    import fakeredis
except ImportError:
    fakeredis = None

# Atomic Token Bucket Lua Script
# KEYS[1]: bucket key (e.g. ratelimit:user:usr_123)
# ARGV[1]: capacity (float, e.g. 10.0)
# ARGV[2]: refill_rate (tokens/sec, e.g. 0.16666666666666666)
# ARGV[3]: cost (float, e.g. 1.0)
# ARGV[4]: now (float epoch timestamp in seconds)
# ARGV[5]: ttl_seconds (integer TTL)
LUA_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil or last_refill == nil then
    tokens = capacity
    last_refill = now
else
    local elapsed = math.max(0.0, now - last_refill)
    tokens = math.min(capacity, tokens + elapsed * refill_rate)
    last_refill = now
end

local allowed = 0
local retry_after = 0
local remaining = 0
local reset_seconds = math.max(1, math.ceil((capacity - tokens) / refill_rate))

if tokens >= cost then
    allowed = 1
    tokens = tokens - cost
    remaining = math.max(0, math.floor(tokens))
    reset_seconds = math.max(1, math.ceil((capacity - tokens) / refill_rate))
else
    allowed = 0
    remaining = 0
    local needed = cost - tokens
    retry_after = math.max(1, math.ceil(needed / refill_rate))
    reset_seconds = math.max(1, math.ceil((capacity - tokens) / refill_rate))
end

redis.call("HMSET", key, "tokens", tostring(tokens), "last_refill", tostring(last_refill))
redis.call("EXPIRE", key, ttl)

return {allowed, remaining, reset_seconds, retry_after}
"""


@dataclass
class RateLimitResult:
    """Structured result of a rate limit check."""
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after: int


class CircuitBreakerAlerter:
    """
    Monitors rate limiter bypasses resulting from backend failures.
    Triggers structured security alerts and Sentry/PostHog notifications when bypass rates
    exceed acceptable thresholds.
    """

    def __init__(self, threshold: int = 5, window_seconds: float = 60.0) -> None:
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._bypass_timestamps: Deque[float] = collections.deque()
        self._total_bypasses: int = 0
        self._consecutive_failures = 0
        self._last_alert_time = 0.0
        self._last_failure_time = 0.0

    def record_failure(self, error: Exception, key: str) -> None:
        """Records a fail-open bypass event and triggers alert if threshold breached."""
        now = time.time()
        with self._lock:
            self._bypass_timestamps.append(now)
            self._total_bypasses += 1
            self._consecutive_failures += 1
            self._last_failure_time = now

            # Evict events outside current sliding window
            cutoff = now - self.window_seconds
            while self._bypass_timestamps and self._bypass_timestamps[0] < cutoff:
                self._bypass_timestamps.popleft()

            window_count = len(self._bypass_timestamps)

            # Check if threshold is breached and alert cooldown (10s) elapsed
            if window_count >= self.threshold and (now - self._last_alert_time >= 10.0):
                self._last_alert_time = now
                self._trigger_security_alert(window_count, error, key)

    def is_tripped(self) -> bool:
        """Returns True if consecutive failures exceed threshold and cooldown (2.0s) is active."""
        with self._lock:
            return self._consecutive_failures >= self.threshold and (time.time() - self._last_failure_time < 2.0)

    def record_success(self) -> None:
        """Resets consecutive failure counter on successful Redis operation."""
        with self._lock:
            self._consecutive_failures = 0

    def _trigger_security_alert(self, bypass_count: int, error: Exception, key: str) -> None:
        """Dispatches structured security alert to logs and monitoring providers."""
        msg = (
            f"SECURITY ALERT: Rate limiter bypass threshold exceeded! "
            f"({bypass_count} fail-open bypasses in {self.window_seconds}s). "
            f"Backend unreachable or error: {error}. Target key: '{key}'."
        )
        logger.critical(
            msg,
            extra={
                "security_alert": "rate_limiter_bypass_threshold_exceeded",
                "bypass_count": bypass_count,
                "window_seconds": self.window_seconds,
                "consecutive_failures": self._consecutive_failures,
                "last_error": str(error),
                "key": key,
            },
        )

        # Dispatch to Sentry if available
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                msg,
                level="fatal",
                tags={
                    "security_alert": "rate_limiter_bypass_threshold_exceeded",
                    "component": "rate_limiter",
                },
            )
        except Exception:
            pass

        # Dispatch to PostHog if available
        try:
            from app.monitoring.posthog import analytics
            analytics.capture(
                event_name="rate_limiter_bypass_alert",
                user_id="system",
                properties={
                    "bypass_count": bypass_count,
                    "window_seconds": self.window_seconds,
                    "consecutive_failures": self._consecutive_failures,
                },
            )
        except Exception:
            pass

    def get_stats(self) -> Dict[str, Any]:
        """Returns circuit-breaker diagnostic metrics."""
        now = time.time()
        with self._lock:
            cutoff = now - self.window_seconds
            while self._bypass_timestamps and self._bypass_timestamps[0] < cutoff:
                self._bypass_timestamps.popleft()
            return {
                "recent_bypasses_window": len(self._bypass_timestamps),
                "total_bypasses": self._total_bypasses,
                "consecutive_failures": self._consecutive_failures,
                "threshold": self.threshold,
                "window_seconds": self.window_seconds,
            }

    def reset(self) -> None:
        """Resets all metrics and timestamps (used in test teardown)."""
        with self._lock:
            self._bypass_timestamps.clear()
            self._total_bypasses = 0
            self._consecutive_failures = 0
            self._last_alert_time = 0.0
            self._last_failure_time = 0.0


class RedisTokenBucketRateLimiter:
    """
    Distributed Redis-backed Token-Bucket Rate Limiter with atomic Lua evaluation.
    
    Default Configuration:
    - capacity = 10 (Allows bursts of up to 10 immediate execution requests)
    - refill_per_minute = 10 (~0.1667 tokens/sec = 10 requests per minute)
    - fail_open = True (Ensures legitimate user traffic is not dropped if Redis is temporarily offline)
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_client: Optional[Any] = None,
        capacity: int = 10,
        refill_per_minute: int = 10,
        fail_open: bool = True,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_window_seconds: float = 60.0,
        redis_timeout: float = 0.05,
    ) -> None:
        self.capacity = capacity
        self.refill_per_minute = refill_per_minute
        self.refill_rate = float(refill_per_minute) / 60.0
        self.fail_open = fail_open
        self.redis_timeout = redis_timeout

        # Calculate key TTL (2x full replenishment time, min 120s)
        replenish_time = math.ceil(float(self.capacity) / self.refill_rate)
        self.key_ttl = max(120, int(replenish_time * 2))

        # Circuit breaker for monitoring fail-open bypasses
        self.circuit_breaker = CircuitBreakerAlerter(
            threshold=circuit_breaker_threshold,
            window_seconds=circuit_breaker_window_seconds,
        )

        # In-memory fallback bucket store for unit tests or offline environments
        self._fallback_buckets: Dict[str, Tuple[float, float]] = {}
        self._fallback_lock = threading.Lock()

        # Redis connection setup
        self._redis: Optional[Any] = redis_client
        self._script: Optional[Any] = None
        self._redis_url = redis_url

        self._init_redis(redis_url=redis_url, redis_client=redis_client)

    def _init_redis(self, redis_url: Optional[str] = None, redis_client: Optional[Any] = None) -> None:
        """Initializes Redis client and registers Lua script."""
        if redis_client is not None:
            self._redis = redis_client
        else:
            from app.core.config import get_settings
            settings = get_settings()
            target_url = redis_url or os.getenv("REDIS_URL") or settings.REDIS_URL or "redis://127.0.0.1:6379/0"
            if "://localhost:" in target_url:
                target_url = target_url.replace("://localhost:", "://127.0.0.1:")
            self._redis_url = target_url

            if redis is not None and target_url:
                try:
                    pool = redis.ConnectionPool.from_url(
                        target_url,
                        socket_connect_timeout=min(0.05, self.redis_timeout),
                        socket_timeout=min(0.05, self.redis_timeout),
                        max_connections=20,
                        decode_responses=True,
                    )
                    self._redis = redis.Redis(connection_pool=pool)
                except Exception as e:
                    logger.warning(f"Failed to create Redis connection pool for '{target_url}': {e}")
                    self._redis = None

        if self._redis is not None:
            try:
                self._script = self._redis.register_script(LUA_TOKEN_BUCKET_SCRIPT)
            except Exception:
                self._script = None

    def _check_rate_limit_fallback(self, key: str, cost: float, now: float) -> RateLimitResult:
        """In-process thread-safe fallback implementation when Redis is unavailable."""
        with self._fallback_lock:
            entry = self._fallback_buckets.get(key)
            if entry is None:
                tokens = float(self.capacity)
                last_refill = now
            else:
                stored_tokens, stored_last_refill = entry
                elapsed = max(0.0, now - stored_last_refill)
                tokens = min(float(self.capacity), stored_tokens + elapsed * self.refill_rate)
                last_refill = now

            if tokens >= cost:
                tokens -= cost
                self._fallback_buckets[key] = (tokens, last_refill)
                remaining = max(0, int(math.floor(tokens)))
                reset_seconds = max(1, int(math.ceil((self.capacity - tokens) / self.refill_rate)))
                return RateLimitResult(
                    allowed=True,
                    limit=self.capacity,
                    remaining=remaining,
                    reset_seconds=reset_seconds,
                    retry_after=0,
                )
            else:
                self._fallback_buckets[key] = (tokens, last_refill)
                needed = cost - tokens
                retry_after = max(1, int(math.ceil(needed / self.refill_rate)))
                reset_seconds = max(1, int(math.ceil((self.capacity - tokens) / self.refill_rate)))
                return RateLimitResult(
                    allowed=False,
                    limit=self.capacity,
                    remaining=0,
                    reset_seconds=reset_seconds,
                    retry_after=retry_after,
                )

    def check_rate_limit(self, key: str, cost: float = 1.0) -> RateLimitResult:
        """
        Atomically checks and consumes rate limit quota for the given key via Redis Lua script.
        Falls back to local fallback / fail-open on connection or execution errors.
        """
        redis_key = f"ratelimit:{key}"
        now = time.time()

        if self._redis is not None and not self.circuit_breaker.is_tripped():
            try:
                if self._script is None:
                    self._script = self._redis.register_script(LUA_TOKEN_BUCKET_SCRIPT)

                res = self._script(
                    keys=[redis_key],
                    args=[
                        float(self.capacity),
                        float(self.refill_rate),
                        float(cost),
                        float(now),
                        int(self.key_ttl),
                    ],
                )

                # res is [allowed (1/0), remaining, reset_seconds, retry_after]
                allowed = bool(res[0])
                remaining = int(res[1])
                reset_seconds = int(res[2])
                retry_after = int(res[3])

                self.circuit_breaker.record_success()

                return RateLimitResult(
                    allowed=allowed,
                    limit=self.capacity,
                    remaining=remaining,
                    reset_seconds=reset_seconds,
                    retry_after=retry_after,
                )

            except Exception as exc:
                logger.warning(f"Redis rate limiter failed for key '{key}': {exc}. Triggering resilience path.")
                self.circuit_breaker.record_failure(exc, key)

        # Fallback path if Redis is unconfigured or errored out
        if self.fail_open:
            # If fail_open is enabled, check local memory fallback first to still enforce limit locally
            try:
                return self._check_rate_limit_fallback(key, cost, now)
            except Exception as fallback_exc:
                logger.error(f"Fallback rate limiter failed for key '{key}': {fallback_exc}", exc_info=True)
                return RateLimitResult(
                    allowed=True,
                    limit=self.capacity,
                    remaining=1,
                    reset_seconds=0,
                    retry_after=0,
                )
        else:
            return RateLimitResult(
                allowed=False,
                limit=self.capacity,
                remaining=0,
                reset_seconds=60,
                retry_after=60,
            )

    def is_redis_healthy(self) -> bool:
        """Pings Redis to test connectivity and responsiveness."""
        if self._redis is None:
            return False
        try:
            return bool(self._redis.ping())
        except Exception:
            return False

    def reset_key(self, key: str) -> None:
        """Deletes rate limit bucket for key from Redis and fallback store."""
        redis_key = f"ratelimit:{key}"
        with self._fallback_lock:
            self._fallback_buckets.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.delete(redis_key)
            except Exception:
                pass

    def reset_all(self) -> None:
        """Clears all rate limit buckets in Redis and fallback store."""
        with self._fallback_lock:
            self._fallback_buckets.clear()
        self.circuit_breaker.reset()
        if self._redis is not None:
            try:
                keys = self._redis.keys("ratelimit:*")
                if keys:
                    self._redis.delete(*keys)
            except Exception:
                pass


# Backward compatible alias for existing imports
TokenBucketRateLimiter = RedisTokenBucketRateLimiter

# Global execution rate limiter for /run and /submit endpoints
# Configured for 10 code execution requests per minute per user, burstable to 10
execution_rate_limiter = RedisTokenBucketRateLimiter(
    capacity=10,
    refill_per_minute=10,
    fail_open=True,
)
