
import httpx

from app.core.config import settings
from app.core.exceptions import GSTINNotFoundError, GSTProviderError, InvalidGSTINError
from app.providers.base import GSTProvider
from app.schemas.gstin import GSTINDetails


class GstinApiProvider(GSTProvider):
    """https://www.gstinapi.in/docs — 100 free credits, no card required."""

    BASE_URL = "https://www.gstinapi.in/v1/gstin"

    async def fetch_gstin_details(self, gstin: str) -> GSTINDetails:
        headers = {"x-api-key": settings.gstinapi_api_key}

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                response = await client.get(f"{self.BASE_URL}/{gstin}", headers=headers)
        except httpx.RequestError as exc:
            raise GSTProviderError(f"Upstream request failed: {exc}") from exc

        body = response.json()

        if response.status_code == 400:
            raise InvalidGSTINError(body.get("error", "Invalid GSTIN format"))
        if response.status_code == 404:
            raise GSTINNotFoundError(body.get("error", "GSTIN not registered"))
        if response.status_code != 200 or not body.get("success"):
            raise GSTProviderError(body.get("error", f"Upstream returned status {response.status_code}"))

        data = body["data"]
        return GSTINDetails(
            gstin=data.get("gstin", gstin),
            legal_name=data.get("legal_name", ""),
            trade_name=data.get("trade_name", ""),
            status=data.get("status", ""),
            address=data.get("address", ""),
            city=data.get("city", ""),
            pincode=data.get("pincode", ""),
        )


