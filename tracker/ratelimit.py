import time
from django.core.cache import cache

class RateLimitError(Exception):
    pass

def check_ratelimit(key_prefix, limit=5, period=60):
    """
    Synchronous Rate Limiter.
    Uses Django's standard cache backend (Redis/Locmem).
    """
    # Create a unique key for the cache
    key = f"ratelimit:{key_prefix}"
    
    # Get current usage history (list of timestamps)
    with cache.lock(f"{key}:lock", timeout=5):
        history = cache.get(key, [])
        now = time.time()
        
        # Clean old timestamps
        history = [t for t in history if t > (now - period)]
        
        if len(history) >= limit:
            raise RateLimitError("Too many requests. Please try again later.")
        
        history.append(now)
        cache.set(key, history, timeout=period)
        
    return True