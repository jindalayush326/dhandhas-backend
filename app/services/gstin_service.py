from app.core.exceptions import InvalidGSTINError
from app.providers.base import GSTProvider
from app.schemas.gstin import GSTINDetails
from app.utils.validators import validate_gstin_format_and_checksum


class GSTINService:
    """Business rules live here, independent of which provider supplies the data."""

    def __init__(self, provider: GSTProvider):
        self._provider = provider

    async def validate_and_fetch(self, gstin: str) -> GSTINDetails:
        gstin = gstin.strip().upper()
        if not validate_gstin_format_and_checksum(gstin):
            raise InvalidGSTINError("Invalid GSTIN format or checksum")

        details = await self._provider.fetch_gstin_details(gstin)

        if details.status and details.status.upper() not in ("ACTIVE", "ACT"):
            raise InvalidGSTINError(f"GSTIN is not active (status: {details.status})")

        return details
