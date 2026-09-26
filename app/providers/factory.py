
from functools import lru_cache

from app.core.config import settings
# from app.providers.appyflow_provider import AppyFlowProvider
from app.providers.base import GSTProvider
from app.providers.gstinapi_provider import GstinApiProvider

# To add the official GST portal later: write GovtGSTProvider(GSTProvider) in a
# new file, register it below, then set GST_PROVIDER=govt in .env.
# No other file in this project needs to change.
_PROVIDERS: dict[str, type[GSTProvider]] = {
    "gstinapi": GstinApiProvider,
    # "appyflow": AppyFlowProvider,
}


@lru_cache
def get_provider() -> GSTProvider:
    provider_cls = _PROVIDERS.get(settings.gst_provider)
    if provider_cls is None:
        raise ValueError(f"Unknown GST_PROVIDER '{settings.gst_provider}'")
    return provider_cls()


