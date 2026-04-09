import httpx
import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Cache for exchange rate
_cache = {
    "rate": 0.92,  # Fallback rate
    "last_updated": 0
}
CACHE_DURATION = 24 * 3600  # 24 hours

def get_usd_to_eur_rate() -> float:
    """
    Fetches the latest USD to EUR exchange rate from frankfurter.dev API.
    Uses 24h caching to avoid rate limiting.
    """
    now = time.time()
    if now - _cache["last_updated"] < CACHE_DURATION:
        return _cache["rate"]

    try:
        # Using a timeout to prevent hanging
        response = httpx.get("https://api.frankfurter.dev/v1/latest?from=USD&to=EUR", timeout=5.0)
        response.raise_for_status()
        data = response.json()
        rate = data.get("rates", {}).get("EUR")
        if rate:
            _cache["rate"] = float(rate)
            _cache["last_updated"] = now
            logger.info(f"Updated USD->EUR exchange rate: {rate}")
            return _cache["rate"]
    except Exception as e:
        logger.error(f"Failed to fetch exchange rate: {e}. Using fallback: {_cache['rate']}")
    
    return _cache["rate"]
