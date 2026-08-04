"""Provider 工厂 —— 按配置构造 LlmProvider（server / 测试共用）。"""
from __future__ import annotations

from typing import Optional

from ..config import provider_config
from .base import ProviderNotConfiguredError
from .fake import FakeLlmProvider
from .openai_compatible import OpenAICompatibleProvider


def build_provider(cfg: Optional[dict] = None):
    """按配置构造 provider。未知 provider 名 → ProviderNotConfiguredError。"""
    c = provider_config(cfg)
    name = c["provider"]
    if name == "fake":
        return FakeLlmProvider()
    if name == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=c["base_url"],
            api_key=c["api_key"],
            model=c["model"],
            timeout_seconds=c["timeout_seconds"],
            allow_remote=c["allow_remote"],
        )
    raise ProviderNotConfiguredError(f"未知 LLM_PROVIDER：{name}")
