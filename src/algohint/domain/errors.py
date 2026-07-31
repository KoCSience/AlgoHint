"""Expected domain-facing failures from optional hint providers."""

from algohint.domain.enums import ProviderFailureReason


class HintProviderError(RuntimeError):
    """A classified, secret-free provider failure that should use local fallback."""

    def __init__(
        self,
        *,
        reason_code: ProviderFailureReason,
        provider: str,
        model: str,
        http_status: int | None = None,
        retryable: bool = False,
        exception_type: str = "UnknownError",
    ) -> None:
        self.reason_code = reason_code
        self.provider = provider
        self.model = model
        self.http_status = http_status
        self.retryable = retryable
        self.exception_type = exception_type
        # Keep exception text safe even if a caller logs it accidentally.
        super().__init__(reason_code.value)


class DraftConflictError(RuntimeError):
    """Reject an edit based on an older server-side draft revision."""

    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__("draft_conflict")
