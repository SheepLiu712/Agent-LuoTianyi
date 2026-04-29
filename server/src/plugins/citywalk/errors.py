class CitywalkError(Exception):
    """Citywalk base error."""


class AMapRequestError(CitywalkError):
    """AMap API request failed."""


class AMapResponseError(CitywalkError):
    """AMap API returned business error."""


class LLMDecisionError(CitywalkError):
    """Citywalk decision LLM failed or returned invalid output."""


class LLMEnvironmentError(CitywalkError):
    """Citywalk environment LLM failed or returned invalid output."""
