"""OpenAICompatibleProvider —— 调用 /v1/chat/completions 兼容接口。

支持的本地服务（默认配置即本地，不得默认调用远程 OpenAI）：
  - llama.cpp server
  - LM Studio
  - Ollama 的 OpenAI-compatible API（/v1/chat/completions）
  - OpenAI 官方兼容接口（需显式 LLM_ALLOW_REMOTE=true）

安全：
  - 远程地址（非 localhost / 127.0.0.1 / ::1）在 LLM_ALLOW_REMOTE=false 时直接拒绝；
  - API Key 只来自环境变量/本地配置，不写日志、不返回普通响应；
  - 日志/异常不携带完整 prompt 与密钥。
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .base import (
    LlmProvider,
    ProviderHealth,
    ProviderOutputError,
    ProviderTimeoutError,
    ProviderUnreachableError,
    RemoteProviderDisabledError,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", ""}


def is_local_url(base_url: str) -> bool:
    """localhost / 127.0.0.1 / ::1（或无主机）视为本地；其余视为远程。"""
    try:
        host = urllib.parse.urlparse(base_url).hostname or ""
    except ValueError:
        return False
    return host.lower() in _LOCAL_HOSTS


def _extract_json(text: str) -> dict:
    """从模型输出中提取 JSON dict：容忍 markdown code fence 与前后解释文字。

    解析失败抛 ProviderOutputError（由上层做修复重试）。
    """
    if not text:
        raise ProviderOutputError("模型返回空内容。")
    t = text.strip()
    # 剥离 ```json ... ``` code fence
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip()
    # 截取首个 { 到末个 }（容忍前后解释文字）
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end < start:
        raise ProviderOutputError("模型输出中找不到 JSON 对象。")
    t = t[start : end + 1]
    try:
        data = json.loads(t)
    except json.JSONDecodeError as e:
        raise ProviderOutputError(f"JSON 解析失败：{e.msg}") from e
    if not isinstance(data, dict):
        raise ProviderOutputError("JSON 顶层不是对象。")
    return data


def redact_base_url(base_url: str) -> str:
    """脱敏 base_url：只保留 scheme://host:port，去掉路径中的任何凭证/查询。"""
    try:
        p = urllib.parse.urlsplit(base_url)
        return f"{p.scheme}://{p.netloc}"
    except ValueError:
        return "<invalid-url>"


class OpenAICompatibleProvider:
    """调用 {base_url}/chat/completions 的兼容实现。"""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080/v1",
        api_key: str = "",
        model: str = "",
        timeout_seconds: float = 120,
        allow_remote: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.allow_remote = allow_remote
        self.local = is_local_url(self.base_url)

    def name(self) -> str:
        return "openai_compatible"

    def _endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _check_remote_allowed(self) -> None:
        if not self.local and not self.allow_remote:
            raise RemoteProviderDisabledError(
                f"远程模型地址 {redact_base_url(self.base_url)} 被禁用："
                "请设置 LLM_ALLOW_REMOTE=true 并确认数据发送范围。"
            )

    def health(self) -> ProviderHealth:
        h = ProviderHealth(
            configured=True,
            provider=self.name(),
            baseUrlRedacted=redact_base_url(self.base_url),
            model=self.model or None,
            local=self.local,
            reachable=False,
        )
        try:
            self._check_remote_allowed()
        except RemoteProviderDisabledError as e:
            h.errorCode = e.code
            h.message = e.message
            return h
        try:
            self._post_minimal()
            h.reachable = True
        except ProviderTimeoutError as e:
            h.errorCode = e.code
            h.message = e.message
        except ProviderUnreachableError as e:
            h.errorCode = e.code
            h.message = e.message
        except ProviderOutputError as e:
            h.reachable = True  # 服务可达但响应不符合预期
            h.message = e.message
        return h

    def _post_minimal(self) -> None:
        """健康检查：发送一个最小 chat 请求确认服务可达。"""
        self._raw_post(
            {
                "model": self.model or "unused",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            }
        )

    def _raw_post(self, payload: dict) -> str:
        self._check_remote_allowed()
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint(),
            data=body,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise ProviderUnreachableError(f"模型服务返回 HTTP {e.code}。") from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", None)
            if isinstance(reason, TimeoutError):
                raise ProviderTimeoutError() from e
            raise ProviderUnreachableError(
                f"无法连接模型服务：{getattr(reason, 'strerror', None) or reason or e}"
            ) from e
        except http.client.HTTPException as e:
            # 服务器在响应完成前断开连接（RemoteDisconnected / BadStatusLine 等），
            # 不是 URLError 子类，必须显式包装为不可达，否则 health() 会裸抛。
            raise ProviderUnreachableError(
                f"连接模型服务时连接被断开：{e}"
            ) from e
        except TimeoutError as e:
            raise ProviderTimeoutError() from e

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        payload = {
            "model": self.model or "unused",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # 部分兼容服务支持 json_object；不支持时服务会忽略或报错，我们只在
        # 已启用 remote 或本地服务上尝试，失败不影响主流程。
        raw = self._raw_post(payload)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderOutputError(f"服务响应非 JSON：{e.msg}") from e
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderOutputError("服务响应缺少 choices[0].message.content。") from e
        return _extract_json(content)
