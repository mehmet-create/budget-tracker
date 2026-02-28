import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


def check_ratelimit(key_prefix: str, limit: int = 5, period: int = 60) -> bool:
    """
    Lightweight rate limiter using Django's cache backend.
    RateLimitError is intentionally NOT caught here — callers must handle it.
    Only genuine cache backend failures are caught and logged.
    """
    key = f"ratelimit:{key_prefix}"

    try:
        current = cache.get(key)

        if current is None:
            cache.set(key, 1, timeout=period)
            return True

        if current >= limit:
            # Raise BEFORE the except — so it propagates to the caller
            raise RateLimitError("Too many attempts. Please try again later.")

        cache.incr(key)
        return True

    except RateLimitError:
        # Re-raise — never swallow this, it's intentional flow control
        raise

    except Exception as e:
        # Only real cache errors land here (Redis down, serialisation error, etc.)
        logger.error("Cache backend error in rate limiter (key=%s): %s", key, e)
        # Fail open: let the request through rather than locking everyone out
        return True