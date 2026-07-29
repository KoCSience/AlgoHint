"""Pure response-normalization tests cover Gemma parser shape changes."""

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

