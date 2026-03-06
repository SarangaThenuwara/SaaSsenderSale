import redis
from .config import REDIS_URL
import logging

LOG = logging.getLogger(__name__)

# Initialize a connection pool for persistent connections
# We use socket_keepalive=True to help keep the connection alive through idleness
try:
    pool = redis.ConnectionPool.from_url(
        REDIS_URL, 
        max_connections=20, 
        socket_timeout=5, 
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,  # Ping server every 30s of idleness
        retry_on_timeout=True
    )
    redis_client = redis.StrictRedis(connection_pool=pool)
    LOG.info("Redis connection pool initialized with health checks")
except Exception as e:
    LOG.error(f"Failed to initialize Redis pool: {e}")
    redis_client = None

def get_redis_info():
    if not redis_client:
        return {"error": "Redis client not initialized"}
    try:
        return redis_client.info()
    except Exception as e:
        LOG.error(f"Failed to fetch Redis info: {e}")
        return {"error": str(e)}

def ensure_redis_connection():
    """Simple heartbeat to keep the connection alive in the pool."""
    if not redis_client:
        return False
    try:
        return redis_client.ping()
    except Exception:
        return False
