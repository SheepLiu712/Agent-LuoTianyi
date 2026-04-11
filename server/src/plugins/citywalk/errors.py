class CitywalkError(Exception):
    """Citywalk base error."""


class AMapRequestError(CitywalkError):
    """AMap API request failed."""


class AMapResponseError(CitywalkError):
    """AMap API returned business error."""
