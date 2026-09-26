from app.core.exceptions import InvalidHSNError
from app.providers.hsn_base import HSNProvider
from app.schemas.hsn import HSNDetails
from app.utils.validators import validate_hsn_format


class HSNService:
    """Validate format, then look up via the bundled offline CBIC/GST master.
    Swap in a live provider later by passing a different HSNProvider in —
    nothing else changes."""

    def __init__(self, provider: HSNProvider):
        self._provider = provider

    async def validate_and_fetch(self, code: str) -> HSNDetails:
        code = code.strip()
        if not validate_hsn_format(code):
            raise InvalidHSNError("HSN/SAC must be numeric, 2/4/6/8 digits")
        return await self._provider.fetch_hsn_details(code)
