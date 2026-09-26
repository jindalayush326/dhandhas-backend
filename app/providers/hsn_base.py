
from abc import ABC, abstractmethod

from app.schemas.hsn import HSNDetails


class HSNProvider(ABC):
    """Contract for any HSN/SAC data source (official GST portal, offline master, ...)."""

    @abstractmethod
    async def fetch_hsn_details(self, code: str) -> HSNDetails:
        """Return normalized HSNDetails for `code`.

        Must raise app.core.exceptions.HSNNotFoundError or GSTProviderError
        on failure — never a raw provider-specific exception.
        """
        raise NotImplementedError


