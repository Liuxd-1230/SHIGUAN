"""LLM Provider 健康检查 API（Phase 3A 5.3）。

  GET /api/llm/health —— 只返回脱敏状态（configured/provider/baseUrlRedacted/model/
  local/reachable/errorCode/message）。绝不返回 API Key / 完整 Prompt / 原始存档内容。
"""
from __future__ import annotations

from fastapi import APIRouter

from biography_engine.config import load_llm_config, provider_config
from biography_engine.providers.base import ProviderNotConfiguredError
from biography_engine.providers.factory import build_provider

router = APIRouter()


@router.get("/llm/health")
def llm_health_endpoint():
    """模型提供者健康状态（探测本地服务可达性，不阻塞主流程）。"""
    cfg = load_llm_config()
    c = provider_config(cfg)
    name = c["provider"]
    try:
        provider = build_provider(cfg)
    except ProviderNotConfiguredError as exc:
        return {
            "configured": False,
            "provider": name,
            "baseUrlRedacted": None,
            "model": None,
            "local": False,
            "reachable": False,
            "errorCode": exc.code,
            "message": exc.message,
        }
    return provider.health().to_dict()
