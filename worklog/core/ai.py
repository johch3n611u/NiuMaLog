from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import ReportContext, ReportDraft, ReportInstructions
from .utils import json_dumps


class KeyStore:
    """Small keychain facade. Optional keyring is used when installed; env vars remain supported for CLI use."""

    def __init__(self):
        self._memory: Dict[str, str] = {}
        try:
            import keyring  # type: ignore
            self._keyring = keyring
        except Exception:
            self._keyring = None

    def get(self, provider: str) -> Optional[str]:
        env_name = "WORKLOG_%s_API_KEY" % provider.upper()
        if os.getenv(env_name):
            return os.getenv(env_name)
        if provider in self._memory:
            return self._memory[provider]
        if self._keyring:
            try:
                return self._keyring.get_password("worklog", provider)
            except Exception:
                return None
        return None

    def set(self, provider: str, value: str) -> None:
        self._memory[provider] = value
        if self._keyring:
            try:
                self._keyring.set_password("worklog", provider, value)
            except Exception:
                pass


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderConfig:
    """Connection settings for an official provider or a local relay such as CCSwitch."""

    provider: str
    protocol: str = "openai"
    base_url: Optional[str] = None
    model: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _instructions_text(instructions: ReportInstructions) -> str:
    return "Generate a concise, factual %s work report in %s. Return JSON with keys overview and sections. sections must be an object whose values are arrays of {title, summary, type}. Tone: %s." % (
        "daily or weekly", instructions.language, instructions.tone)


def build_prompt(context: ReportContext, instructions: ReportInstructions) -> Dict[str, Any]:
    payload = context.as_payload()
    for term in instructions.redaction_terms:
        payload = _redact(payload, term)
    return {"system": _instructions_text(instructions), "context": payload}


def _redact(value: Any, term: str) -> Any:
    if isinstance(value, str):
        return value.replace(term, "[已隐藏]")
    if isinstance(value, list):
        return [_redact(item, term) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, term) for key, item in value.items()}
    return value


class ModelProvider:
    name = "unknown"

    def generate_report(self, context: ReportContext, instructions: ReportInstructions) -> ReportDraft:
        raise NotImplementedError


class OpenAIProvider(ModelProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", endpoint: str = "https://api.openai.com/v1/chat/completions", provider_name: str = "openai"):
        self.api_key, self.model, self.endpoint, self.name = api_key, model, endpoint, provider_name

    def generate_report(self, context: ReportContext, instructions: ReportInstructions) -> ReportDraft:
        prompt = build_prompt(context, instructions)
        body = {"model": self.model, "temperature": 0.2, "response_format": {"type": "json_object"}, "messages": [{"role": "system", "content": prompt["system"]}, {"role": "user", "content": json_dumps(prompt["context"])}]}
        response = _post_json(self.endpoint, {"Authorization": "Bearer %s" % self.api_key}, body)
        try:
            content = response["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("OpenAI returned invalid structured output") from exc
        return validate_draft(data, self.name, response)


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-latest", endpoint: str = "https://api.anthropic.com/v1/messages", provider_name: str = "anthropic"):
        self.api_key, self.model, self.endpoint, self.name = api_key, model, endpoint, provider_name

    def generate_report(self, context: ReportContext, instructions: ReportInstructions) -> ReportDraft:
        prompt = build_prompt(context, instructions)
        body = {"model": self.model, "max_tokens": 3000, "temperature": 0.2, "system": prompt["system"], "messages": [{"role": "user", "content": json_dumps(prompt["context"])}]}
        response = _post_json(self.endpoint, {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, body)
        try:
            content = response["content"][0]["text"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("Anthropic returned invalid structured output") from exc
        return validate_draft(data, self.name, response)


def _post_json(endpoint: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
    request = Request(endpoint, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ProviderError("Model request failed: %s" % exc) from exc


def validate_draft(data: Any, provider: str, raw_response: Optional[Dict[str, Any]] = None) -> ReportDraft:
    if not isinstance(data, dict) or not isinstance(data.get("overview", ""), str) or not isinstance(data.get("sections", {}), dict):
        raise ProviderError("Model output must contain overview and sections")
    sections: Dict[str, List[Dict[str, Any]]] = {}
    for key, items in data.get("sections", {}).items():
        if not isinstance(items, list):
            raise ProviderError("Model section %s must be an array" % key)
        sections[key] = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("title", ""), str) or not isinstance(item.get("summary", ""), str):
                raise ProviderError("Model section items must contain title and summary")
            sections[key].append({"title": item["title"], "summary": item["summary"], "type": item.get("type", key)})
    return ReportDraft(data["overview"], sections, provider, raw_response)


class AIService:
    def __init__(self, key_store: Optional[KeyStore] = None, config_path: str = ".worklog/provider-settings.json"):
        self.key_store = key_store or KeyStore()
        self.config_path = Path(config_path).expanduser()
        self._configs: Dict[str, ProviderConfig] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._configs = {key: ProviderConfig(key, value.get("protocol", "openai"), value.get("base_url"), value.get("model")) for key, value in data.items() if isinstance(value, dict)}
        except (OSError, ValueError, TypeError):
            self._configs = {}

    def set_config(self, provider: str, protocol: str = "openai", base_url: Optional[str] = None, model: Optional[str] = None) -> ProviderConfig:
        if provider not in ("openai", "anthropic", "ccswitch"):
            raise ProviderError("Unsupported provider: %s" % provider)
        if protocol not in ("openai", "anthropic"):
            raise ProviderError("Protocol must be openai or anthropic")
        config = ProviderConfig(provider, protocol, base_url.strip() if base_url else None, model.strip() if model else None)
        self._configs[provider] = config
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps({key: item.to_dict() for key, item in self._configs.items()}, ensure_ascii=False, indent=2), encoding="utf-8")
        return config

    def configs(self) -> List[ProviderConfig]:
        return [self._configs[key] for key in sorted(self._configs)]

    def config(self, provider: str) -> ProviderConfig:
        if provider in self._configs:
            return self._configs[provider]
        if provider == "anthropic":
            return ProviderConfig(provider, "anthropic", None, "claude-3-5-haiku-latest")
        if provider == "ccswitch":
            return ProviderConfig(provider, "openai", None, None)
        return ProviderConfig(provider, "openai", None, "gpt-4o-mini")

    @staticmethod
    def _endpoint(base_url: Optional[str], suffix: str, official: str) -> str:
        if not base_url:
            return official
        base = base_url.rstrip("/")
        if base.endswith("/" + suffix) or base.endswith(suffix):
            return base
        if base.endswith("/v1"):
            return base + "/" + suffix
        return base + "/v1/" + suffix

    def provider(self, name: str, model: Optional[str] = None, protocol: Optional[str] = None, base_url: Optional[str] = None) -> ModelProvider:
        config = self.config(name)
        protocol = protocol or config.protocol
        base_url = base_url if base_url is not None else config.base_url
        selected_model = model or config.model
        key = self.key_store.get(name) or ""
        if not key and name != "ccswitch":
            raise ProviderError("No API key configured for %s" % name)
        if protocol == "openai":
            return OpenAIProvider(key or "ccswitch", selected_model or "gpt-4o-mini", self._endpoint(base_url, "chat/completions", "https://api.openai.com/v1/chat/completions"), name)
        if protocol == "anthropic":
            return AnthropicProvider(key or "ccswitch", selected_model or "claude-3-5-haiku-latest", self._endpoint(base_url, "messages", "https://api.anthropic.com/v1/messages"), name)
        raise ProviderError("Unsupported protocol: %s" % protocol)
