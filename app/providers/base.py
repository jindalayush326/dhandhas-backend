
from abc import ABC, abstractmethod

from app.schemas.gstin import GSTINDetails


class GSTProvider(ABC):
    """Contract for any GSTIN data source (3rd-party API or official GST portal)."""

    @abstractmethod
    async def fetch_gstin_details(self, gstin: str) -> GSTINDetails:
        """Fetch raw data from the source and return it normalized as GSTINDetails.

        Must raise app.core.exceptions.GSTINNotFoundError or GSTProviderError
        on failure — never a raw provider-specific exception.
        """
        raise NotImplementedError


