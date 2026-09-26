
import json
from functools import lru_cache
from pathlib import Path

from app.core.exceptions import HSNNotFoundError
from app.providers.hsn_base import HSNProvider
from app.schemas.hsn import HSNDetails

_CHAPTERS_FILE = Path(__file__).resolve().parent.parent / "data" / "hsn_chapters.json"
_CODES_FILE = Path(__file__).resolve().parent.parent / "data" / "hsn_codes.json"


@lru_cache
def _load_chapters() -> dict[str, str]:
    with open(_CHAPTERS_FILE, encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def _load_codes() -> dict[str, str]:
    """Full 4/6/8-digit code -> description, parsed from the official
    CBIC/GST HSN master (~15.8k entries). See data/hsn_codes.json.
    """
    with open(_CODES_FILE, encoding="utf-8") as f:
        return json.load(f)


class OfflineHSNProvider(HSNProvider):
    """No network required. A code is valid ONLY if it's an exact match in
    the bundled master list (17.4k official codes) or is itself a real
    2-digit chapter. A 6/8-digit code that isn't in the list is genuinely
    unrecognized and must fail — silently falling back to its chapter's
    generic description would misreport an invalid/unlisted code as valid.
    """

    async def fetch_hsn_details(self, code: str) -> HSNDetails:
        chapter = code[:2]
        chapters = _load_chapters()
        if chapter not in chapters:
            raise HSNNotFoundError(f"'{chapter}' is not a recognized HSN chapter")

        if len(code) == 2:
            return HSNDetails(code=code, description=chapters[chapter], chapter=chapter, source="offline")

        codes = _load_codes()
        exact = codes.get(code)
        if exact is None:
            raise HSNNotFoundError(f"HSN/SAC code '{code}' was not found in the official master list")

        return HSNDetails(code=code, description=exact, chapter=chapter, source="offline")


