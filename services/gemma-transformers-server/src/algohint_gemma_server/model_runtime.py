"""Text-only Gemma runtime isolated from HTTP and authentication concerns."""

from __future__ import annotations

from typing import Any, Protocol

from algohint_gemma_server.config import ServerConfig


class ModelNotReadyError(RuntimeError):
    """The process is alive but model loading has not completed."""


class InputTooLongError(ValueError):
    """The rendered chat exceeds the configured token budget."""


class InvalidModelOutputError(ValueError):
    """The model returned no learner-displayable final text."""


class HintRuntime(Protocol):
    """Minimal interface used by FastAPI and replaced by fakes in tests."""

    @property
    def ready(self) -> bool: ...

    def load(self) -> None: ...

    def generate(
        self,
        system_instructions: str,
        learner_context: str,
        *,
        max_output_chars: int = 1_200,
        max_new_tokens: int | None = None,
    ) -> str: ...


class TransformersGemmaRuntime:
    """Load one Gemma model across visible GPUs and generate text-only hints."""

    def __init__(self, config: ServerConfig) -> None:
        self._config = config
        self._model: Any | None = None
        self._processor: Any | None = None
        self._torch: Any | None = None

    @property
    def ready(self) -> bool:
        """Report readiness only after both model and processor are retained."""

        return self._model is not None and self._processor is not None

    def load(self) -> None:
        """Load the pinned checkpoint without requiring torch at package import time."""

        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor

        gpu_count = torch.cuda.device_count()
        if gpu_count <= 0 or not torch.cuda.is_available():
            raise RuntimeError("no CUDA device is available")
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        processor = AutoProcessor.from_pretrained(
            self._config.model_id,
            revision=self._config.model_revision,
        )
        model = AutoModelForMultimodalLM.from_pretrained(
            self._config.model_id,
            revision=self._config.model_revision,
            dtype=dtype,
            device_map="balanced",
            max_memory=self._config.max_memory(gpu_count),
            low_cpu_mem_usage=True,
        )
        model.eval()
        self._torch = torch
        self._processor = processor
        self._model = model

    def generate(
        self,
        system_instructions: str,
        learner_context: str,
        *,
        max_output_chars: int = 1_200,
        max_new_tokens: int | None = None,
    ) -> str:
        """Apply Gemma's chat template, suppress thinking, and return final plain text."""

        if not self.ready or self._torch is None:
            raise ModelNotReadyError("model is not ready")
        model = self._model
        processor = self._processor
        torch = self._torch
        assert model is not None
        assert processor is not None
        messages = [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": learner_context},
        ]
        inputs = processor.apply_chat_template(
            messages,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
            add_generation_prompt=True,
            enable_thinking=False,
        )
        input_ids = inputs["input_ids"]
        input_length = int(input_ids.shape[-1])
        if input_length > self._config.max_input_tokens:
            raise InputTooLongError("rendered prompt exceeds the token limit")
        model_device = getattr(model, "device", None)
        if model_device is not None:
            inputs = inputs.to(model_device)
        output_tokens = max_new_tokens or self._config.max_new_tokens
        if not 1 <= output_tokens <= 4_096:
            raise ValueError("max_new_tokens is outside the supported range")
        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=output_tokens,
                do_sample=True,
                temperature=1.0,
                top_p=0.95,
                top_k=64,
            )
        generated = outputs[0][input_length:]
        decoded = processor.decode(generated, skip_special_tokens=False)
        text = self._final_text(processor, decoded, input_ids)
        if not text:
            raise InvalidModelOutputError("model returned no final text")
        if not 1 <= max_output_chars <= 8_000:
            raise ValueError("max_output_chars is outside the supported range")
        if len(text) > max_output_chars:
            raise InvalidModelOutputError("model output exceeds the character limit")
        return text

    @staticmethod
    def _final_text(processor: Any, decoded: str, input_ids: Any) -> str:
        """Normalize current and future ``parse_response`` return shapes conservatively."""

        try:
            parsed = processor.parse_response(decoded, prefix=input_ids)
        except (AttributeError, TypeError, ValueError):
            parsed = decoded
        return TransformersGemmaRuntime._extract_text(parsed).strip()

    @staticmethod
    def _extract_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("text", "content", "final", "response"):
                if key in value:
                    text = TransformersGemmaRuntime._extract_text(value[key])
                    if text:
                        return text
            return ""
        if isinstance(value, (list, tuple)):
            for item in reversed(value):
                text = TransformersGemmaRuntime._extract_text(item)
                if text:
                    return text
        return ""
