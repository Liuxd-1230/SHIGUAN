"""FakeLlmProvider —— 确定性脚本化提供者（测试 / CI / 演示）。

CI 禁止访问真实模型服务，全部用 FakeLlmProvider。可模拟：
  - 正常 JSON（含 code fence / 前后解释文字）
  - 非法 JSON
  - 超时
  - 服务不可达
  - 远程被禁用
  - 重试后成功（脚本按次消费，前 N 次失败后成功）
  - 始终失败
"""
from __future__ import annotations

from typing import Optional

from .base import (
    ProviderError,
    ProviderHealth,
    ProviderOutputError,
    ProviderTimeoutError,
    ProviderUnreachableError,
)
from .openai_compatible import _extract_json


class FakeLlmProvider:
    """按脚本（列表）逐次消费的 Fake Provider。

    script 元素（每次 generate_json 弹出一个）：
      - {"json": {...}}            → 直接返回该 dict
      - {"raw": "```json\\n{...}```"} → 经 _extract_json 解析后返回
      - {"invalid_json": "not json"} → 抛 ProviderOutputError
      - {"timeout": True}          → 抛 ProviderTimeoutError
      - {"unreachable": True}      → 抛 ProviderUnreachableError
      - {"error": "..."}           → 抛 ProviderError
    script 耗尽后：按 `fallback`（默认 {"error": "fake script exhausted"}）。
    """

    def __init__(
        self,
        script: Optional[list] = None,
        *,
        name: str = "fake",
        local: bool = True,
        reachable: bool = True,
        model: Optional[str] = None,
    ):
        self._script: list = list(script or [])
        self._name = name
        self._local = local
        self._reachable = reachable
        self._model = model
        self.calls: list[dict] = []

    def name(self) -> str:
        return self._name

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            configured=True,
            provider=self._name,
            baseUrlRedacted=None,
            model=self._model,
            local=self._local,
            reachable=self._reachable,
        )

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema": schema,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if not self._script:
            raise ProviderError("fake script exhausted")
        step = self._script.pop(0)
        if "json" in step:
            return step["json"]
        if "raw" in step:
            return _extract_json(step["raw"])
        if "invalid_json" in step:
            raise ProviderOutputError(step.get("message", "fake invalid json"))
        if step.get("timeout"):
            raise ProviderTimeoutError("fake timeout")
        if step.get("unreachable"):
            raise ProviderUnreachableError("fake unreachable")
        if "error" in step:
            raise ProviderError(str(step["error"]))
        raise ProviderError(f"unknown fake step: {step!r}")
