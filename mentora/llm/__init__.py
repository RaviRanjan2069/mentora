"""Provider-agnostic LLM client with hosted, local and fake back-ends."""

from mentora.llm.client import LLMClient, make_client
from mentora.llm.prompts import PromptRegistry, RenderedPrompt, default_registry

__all__ = ["LLMClient", "PromptRegistry", "RenderedPrompt", "default_registry", "make_client"]
