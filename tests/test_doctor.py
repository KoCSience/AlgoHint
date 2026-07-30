from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError

from algohint import cli
from algohint.cli import _parser, _run_gemini_doctor, _run_provider_doctor
from algohint.domain.enums import ProviderFailureReason
from algohint.domain.models import ProviderDiagnostic
from algohint.infrastructure.gemini_hint_provider import GeminiHintProvider


class DoctorModels:
    """Minimal fake models endpoint that never accepts learner content."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.kwargs: dict[str, object] = {}

    def get(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(name=kwargs["model"])


class FixedDiagnosticProvider:
    """Return one prebuilt diagnostic without opening a network connection."""

    def __init__(self, diagnostic: ProviderDiagnostic) -> None:
        self._diagnostic = diagnostic

    def diagnose(self, *, verbose: bool = False) -> ProviderDiagnostic:
        return self._diagnostic


def test_doctor_parser_requires_supported_provider() -> None:
    args = _parser().parse_args(["doctor", "--provider", "gemini", "--verbose"])

    assert args.command == "doctor"
    assert args.provider == "gemini"
    assert args.verbose

    gemma = _parser().parse_args(["doctor", "--provider", "gemma"])
    assert gemma.provider == "gemma"


def test_gemini_doctor_succeeds_without_generation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "private-key-marker")
    models = DoctorModels()
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(models=models),
    )

    status = _run_gemini_doctor(provider)

    output = capsys.readouterr().out
    assert status == 0
    assert models.kwargs == {"model": "gemini-3.6-flash"}
    assert "Gemini診断: OK" in output
    assert "private-key-marker" not in output


def test_gemini_doctor_reports_safe_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "private-key-marker")
    error = ClientError(
        404,
        {
            "error": {
                "code": 404,
                "status": "NOT_FOUND",
                "message": "raw-response-marker",
            }
        },
    )
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(models=DoctorModels(error)),
    )

    status = _run_gemini_doctor(provider)

    output = capsys.readouterr().out
    assert status == 1
    assert "reason_code=model_not_found" in output
    assert "http_status=404" in output
    assert "private-key-marker" not in output
    assert "raw-response-marker" not in output


def test_gemma_doctor_reports_endpoint_recovery_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = FixedDiagnosticProvider(
        ProviderDiagnostic(
            healthy=False,
            provider="gemma",
            model="google/gemma-4-12B-it",
            reason_code=ProviderFailureReason.ENDPOINT_UNREACHABLE,
            retryable=True,
            exception_type="ConnectError",
        )
    )

    status = _run_provider_doctor("Gemma", provider)

    output = capsys.readouterr().out
    assert status == 1
    assert "reason_code=endpoint_unreachable" in output
    assert "run-ssh-stack.sh" in output
    assert "run-local-stack.sh" in output


def test_gemini_doctor_verbose_shows_redacted_development_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "private-key-marker"
    bearer = "private-bearer-marker"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(
            models=DoctorModels(
                RuntimeError(f"diagnostic failed api_key={secret} Authorization: Bearer {bearer}")
            )
        ),
        development_mode=True,
    )

    status = _run_gemini_doctor(
        provider,
        verbose=True,
        development_mode=True,
    )

    output = capsys.readouterr().out
    assert status == 1
    assert "Gemini診断詳細" in output
    assert "RuntimeError" in output
    assert "diagnostic failed" in output
    assert "[REDACTED]" in output
    assert secret not in output
    assert bearer not in output


def test_gemini_doctor_verbose_requires_development(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "private-key-marker")
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: SimpleNamespace(
            models=DoctorModels(RuntimeError("private-runtime-marker"))
        ),
    )

    status = _run_gemini_doctor(
        provider,
        verbose=True,
        development_mode=False,
    )

    output = capsys.readouterr().out
    assert status == 1
    assert "developmentでのみ有効" in output
    assert "private-runtime-marker" not in output


def test_gemini_doctor_reports_missing_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiHintProvider(
        "gemini-3.6-flash",
        client_factory=lambda: pytest.fail("client must not be constructed"),
    )

    status = _run_gemini_doctor(provider)

    assert status == 1
    assert "reason_code=not_configured" in capsys.readouterr().out


def test_main_doctor_returns_nonzero_for_missing_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise command dispatch without opening a network connection."""

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(SystemExit) as raised:
        cli.main(["doctor", "--provider", "gemini"])

    assert raised.value.code == 1
    assert "reason_code=not_configured" in capsys.readouterr().out


def test_main_gemma_doctor_returns_nonzero_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ALGOHINT_GEMMA_BACKEND", "transformers_http")
    monkeypatch.setenv("ALGOHINT_GEMMA_DEPLOYMENT", "remote")
    monkeypatch.setenv("ALGOHINT_GEMMA_BASE_URL", "http://127.0.0.1:18000/v1")
    monkeypatch.delenv("ALGOHINT_GEMMA_API_KEY", raising=False)

    with pytest.raises(SystemExit) as raised:
        cli.main(["doctor", "--provider", "gemma"])

    assert raised.value.code == 1
    output = capsys.readouterr().out
    assert "Gemma診断: NG" in output
    assert "reason_code=not_configured" in output
