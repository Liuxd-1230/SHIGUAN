"""Provider 层测试（Phase 3A 5.2/5.3/5.12）：
本地/远程判定、远程禁用、API Key 不泄露、健康检查、超时、HTTP 错误、非 JSON、code fence。
"""
import pytest

from biography_engine.providers.base import (
    ProviderError,
    ProviderOutputError,
    ProviderTimeoutError,
    ProviderUnreachableError,
    RemoteProviderDisabledError,
)
from biography_engine.providers.fake import FakeLlmProvider
from biography_engine.providers.openai_compatible import (
    OpenAICompatibleProvider,
    _extract_json,
    is_local_url,
    redact_base_url,
)


def test_local_url_detection():
    assert is_local_url("http://127.0.0.1:8080/v1") is True
    assert is_local_url("http://localhost:11434/v1") is True
    assert is_local_url("http://[::1]:8080/v1") is True
    assert is_local_url("https://api.openai.com/v1") is False
    assert is_local_url("http://192.168.1.5:8080/v1") is False


def test_remote_provider_disabled_by_default():
    p = OpenAICompatibleProvider(base_url="https://api.openai.com/v1")
    with pytest.raises(RemoteProviderDisabledError):
        p.generate_json(
            system_prompt="s", user_prompt="u", schema={}, temperature=0.3, max_tokens=10
        )


def test_remote_allowed_only_when_flagged():
    p = OpenAICompatibleProvider(base_url="http://192.168.1.5:8080/v1", allow_remote=True)
    assert p.local is False
    # 不真正发起请求：只验证远程判定与 health 不泄露密钥。
    h = p.health()
    assert "key" not in str(h.to_dict()).lower()
    assert "api" not in str(h.to_dict()).lower() or h.api_key is None


def test_base_url_redacted():
    assert redact_base_url("https://api.openai.com/v1") == "https://api.openai.com"
    r = OpenAICompatibleProvider(base_url="https://api.openai.com/v1").health()
    assert r.baseUrlRedacted == "https://api.openai.com"
    assert "/v1" not in (r.baseUrlRedacted or "")


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_fence_and_text():
    raw = '好的，以下是提纲：\n```json\n{"profileId": "x", "style": "vernacular_annals", "chapters": []}\n```\n希望有用。'
    out = _extract_json(raw)
    assert out["profileId"] == "x"


def test_extract_json_invalid_raises():
    with pytest.raises(ProviderOutputError):
        _extract_json("不是 JSON")


def test_extract_json_empty_raises():
    with pytest.raises(ProviderOutputError):
        _extract_json("")


def test_fake_provider_scripted():
    p = FakeLlmProvider(
        script=[
            {"json": {"ok": 1}},
            {"raw": '```json\n{"ok": 2}\n```'},
            {"invalid_json": "oops"},
            {"timeout": True},
            {"unreachable": True},
            {"error": "boom"},
        ]
    )
    assert p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1) == {"ok": 1}
    assert p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1) == {"ok": 2}
    with pytest.raises(ProviderOutputError):
        p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1)
    with pytest.raises(ProviderTimeoutError):
        p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1)
    with pytest.raises(ProviderUnreachableError):
        p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1)
    with pytest.raises(ProviderError):
        p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1)
    # script 耗尽 → ProviderError
    with pytest.raises(ProviderError):
        p.generate_json(system_prompt="s", user_prompt="u", schema={}, temperature=0, max_tokens=1)


def test_fake_health_no_secrets():
    p = FakeLlmProvider(model="local-model")
    h = p.health().to_dict()
    assert h["configured"] is True
    assert h["reachable"] is True
    assert h["model"] == "local-model"
    assert h["local"] is True
