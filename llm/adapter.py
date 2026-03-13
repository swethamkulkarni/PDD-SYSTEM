"""
LLM Adapter — Pluggable interface for Claude, OpenAI, and Ollama.
Configure via environment variable: LLM_PROVIDER=claude|openai|ollama

Usage:
    from llm.adapter import get_llm
    llm = get_llm()
    response = llm.complete(system_prompt, user_prompt, temperature=0)
"""
import os
import json
import re
from abc import ABC, abstractmethod


class LLMResponse:
    """Standardized response from any LLM provider."""
    def __init__(self, text: str, model: str, provider: str):
        self.text = text
        self.model = model
        self.provider = provider

    def as_json(self) -> dict:
        """Parse response text as JSON. Strips markdown fences if present."""
        text = self.text.strip()
        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)


class BaseLLMAdapter(ABC):
    """Abstract base — all adapters implement this interface."""

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """Send a prompt and return an LLMResponse."""
        pass

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> dict:
        """Convenience method — returns parsed JSON dict."""
        response = self.complete(system_prompt, user_prompt, temperature)
        return response.as_json()


# ── Claude Adapter (Anthropic) ────────────────────────────────────────────────

class ClaudeAdapter(BaseLLMAdapter):
    """
    Anthropic Claude adapter.
    Install: pip install anthropic
    Set: ANTHROPIC_API_KEY=your_key in .env
    For zero data retention: use claude.ai Enterprise or API with no-log endpoint.
    """

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        try:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )
            self.model = model
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")

    def complete(self, system_prompt, user_prompt, temperature=0.0, max_tokens=1000) -> LLMResponse:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return LLMResponse(
            text=message.content[0].text,
            model=self.model,
            provider="claude"
        )


# ── OpenAI Adapter ────────────────────────────────────────────────────────────

class OpenAIAdapter(BaseLLMAdapter):
    """
    OpenAI GPT adapter.
    Install: pip install openai
    Set: OPENAI_API_KEY=your_key in .env
    For zero data retention: use OpenAI Enterprise tier.
    """

    def __init__(self, model: str = "gpt-4o"):
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.model = model
        except ImportError:
            raise ImportError("Install openai: pip install openai")

    def complete(self, system_prompt, user_prompt, temperature=0.0, max_tokens=1000) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return LLMResponse(
            text=response.choices[0].message.content,
            model=self.model,
            provider="openai"
        )


# ── Ollama Adapter (Local — fully air-gapped) ─────────────────────────────────

class OllamaAdapter(BaseLLMAdapter):
    """
    Ollama local model adapter. Zero external network calls.
    Install: https://ollama.ai → then: ollama pull llama3
    Set: OLLAMA_MODEL=llama3 (or mistral, mixtral, etc.)
    Set: OLLAMA_HOST=http://localhost:11434 (default)
    """

    def __init__(self):
        self.model = os.environ.get("OLLAMA_MODEL", "llama3")
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def complete(self, system_prompt, user_prompt, temperature=0.0, max_tokens=1000) -> LLMResponse:
        try:
            import requests
        except ImportError:
            raise ImportError("Install requests: pip install requests")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()

        return LLMResponse(
            text=data["message"]["content"],
            model=self.model,
            provider="ollama"
        )

# ── Groq Adapter (Fast + Free) ────────────────────────────────────────────────

class GroqAdapter(BaseLLMAdapter):
    """
    Groq API — runs LLaMA 3 at very high speed on Groq hardware.
    Free tier: 14,400 requests/day — more than enough for testing.
    Install: pip install groq
    Set: GROQ_API_KEY=your_key in .env
    """
    def __init__(self):
        try:
            from groq import Groq
            self._client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
            self.model = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
        except ImportError:
            raise ImportError("Install groq: pip install groq")

    def complete(self, system_prompt, user_prompt, temperature=0.0, max_tokens=1000) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        return LLMResponse(
            text=response.choices[0].message.content,
            model=self.model,
            provider="groq"
        )
# ── Factory function ──────────────────────────────────────────────────────────

def get_llm(provider: str = None) -> BaseLLMAdapter:
    """
    Get the configured LLM adapter.

    Provider is resolved in this order:
    1. Explicit `provider` argument
    2. LLM_PROVIDER environment variable
    3. Default: claude

    Args:
        provider: "claude" | "openai" | "ollama"

    Returns:
        Configured LLM adapter instance.
    """
    # Load .env if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    provider = (provider or os.environ.get("LLM_PROVIDER", "claude")).lower().strip()

    if provider == "claude":
        adapter = ClaudeAdapter()
        print(f"[LLM] Using Claude ({adapter.model})")
        return adapter

    elif provider == "openai":
        adapter = OpenAIAdapter()
        print(f"[LLM] Using OpenAI ({adapter.model})")
        return adapter
    
    

    elif provider == "ollama":
        adapter = OllamaAdapter()
        print(f"[LLM] Using Ollama (local: {adapter.model}) — fully air-gapped")
        return adapter
    
    elif provider == "groq":
        adapter = GroqAdapter()
        print(f"[LLM] Using Groq (fast: {adapter.model}) — free tier")
        return adapter

    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Valid options: claude, openai, ollama"
        )