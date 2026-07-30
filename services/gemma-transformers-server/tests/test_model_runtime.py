"""Pure response-normalization tests cover Gemma parser shape changes."""

import sys
from types import SimpleNamespace

from algohint_gemma_server.config import ServerConfig
from algohint_gemma_server.model_runtime import TransformersGemmaRuntime


def test_extracts_final_text_from_supported_parser_shapes() -> None:
    assert TransformersGemmaRuntime._extract_text("hint") == "hint"
    assert TransformersGemmaRuntime._extract_text({"text": "hint"}) == "hint"
    assert (
        TransformersGemmaRuntime._extract_text(
            [{"content": ""}, {"role": "assistant", "content": "hint"}]
        )
        == "hint"
    )


def test_unknown_parser_shape_returns_no_text() -> None:
    assert TransformersGemmaRuntime._extract_text({"unknown": 1}) == ""


def test_model_load_is_pinned_to_pre_downloaded_local_files(monkeypatch) -> None:
    """Startup must not turn a missing model into an implicit network download."""

    captured: dict[str, dict[str, object]] = {}

    class FakeProcessorLoader:
        @staticmethod
        def from_pretrained(model_id: str, **kwargs):
            captured["processor"] = {"model_id": model_id, **kwargs}
            return object()

    class FakeModel:
        def __init__(self) -> None:
            self.hf_device_map = {"layer": 0}

        def eval(self) -> None:
            return None

    class FakeModelLoader:
        @staticmethod
        def from_pretrained(model_id: str, **kwargs):
            captured["model"] = {"model_id": model_id, **kwargs}
            return FakeModel()

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            device_count=lambda: 1,
            is_available=lambda: True,
            is_bf16_supported=lambda: True,
        ),
        bfloat16="bfloat16",
        float16="float16",
    )
    fake_transformers = SimpleNamespace(
        AutoModelForMultimodalLM=FakeModelLoader,
        AutoProcessor=FakeProcessorLoader,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    runtime = TransformersGemmaRuntime(
        ServerConfig(api_key="test-only-api-key-that-is-long-enough")
    )

    runtime.load()

    assert captured["processor"]["local_files_only"] is True
    assert captured["model"]["local_files_only"] is True
