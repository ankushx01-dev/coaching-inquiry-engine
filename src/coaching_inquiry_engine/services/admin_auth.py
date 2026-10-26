"""Admin password verification and bounded failed-login tracking."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import OrderedDict, deque
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from os import urandom
from re import fullmatch
from threading import Lock
from time import monotonic

_SCHEME = "pbkdf2_sha256"
_MIN_ITERATIONS = 100_000
_MAX_ITERATIONS = 2_000_000
_DEFAULT_ITERATIONS = 310_000


def hash_admin_password(password: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Return a salted PBKDF2-SHA256 string suitable for configuration."""
    if not password:
        raise ValueError("password must not be empty")
    if not _MIN_ITERATIONS <= iterations <= _MAX_ITERATIONS:
        raise ValueError("PBKDF2 iterations must be between 100000 and 2000000")
    salt = urandom(16)
    derived = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        (
            _SCHEME,
            str(iterations),
            urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            urlsafe_b64encode(derived).decode("ascii").rstrip("="),
        )
    )


def is_valid_password_hash(encoded: str) -> bool:
    """Check the supported encoded hash shape and bounded cost parameters."""
    match = fullmatch(
        r"pbkdf2_sha256\$(\d{6,7})\$([A-Za-z0-9_-]{22})\$([A-Za-z0-9_-]{43})",
        encoded,
    )
    if match is None:
        return False
    iterations = int(match.group(1))
    try:
        salt = _decode(match.group(2))
        digest = _decode(match.group(3))
    except (ValueError, TypeError):
        return False
    return (
        _MIN_ITERATIONS <= iterations <= _MAX_ITERATIONS
        and len(salt) == 16
        and len(digest) == 32
    )


def verify_admin_password(password: str, encoded: str) -> bool:
    """Verify password using the configured PBKDF2-SHA256 hash."""
    if not is_valid_password_hash(encoded):
        return False
    scheme, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
    if scheme != _SCHEME:
        return False
    iterations = int(iterations_raw)
    actual = pbkdf2_hmac(
        "sha256", password.encode("utf-8"), _decode(salt_raw), iterations
    )
    return compare_digest(actual, _decode(digest_raw))


def _decode(value: str) -> bytes:
    return urlsafe_b64decode(value + "=" * (-len(value) % 4))


class AdminAuthRateLimiter:
    """Bounded per-address failed-login window for a single API process."""

    def __init__(
        self,
        *,
        limit: int = 5,
        window_seconds: float = 60,
        max_addresses: int = 4096,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_addresses = max_addresses
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def is_blocked(self, address: str) -> bool:
        now = monotonic()
        with self._lock:
            self._prune(now)
            entries = self._failures.get(address)
            return entries is not None and len(entries) >= self._limit

    def record_failure(self, address: str) -> bool:
        now = monotonic()
        with self._lock:
            self._prune(now)
            entries = self._failures.get(address)
            if entries is None:
                while len(self._failures) >= self._max_addresses:
                    self._failures.popitem(last=False)
                entries = deque()
                self._failures[address] = entries
            else:
                self._failures.move_to_end(address)
            entries.append(now)
            return len(entries) >= self._limit

    def clear(self, address: str) -> None:
        with self._lock:
            self._failures.pop(address, None)

    def _prune(self, now: float) -> None:
        expired = [
            address
            for address, entries in self._failures.items()
            if not entries or now - entries[-1] >= self._window
        ]
        for address in expired:
            self._failures.pop(address, None)
        for entries in self._failures.values():
            while entries and now - entries[0] >= self._window:
                entries.popleft()
