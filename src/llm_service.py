from __future__ import annotations

import os
from typing import Iterator


DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_MAX_INPUT_CHARS = 120000
RECOMMENDED_MODEL_PATTERNS = (
    "qwen2.5:7b",
    "qwen3:8b",
    "llama3.1:8b",
    "mistral:7b",
    "gemma3:4b",
    "gemma4:e4b",
    "qwen2.5",
    "qwen3",
    "gemma4",
)


class OllamaServiceError(Exception):
    """Raised when the local Ollama service cannot complete a request."""


def get_configured_host() -> str:
    return os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).strip() or DEFAULT_OLLAMA_HOST


def get_configured_model() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def get_max_input_chars() -> int:
    raw_value = os.getenv("MAX_INPUT_CHARS", str(DEFAULT_MAX_INPUT_CHARS)).strip()
    try:
        return max(20000, int(raw_value))
    except ValueError:
        return DEFAULT_MAX_INPUT_CHARS


def trim_content(content: str, max_chars: int | None = None) -> tuple[str, bool]:
    limit = max_chars or get_max_input_chars()
    if len(content) <= limit:
        return content, False

    head_len = int(limit * 0.7)
    tail_len = limit - head_len
    trimmed = (
        content[:head_len].rstrip()
        + "\n\n[Middle content omitted to fit local model context]\n\n"
        + content[-tail_len:].lstrip()
    )
    return trimmed, True


def recommend_model(models: list[str]) -> str | None:
    """Choose a balanced study-generation model from locally installed models."""
    if not models:
        return None

    lowered = {model.lower(): model for model in models}
    for pattern in RECOMMENDED_MODEL_PATTERNS:
        if pattern in lowered:
            return lowered[pattern]
        for normalized, original in lowered.items():
            if normalized.startswith(f"{pattern}:") or pattern in normalized:
                return original

    return models[0]


class OllamaService:
    def __init__(self, host: str | None = None, model: str | None = None, timeout: float = 120.0) -> None:
        self.host = (host or get_configured_host()).strip()
        self.model = (model or get_configured_model()).strip()
        self.timeout = timeout

    def list_models(self) -> list[str]:
        client = self._client(timeout=5.0)
        try:
            response = client.list()
        except Exception as exc:
            raise OllamaServiceError(
                f"Could not connect to Ollama at {self.host}. Start Ollama and try again."
            ) from exc

        models = self._response_get(response, "models", [])
        names: list[str] = []
        for item in models:
            name = self._response_get(item, "model", None) or self._response_get(item, "name", None)
            if name:
                names.append(str(name))
        return sorted(set(names), key=str.lower)

    def stream(self, prompt: str, json_mode: bool = False) -> Iterator[str]:
        client = self._client(timeout=self.timeout)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are ExamPrep AI, a local exam preparation assistant. "
                    "Use only the supplied study material and produce clean Markdown."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            request_options = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": 0.2,
                    "top_p": 0.9,
                },
            }
            if json_mode:
                request_options["format"] = "json"

            stream = client.chat(
                **request_options,
            )
            for chunk in stream:
                text = self._chunk_text(chunk)
                if text:
                    yield text
        except Exception as exc:
            raise OllamaServiceError(
                f"Ollama generation failed for {self.model}. "
                f"Check that Ollama is running and the model is pulled. Details: {exc}"
            ) from exc

    def _client(self, timeout: float):
        try:
            from ollama import Client
        except Exception as exc:
            raise OllamaServiceError("Install the ollama Python package with `pip install ollama`.") from exc

        return Client(host=self.host, timeout=timeout)

    @staticmethod
    def _chunk_text(chunk: object) -> str:
        message = OllamaService._response_get(chunk, "message", {})
        return str(OllamaService._response_get(message, "content", "") or "")

    @staticmethod
    def _response_get(value: object, key: str, default: object = None) -> object:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)
