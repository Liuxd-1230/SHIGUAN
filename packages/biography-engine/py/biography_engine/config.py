"""LLM Provider 配置（Phase 3A 5.3）。

仅从环境变量 / .env（由 server 的 config._load_dotenv 注入）读取，**不覆盖**已有 .env。
默认配置为本地服务 http://127.0.0.1:8080/v1；远程地址必须显式 LLM_ALLOW_REMOTE=true。

API Key 只在此处读取：不写日志、不返回普通前端响应、不提交 Git。
"""
from __future__ import annotations

import os
from typing import Optional

ENV_PREFIX = "LLM_"

DEFAULTS = {
    "LLM_PROVIDER": "openai_compatible",
    "LLM_BASE_URL": "http://127.0.0.1:8080/v1",
    "LLM_MODEL": "",
    "LLM_API_KEY": "",
    "LLM_TIMEOUT_SECONDS": "120",
    "LLM_TEMPERATURE": "0.3",
    "LLM_MAX_TOKENS": "4096",
    "LLM_ALLOW_REMOTE": "false",
}

# 用于 /api/llm/health 的 baseUrlRedacted —— 只暴露 host:port，绝不暴露路径/密钥。
from .providers.openai_compatible import redact_base_url  # noqa: E402


def load_llm_config() -> dict:
    """读取当前环境中的 LLM 配置（未设置时用默认值）。"""
    cfg: dict = {}
    for key, default in DEFAULTS.items():
        cfg[key] = os.environ.get(key, default)
    return cfg


def provider_config(cfg: Optional[dict] = None) -> dict:
    """规范化 Provider 构造参数（含类型转换，非法值回退默认并标记）。"""
    c = cfg or load_llm_config()
    try:
        timeout = float(c.get("LLM_TIMEOUT_SECONDS", "120"))
    except ValueError:
        timeout = 120.0
    try:
        temperature = float(c.get("LLM_TEMPERATURE", "0.3"))
    except ValueError:
        temperature = 0.3
    try:
        max_tokens = int(c.get("LLM_MAX_TOKENS", "4096"))
    except ValueError:
        max_tokens = 4096
    allow_remote = str(c.get("LLM_ALLOW_REMOTE", "false")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return {
        "provider": (c.get("LLM_PROVIDER") or "openai_compatible").strip(),
        "base_url": (c.get("LLM_BASE_URL") or DEFAULTS["LLM_BASE_URL"]).strip(),
        "api_key": (c.get("LLM_API_KEY") or "").strip(),
        "model": (c.get("LLM_MODEL") or "").strip(),
        "timeout_seconds": timeout,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "allow_remote": allow_remote,
    }
