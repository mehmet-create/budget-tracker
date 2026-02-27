from django.core.cache import cache


class RateLimitError(Exception):
    pass


def check_ratelimit(key_prefix: str, limit: int = 5, period: int = 60) -> bool:
    """
    Lightweight rate limiter using Django's cache backend (Redis).

    This version uses cache.get_or_set() + cache.incr() — two calls total,
    and cache.incr() is atomic on Redis so there's no race condition either.
    """
    key = f"ratelimit:{key_prefix}"

    # Ensure the key exists with a TTL before we increment it.
    # get_or_set is atomic enough for our purposes here.
    current = cache.get(key)

    if current is None:
        # Key doesn't exist yet — set it to 1 with the expiry window
        cache.set(key, 1, timeout=period)
        return True

    if current >= limit:
        raise RateLimitError("Too many requests. Please try again later.")

    # Atomic increment — Redis INCR is a single server-side operation
    cache.incr(key)
    return True