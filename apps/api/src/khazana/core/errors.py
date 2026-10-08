"""Application errors and their HTTP mapping.

One place, so that an endpoint raises a domain error and never decides a
status code, and so that no error message leaks whether a record exists in
another brand's data. ``NotFound`` and ``Forbidden`` are deliberately both
answered with 404 for cross tenant reads: confirming that a lot exists but
belongs to someone else is itself a leak.
"""

from __future__ import annotations

from fastapi import HTTPException, status


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "app_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def as_http(self) -> HTTPException:
        return HTTPException(
            status_code=self.status_code,
            detail={"code": self.code, "message": self.message},
        )


class ValidationFailed(AppError):
    # Spelled as the number because Starlette renamed the constant and
    # importing either name produces a deprecation warning on one version or
    # an ImportError on the other. The code is stable, the constant is not.
    status_code = 422
    code = "validation_failed"


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Unauthenticated(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class CrossTenant(NotFound):
    """A real tenant boundary breach, reported as if the record did not exist.

    Logged at warning level by the handler, because a burst of these is either
    a bug in a query or someone probing identifiers.
    """

    code = "not_found"


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


class SpendLimitReached(AppError):
    """An AI spend cap stopped the work before the call was made."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "ai_spend_limit"


class FeatureDisabled(AppError):
    """A kill switch is off for this AI feature."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "feature_disabled"
