
import re

_GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
_CODE_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _checksum_is_valid(gstin: str) -> bool:
    factor = 1
    total = 0
    for ch in gstin[:-1]:
        value = _CODE_CHARS.index(ch) * factor
        value = (value // 36) + (value % 36)
        total += value
        factor = 2 if factor == 1 else 1
    expected = _CODE_CHARS[(36 - (total % 36)) % 36]
    return expected == gstin[-1]


def validate_gstin_format_and_checksum(gstin: str) -> bool:
    if not _GSTIN_REGEX.match(gstin):
        return False
    return _checksum_is_valid(gstin)


_HSN_REGEX = re.compile(r"^[0-9]{2}([0-9]{2}([0-9]{2}([0-9]{2})?)?)?$")


def validate_hsn_format(code: str) -> bool:
    """HSN/SAC codes are numeric and 2, 4, 6 or 8 digits long."""
    return bool(_HSN_REGEX.match(code))


