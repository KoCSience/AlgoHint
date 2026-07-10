"""Pure output-comparison rules shared by judge tests and production code."""


def normalize_trim(text: str) -> str:
    """Normalize benign presentation differences without masking content errors."""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized = [line.rstrip() for line in lines]
    while normalized and normalized[-1] == "":
        normalized.pop()
    return "\n".join(normalized)


def outputs_match(actual: str, expected: str) -> bool:
    """Apply the single, documented MVP comparison policy."""

    return normalize_trim(actual) == normalize_trim(expected)
