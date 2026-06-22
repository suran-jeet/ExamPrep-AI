from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Iterator

from src.diagnostics import get_logger


class GeminiServiceError(Exception):
    """Raised when Gemini cannot validate or complete a request."""


RECOMMENDED_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]

GEMINI_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


@dataclass(frozen=True)
class GeminiConnectionResult:
    ok: bool
    message: str
    models: list[str]


class GeminiService:
    def __init__(self, api_key: str, model: str, timeout_ms: int = 120000, max_retries: int = 3) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_ms = timeout_ms
        self.max_retries = max(1, max_retries)
        self.logger = get_logger()

    def list_models(self) -> list[str]:
        client = self._client()
        try:
            models = client.models.list()
            names: list[str] = []
            for model in models:
                name = str(getattr(model, "name", "") or "")
                actions = getattr(model, "supported_actions", None) or []
                normalized = name.removeprefix("models/")
                blocked_terms = ("tts", "live", "image", "embedding", "computer-use", "deep-research")
                supports_generation = not actions or "generateContent" in actions
                if name and supports_generation and not any(term in normalized.lower() for term in blocked_terms):
                    names.append(normalized)
            preferred = [model for model in RECOMMENDED_GEMINI_MODELS if model in names]
            others = sorted(set(names) - set(preferred), key=str.lower)
            return preferred + others
        except Exception as exc:
            raise GeminiServiceError(_friendly_error(exc, "Gemini model loading failed.")) from exc
        finally:
            client.close()

    def test_connection(self) -> GeminiConnectionResult:
        try:
            models = self.list_models()
            if self.model and models and self.model not in models:
                return GeminiConnectionResult(
                    ok=False,
                    message="The API key works, but the selected Gemini model is not available to this account.",
                    models=models,
                )
            probe_model = self.model if self.model in models else (models[0] if models else self.model)
            if probe_model:
                self._probe_generation(probe_model)
            return GeminiConnectionResult(
                ok=True,
                message=f"Gemini connection is ready with {probe_model}.",
                models=models,
            )
        except GeminiServiceError as exc:
            return GeminiConnectionResult(ok=False, message=str(exc), models=[])

    def stream(self, prompt: str, json_mode: bool = False) -> Iterator[str]:
        last_error: Exception | None = None
        model_sequence = self._model_sequence()

        for model in model_sequence:
            for attempt in range(self.max_retries):
                try:
                    self.logger.info("gemini_attempt model=%s attempt=%s", model, attempt + 1)
                    chunks = self._generate_once(model, prompt, json_mode)
                    for chunk in chunks:
                        yield chunk
                    if model != self.model:
                        self.logger.info("gemini_fallback_success selected=%s actual=%s", self.model, model)
                    return
                except Exception as exc:
                    last_error = exc
                    friendly = _friendly_error(exc, f"Gemini failed with {model}.")
                    self.logger.warning(
                        "gemini_attempt_failed model=%s attempt=%s error=%s",
                        model,
                        attempt + 1,
                        friendly,
                    )
                    if not _is_retryable(exc):
                        break
                    if attempt < self.max_retries - 1:
                        time.sleep(min(8, 1.5 * (2**attempt)))

        detail = _friendly_error(last_error, "Gemini could not generate the requested content.")
        raise GeminiServiceError(detail)

    def _generate_once(self, model: str, prompt: str, json_mode: bool) -> list[str]:
        client = self._client()
        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                temperature=0.15,
                top_p=0.9,
                response_mime_type="application/json" if json_mode else "text/plain",
            )
            chunks: list[str] = []
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=config,
            ):
                text = getattr(chunk, "text", None)
                if text:
                    chunks.append(str(text))
            if not chunks:
                raise GeminiServiceError("Gemini returned an empty response. Please try again.")
            return chunks
        finally:
            client.close()

    def _probe_generation(self, model: str) -> None:
        client = self._client()
        try:
            from google.genai import types

            config = types.GenerateContentConfig(temperature=0, max_output_tokens=8)
            response = client.models.generate_content(
                model=model,
                contents="Reply with OK.",
                config=config,
            )
            if not str(getattr(response, "text", "") or "").strip():
                raise GeminiServiceError("Gemini accepted the key but returned an empty test response.")
        except Exception as exc:
            raise GeminiServiceError(_friendly_error(exc, "Gemini connection test failed.")) from exc
        finally:
            client.close()

    def _model_sequence(self) -> list[str]:
        return list(dict.fromkeys(([self.model] if self.model else []) + GEMINI_FALLBACK_MODELS))

    def _client(self):
        if not self.api_key:
            raise GeminiServiceError("Enter a Gemini API key in Model Settings.")
        if not self.model:
            raise GeminiServiceError("Choose a Gemini model in Model Settings.")

        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise GeminiServiceError("Install Gemini support with `pip install google-genai`.") from exc

        return genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=self.timeout_ms),
        )


def _is_retryable(exc: Exception | None) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    retry_terms = (
        "503",
        "unavailable",
        "overloaded",
        "timeout",
        "temporarily",
        "deadline",
        "rate",
        "quota",
        "429",
        "500",
        "502",
        "504",
    )
    return any(term in text for term in retry_terms)


def _friendly_error(exc: Exception | None, fallback: str) -> str:
    if exc is None:
        return fallback
    raw = str(exc)
    text = f"{type(exc).__name__}: {raw}".lower()

    if "503" in text or "unavailable" in text or "overloaded" in text:
        return "Gemini is currently overloaded. Please try again in a few moments."
    if "429" in text or "quota" in text or "rate limit" in text:
        return "Gemini quota or rate limit was reached. Wait a bit, check billing/quota, or switch to Ollama."
    if "api key" in text or "permission" in text or "unauthenticated" in text or "401" in text or "403" in text:
        return "Gemini rejected the API key. Check the key in Model Settings and save it again."
    if "not found" in text or "404" in text or "model" in text and "not" in text:
        return "The selected Gemini model is not available. Choose another model from Model Settings."
    if "deadline" in text or "timeout" in text or "network" in text:
        return "Gemini did not respond in time. Check your internet connection and try again."

    cleaned = re.sub(r"\{.*\}", "", raw, flags=re.DOTALL).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned:
        return f"{fallback} {cleaned[:220]}"
    return fallback
