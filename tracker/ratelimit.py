import time
from django_redis import get_redis_connection
from asgiref.sync import sync_to_async

class RateLimitError(Exception):
    pass

@sync_to_async
def check_ratelimit(key: str, limit: int, period: int):
    """
    Async Sliding Window Rate Limiter using Redis Sorted Sets.
    """
    redis_conn = get_redis_connection("default")
    cache_key = f"rl:{key}"
    now = time.time()
    window_start = now - period

    with redis_conn.pipeline() as pipe:
        try:
            pipe.zremrangebyscore(cache_key, 0, window_start)
            pipe.zcard(cache_key)
            pipe.zadd(cache_key, {now: now})
            pipe.expire(cache_key, period + 1)
            results = pipe.execute()
            
            current_count = results[1] # Count BEFORE adding new one
            
            if current_count >= limit:
                wait_time = period 
                raise RateLimitError(f"Too many attempts. Please wait {wait_time} seconds.")
                
            return True
        except Exception as e:
            if isinstance(e, RateLimitError):
                raise e
            # Fail open if Redis is down, or log error
            print(f"Redis Error: {e}")
            raise RateLimitError("System busy. Please try again.")