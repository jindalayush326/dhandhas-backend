import re

COMMON_WEAK_PASSWORDS = {
    "password", "password123", "12345678", "123456789", "qwerty123",
    "letmein", "admin123", "welcome123", "iloveyou", "abc12345",
}


def validate_password_strength(password: str) -> str:
    """Raises ValueError with a user-facing message if the password is weak.
    Returns the password unchanged if it passes (for use in a pydantic
    field_validator that must return the value)."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if len(password) > 128:
        raise ValueError("Password is too long")
    if password.lower() in COMMON_WEAK_PASSWORDS:
        raise ValueError("This password is too common — choose something less guessable")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[^a-zA-Z0-9]", password):
        raise ValueError("Password must contain at least one special character")
    return password
