
from functools import lru_cache

from app.providers.hsn_base import HSNProvider
from app.providers.offline_hsn_provider import OfflineHSNProvider


@lru_cache
def get_offline_hsn_provider() -> HSNProvider:
    """Single source of HSN data: bundled offline master (app/data/).
    To add a live/paid provider later, write NewProvider(HSNProvider) and
    depend on it in api/v1/endpoints/hsn.py -- nothing else changes.
    """
    return OfflineHSNProvider()


