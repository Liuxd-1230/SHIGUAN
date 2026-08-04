"""LlmProvider 抽象 —— 统一模型提供者接口（Phase 3A 5.2）。

所有传记生成只依赖 `LlmProvider` 协议（health / generate_json），
不直接接触具体服务（llama.cpp / LM Studio / Ollama / OpenAI 兼容）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Provider 错误：结构化的、可映射到 API 错误码的异常
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Provider 层错误的基类。"""

    code = "provider_error"
    default_message = "模型提供者错误。"

    def __init__(self, message: Optional[str] = None):
        self.message = message or self.default_message
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}


class ProviderNotConfiguredError(ProviderError):
    code = "provider_not_configured"
    default_message = "未配置模型提供者（LLM_PROVIDER 未设置或无效）。"


class ProviderUnreachableError(ProviderError):
    code = "provider_unreachable"
    default_message = "模型服务不可达，请确认本地模型服务已启动。"


class RemoteProviderDisabledError(ProviderError):
    code = "remote_provider_disabled"
    default_message = (
        "远程模型被禁用：LLM_ALLOW_REMOTE=false 时不允许向非本地地址发送数据。"
    )


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    default_message = "模型请求超时。"


class ProviderOutputError(ProviderError):
    code = "invalid_model_output"
    default_message = "模型输出无法解析为 JSON。"


# ---------------------------------------------------------------------------
# 健康检查与 Provider 协议
# ---------------------------------------------------------------------------


@dataclass
class ProviderHealth:
    """GET /api/llm/health 的返回载体（不含任何密钥）。"""

    configured: bool
    provider: str
    baseUrlRedacted: Optional[str] = None
    model: Optional[str] = None
    local: bool = False
    reachable: bool = False
    errorCode: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "configured": self.configured,
            "provider": self.provider,
            "baseUrlRedacted": self.baseUrlRedacted,
            "model": self.model,
            "local": self.local,
            "reachable": self.reachable,
            "errorCode": self.errorCode,
            "message": self.message,
        }


@runtime_checkable
class LlmProvider(Protocol):
    """统一模型提供者接口。

    `generate_json` 必须返回**已解析的 JSON dict**（内部负责剥离 code fence /
    前后文字）；解析失败抛 `ProviderOutputError`；超时抛 `ProviderTimeoutError`；
    服务不可达抛 `ProviderUnreachableError`；远程被禁抛 `RemoteProviderDisabledError`。
    """

    def name(self) -> str: ...

    def health(self) -> ProviderHealth: ...

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float,
        max_tokens: int,
    ) -> dict: ...
