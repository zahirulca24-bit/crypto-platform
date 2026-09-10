from __future__ import annotations
import json, os, re
from typing import Any
import httpx
from pydantic import ValidationError
from .prompts import SYSTEM_PROMPT, STRATEGY_DISCOVERY_SYSTEM_PROMPT
from .schemas import ProposalBatch

class AIProviderError(RuntimeError): pass
class AIProviderNotConfigured(AIProviderError): pass
class AIProviderResponseError(AIProviderError): pass

class GeminiResearchProvider:
    provider_name = "google_gemini"
    def __init__(self, *, api_key: str | None = None, model_name: str | None = None,
                 temperature: float | None = None, max_output_tokens: int | None = None,
                 timeout_seconds: float | None = None, transport: httpx.BaseTransport | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_AI_API_KEY", "")
        self._model_name = model_name if model_name is not None else (os.getenv("GOOGLE_AI_MODEL") or "gemini-2.5-flash")
        self._configuration_error: str | None = None
        try:
            self.temperature = float(temperature if temperature is not None else os.getenv("GOOGLE_AI_TEMPERATURE", "0.2"))
            self.max_output_tokens = int(max_output_tokens if max_output_tokens is not None else os.getenv("GOOGLE_AI_MAX_OUTPUT_TOKENS", "2048"))
            self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else os.getenv("GOOGLE_AI_TIMEOUT_SECONDS", "30"))
            if not (0 <= self.temperature <= 2): raise ValueError("temperature")
            if not (128 <= self.max_output_tokens <= 65536): raise ValueError("max_output_tokens")
            if not (1 <= self.timeout_seconds <= 300): raise ValueError("timeout")
            if not re.fullmatch(r"[A-Za-z0-9._-]+", self._model_name): raise ValueError("model")
        except (TypeError, ValueError):
            self._configuration_error = "Gemini model configuration is invalid"
            self.temperature = 0.2; self.max_output_tokens = 2048; self.timeout_seconds = 30.0
        self.transport = transport
    @property
    def model_name(self) -> str: return self._model_name
    @property
    def configured(self) -> bool: return bool(self.api_key.strip()) and self._configuration_error is None
    def health_check(self) -> dict[str, Any]:
        return {"configured": self.configured, "provider": self.provider_name, "model": self.model_name, "configuration_error": bool(self._configuration_error)}
    def generate_research_proposals(self, *, context: dict[str, Any], prompt: str, max_proposals: int):
        if self._configuration_error: raise AIProviderError(self._configuration_error)
        if not self.configured: raise AIProviderNotConfigured("Google AI Studio API key is not configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_output_tokens, "responseMimeType": "application/json"},
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(url, headers={"x-goog-api-key": self.api_key}, json=payload)
            if response.status_code >= 400:
                if response.status_code in (401, 403): msg = "Gemini authentication failed"
                elif response.status_code == 429: msg = "Gemini quota/rate limit reached"
                else: msg = f"Gemini provider unavailable (HTTP {response.status_code})"
                raise AIProviderError(msg)
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            batch = ProposalBatch.model_validate(parsed)
            if len(batch.proposals) > max_proposals:
                batch = ProposalBatch(proposals=batch.proposals[:max_proposals])
            metadata = {"finish_reason": body.get("candidates", [{}])[0].get("finishReason"), "usage_metadata": body.get("usageMetadata", {})}
            return batch, metadata
        except AIProviderError: raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AIProviderError("Gemini request timed out or provider is unavailable") from exc
        except (KeyError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise AIProviderResponseError("Gemini returned malformed structured output") from exc
    def analyze_research_context(self, *, context: dict[str, Any], prompt: str) -> dict[str, Any]:
        batch, metadata = self.generate_research_proposals(context=context, prompt=prompt, max_proposals=1)
        return {"proposal": batch.proposals[0].model_dump(mode="json"), "metadata": metadata}

    def generate_strategy_blueprint(self, *, context: dict[str, Any], prompt: str):
        if self._configuration_error: raise AIProviderError(self._configuration_error)
        if not self.configured: raise AIProviderNotConfigured("Google AI Studio API key is not configured")
        from .schemas import StructuredStrategyBlueprint
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        payload={"systemInstruction":{"parts":[{"text":STRATEGY_DISCOVERY_SYSTEM_PROMPT}]},"contents":[{"role":"user","parts":[{"text":prompt}]}],"generationConfig":{"temperature":self.temperature,"maxOutputTokens":self.max_output_tokens,"responseMimeType":"application/json"}}
        try:
            with httpx.Client(timeout=self.timeout_seconds,transport=self.transport) as client: response=client.post(url,headers={"x-goog-api-key":self.api_key},json=payload)
            if response.status_code>=400:
                if response.status_code in (401,403): msg="Gemini authentication failed"
                elif response.status_code==429: msg="Gemini quota/rate limit reached"
                else: msg=f"Gemini provider unavailable (HTTP {response.status_code})"
                raise AIProviderError(msg)
            body=response.json(); parsed=json.loads(body["candidates"][0]["content"]["parts"][0]["text"]); bp=StructuredStrategyBlueprint.model_validate(parsed)
            return bp.model_dump(mode="json"),{"finish_reason":body.get("candidates",[{}])[0].get("finishReason"),"usage_metadata":body.get("usageMetadata",{})}
        except AIProviderError: raise
        except (httpx.TimeoutException,httpx.NetworkError) as exc: raise AIProviderError("Gemini request timed out or provider is unavailable") from exc
        except (KeyError,ValueError,json.JSONDecodeError,ValidationError) as exc: raise AIProviderResponseError("Gemini returned malformed structured blueprint output") from exc
