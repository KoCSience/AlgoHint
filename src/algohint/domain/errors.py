"""Expected domain-facing failures from optional hint providers."""


class HintProviderError(RuntimeError):
    """A safe, recoverable provider failure that should use local fallback."""
