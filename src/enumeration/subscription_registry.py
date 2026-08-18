from typing import Optional

from classes.enumeration.subscription_cache import SubscriptionCache

_INSTANCE: Optional[SubscriptionCache] = None


def get_subscription_cache() -> SubscriptionCache:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SubscriptionCache()
    return _INSTANCE
