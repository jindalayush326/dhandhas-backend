class AppError(Exception):
    """Base for every domain error. Each subclass maps to one HTTP status
    in app/main.py's single exception handler — add a new error type here,
    map it once there, done."""

    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class ValidationError(AppError):
    status_code = 422


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class UnbalancedVoucherError(ValidationError):
    pass


# GST / HSN specific (kept distinct because they carry provider semantics)
class InvalidGSTINError(ValidationError):
    pass


class GSTINNotFoundError(NotFoundError):
    pass


class GSTProviderError(AppError):
    status_code = 502


class InvalidHSNError(ValidationError):
    pass


class HSNNotFoundError(NotFoundError):
    pass


# Auth specific
class TokenExpiredError(UnauthorizedError):
    pass


class InvalidTokenError(UnauthorizedError):
    pass


class InvitationError(AppError):
    status_code = 400


class RateLimitError(AppError):
    status_code = 429
