from django.core.cache import cache


class RateLimitError(Exception):
    pass


def check_ratelimit(key_prefix: str, limit: int = 5, period: int = 60) -> bool:
    """
    Lightweight rate limiter using Django's cache backend.
    Gracefully falls back if cache is unavailable.
    """
    key = f"ratelimit:{key_prefix}"

    try:
        current = cache.get(key)

        if current is None:
            cache.set(key, 1, timeout=period)
            return True

        if current >= limit:
            raise RateLimitError("Too many requests. Please try again later.")

        cache.incr(key)
        return True
    except Exception as e:
        # If cache fails, log it but don't block login
        # Rate limiting will be unavailable but the app will still work
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Cache error in rate limiting: {e}")
        return True  # Allow the request through if cache is down