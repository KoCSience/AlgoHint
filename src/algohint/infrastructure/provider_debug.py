"""Development-only provider exception formatting with credential redaction."""

import re
import traceback
from collections.abc import Iterable

_NAMED_SECRET_PATTERN = re.compile(
    r"(?i)\b(authorization|x-goog-api-key|api[_-]?key)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?\s*)"
    r"(?:Bearer\s+)?([^\s,;}]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
REDACTED = "[REDACTED]"


def format_provider_exception(
    error: BaseException,
    *,
    secrets: Iterable[str] = (),
) -> str:
    """Format an exception chain for development after removing credentials.

    Tracebacks are intentionally available only to explicit development paths.
    Redaction remains mandatory there because development logs are often copied
    into issue reports or shared terminals.
    """

    details = "".join(traceback.format_exception(error))
    for secret in secrets:
        if secret:
            details = details.replace(secret, REDACTED)
    details = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", details)
    return _NAMED_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        details,
    )
