"""Gemma endpoint validation that preserves explicit data-location policy."""

from urllib.parse import urlparse

from algohint.domain.enums import GemmaDeployment
from algohint.domain.models import ProviderAvailability

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def gemma_endpoint_availability(
    base_url: str,
    deployment: GemmaDeployment,
    *,
    credential_required: bool = False,
    credential_configured: bool = True,
) -> ProviderAvailability:
    """Validate an operator-owned URL and determine whether consent is required.

    A loopback URL can be an SSH tunnel, so an explicit remote deployment must
    override hostname inference instead of silently bypassing learner consent.
    """

    parsed = urlparse(base_url)
    configured = parsed.scheme in {"http", "https"} and parsed.hostname is not None
    if not configured:
        return ProviderAvailability(
            available=False,
            reason="Gemmaの有効なHTTP接続先が設定されていません。",
        )
    loopback = parsed.hostname in LOOPBACK_HOSTS
    if deployment is GemmaDeployment.LOCAL and not loopback:
        return ProviderAvailability(
            available=False,
            reason="local指定のGemma接続先はループバックアドレスに限定されます。",
        )
    if credential_required and not credential_configured:
        return ProviderAvailability(
            available=False,
            reason="ALGOHINT_GEMMA_API_KEYが設定されていません。",
            sends_data_off_device=deployment is GemmaDeployment.REMOTE or not loopback,
        )
    sends_data_off_device = (
        deployment is GemmaDeployment.REMOTE
        or (deployment is GemmaDeployment.AUTO and not loopback)
    )
    return ProviderAvailability(
        available=True,
        sends_data_off_device=sends_data_off_device,
    )

