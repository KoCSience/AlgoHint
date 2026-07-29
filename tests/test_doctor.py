from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError

from algohint import cli
from algohint.cli import _parser, _run_gemini_doctor
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


def test_doctor_parser_requires_supported_provider() -> None:
    args = _parser().parse_args(["doctor", "--provider", "gemini"])

    assert args.command == "doctor"
    assert args.provider == "gemini"


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
