"""Small authentication helpers that never retain or log bearer values."""

import secrets


def bearer_is_valid(header: str | None, expected_key: str) -> bool:
    """Compare a strict Bearer header in constant time."""

    if header is None:
        return False
    scheme, separator, value = header.partition(" ")
    if separator != " " or scheme != "Bearer" or not value:
        return False
    return secrets.compare_digest(value, expected_key)

