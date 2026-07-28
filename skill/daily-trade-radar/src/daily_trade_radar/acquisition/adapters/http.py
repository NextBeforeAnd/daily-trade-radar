"""Bounded HTTP acquisition with host rate limiting, retry, and receipt caching."""

from __future__ import annotations

from collections.abc import Callable
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..cache import AcquisitionCache
from ..models import AcquisitionReceipt, AcquisitionTask, validate_receipt_for_task
from ..receipts import create_receipt


class HostRateLimiter:
    def __init__(self, minimum_interval: float = 1.0, sleep: Callable[[float], None] = time.sleep):
        if minimum_interval < 0:
            raise ValueError("minimum_interval must not be negative")
        self.minimum_interval = minimum_interval
        self.sleep = sleep
        self._last_request: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.casefold()
        with self._lock:
            now = time.monotonic()
            remaining = self.minimum_interval - (now - self._last_request.get(host, 0.0))
            if remaining > 0:
                self.sleep(remaining)
            self._last_request[host] = time.monotonic()


class HttpAdapter:
    def __init__(
        self,
        cache: AcquisitionCache | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        maximum_bytes: int = 5 * 1024 * 1024,
        opener=urlopen,
        sleep: Callable[[float], None] = time.sleep,
        rate_limiter: HostRateLimiter | None = None,
        cache_ttl_seconds: float = 24 * 60 * 60,
    ):
        if timeout <= 0 or max_attempts < 1 or backoff_seconds < 0 or maximum_bytes < 1:
            raise ValueError("HTTP limits require positive timeout/attempts/bytes and non-negative backoff")
        self.cache = cache
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.maximum_bytes = maximum_bytes
        self.opener = opener
        self.sleep = sleep
        self.rate_limiter = rate_limiter or HostRateLimiter(sleep=sleep)
        if cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must not be negative")
        self.cache_ttl_seconds = cache_ttl_seconds

    def acquire(self, task: AcquisitionTask, checked_at: str, *, refresh: bool = False) -> AcquisitionReceipt:
        if self.cache is not None and not refresh:
            cached = self.cache.load_receipt(
                task.task_id,
                reusable_only=True,
                max_age_seconds=self.cache_ttl_seconds,
                current_time=checked_at,
            )
            if cached is not None:
                validate_receipt_for_task(cached, task)
                return cached
        request = Request(task.url, headers={"User-Agent": "DailyTradeRadar/0.2 (+operational research)"})
        last_error = "unknown"
        for attempt in range(1, self.max_attempts + 1):
            self.rate_limiter.wait(task.url)
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    status_value = getattr(response, "status", None)
                    status = int(status_value if status_value is not None else response.getcode())
                    body = response.read(self.maximum_bytes + 1)
                    if len(body) > self.maximum_bytes:
                        raise ValueError("response exceeds configured byte limit")
                    charset = response.headers.get_content_charset() or "utf-8"
                    content = body.decode(charset, errors="replace")
                    final_url = response.geturl()
                return create_receipt(
                    task,
                    checked_at,
                    "candidate_found",
                    "http",
                    "HTTP source opened; content still requires research review.",
                    content=content,
                    final_url=final_url,
                    http_status=status,
                    attempts=attempt,
                    cache=self.cache,
                )
            except HTTPError as exc:
                last_error = f"http_{exc.code}"
                if exc.code == 401:
                    return create_receipt(task, checked_at, "login_required", "http", "Authentication gate observed.", http_status=exc.code, attempts=attempt, error_type=last_error, cache=self.cache)
                if exc.code == 404:
                    return create_receipt(task, checked_at, "not_applicable", "http", "Configured route was not found and must be reverified.", http_status=exc.code, attempts=attempt, error_type=last_error, cache=self.cache)
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.max_attempts:
                    return create_receipt(task, checked_at, "blocked", "http", "HTTP access failed.", http_status=exc.code, attempts=attempt, error_type=last_error, cache=self.cache)
            except (URLError, TimeoutError, OSError) as exc:
                last_error = type(exc).__name__
                if attempt == self.max_attempts:
                    return create_receipt(task, checked_at, "blocked", "http", "Connection failed after retry.", attempts=attempt, error_type=last_error, cache=self.cache)
            if self.backoff_seconds > 0:
                self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        return create_receipt(task, checked_at, "blocked", "http", "Acquisition failed.", attempts=self.max_attempts, error_type=last_error, cache=self.cache)
