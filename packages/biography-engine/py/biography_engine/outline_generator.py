"""提纲生成编排（Phase 3A 5.7/5.8）—— 压缩 → Prompt → Provider → 校验 → 有限修复重试。

不把非法结果保存成成功传记；重试有上限（原始 1 次 + 修复 N 次），绝不无限重试。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import ValidationError

from models import BiographyOutline, BiographyStyle, CharacterProfile

from .compressor import compress_profile
from .models import CompressedProfile
from .prompt_builder import OUTLINE_JSON_SCHEMA, build_outline_prompts, build_repair_prompt
from .providers.base import ProviderError, ProviderNotConfiguredError, ProviderOutputError
from .providers.base import LlmProvider
from .validators import validate_outline

# 修复重试上限（原始生成 1 次 + 至多 N 次修复请求）。
DEFAULT_MAX_REPAIR = 1


@dataclass
class OutlineGenerationResult:
    outline: Optional[BiographyOutline] = None
    compressed: Optional[CompressedProfile] = None
    valid: bool = False
    retryCount: int = 0
    warnings: List[str] = field(default_factory=list)
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None


class OutlineGenerator:
    """在给定 LlmProvider 之上执行提纲生成流程。"""

    def __init__(self, provider: Optional[LlmProvider] = None, max_repair: int = DEFAULT_MAX_REPAIR):
        self.provider = provider
        self.max_repair = max_repair

    # -- 生成 ---------------------------------------------------------------
    def generate(
        self,
        profile: CharacterProfile,
        *,
        style: BiographyStyle,
        include_inferred: bool,
        include_uncertain: bool,
        max_events: int,
    ) -> OutlineGenerationResult:
        # 1) 确定性压缩（绝不让模型直接接收 CharacterProfile）。
        compressed = compress_profile(
            profile,
            max_events=max_events,
            include_inferred=include_inferred,
            include_uncertain=include_uncertain,
        )
        if not compressed.selectedEvents:
            return OutlineGenerationResult(
                compressed=compressed,
                valid=False,
                errorCode="insufficient_timeline",
                errorMessage="人物时间线为空或被过滤后无可用事件，无法生成提纲。",
            )

        # 2) 构建 Prompt（只含压缩档案 + style + schema）。
        system_prompt, user_prompt = build_outline_prompts(compressed, style)
        allowed = compressed.sourceEventIds

        # 3) 原始生成 + 有限修复重试。
        # 可修复的情形：输出解析失败（ProviderOutputError）或校验失败（errs 非空）。
        # 终态：其他 Provider 级错误（超时 / 不可达 / 未配置等）→ 直接返回。
        current_prompt = user_prompt
        retry = 0
        while True:
            data, err = self._call_provider(system_prompt, current_prompt)
            if err is not None:
                if (
                    isinstance(err, ProviderOutputError)
                    and retry < self.max_repair
                ):
                    retry += 1
                    current_prompt = build_repair_prompt(user_prompt, [err.message])
                    continue
                return self._err_result(compressed, err)

            outline, errs = self._parse_and_validate(data, allowed, compressed)
            if outline is not None:
                break
            if errs and retry < self.max_repair:
                retry += 1
                current_prompt = build_repair_prompt(user_prompt, errs)
                continue
            break

        if outline is None:
            return OutlineGenerationResult(
                compressed=compressed,
                valid=False,
                retryCount=retry,
                errorCode=_last_error_code(errs),
                errorMessage=_last_error_message(errs),
            )
        return OutlineGenerationResult(
            outline=outline,
            compressed=compressed,
            valid=True,
            retryCount=retry,
            warnings=compressed.warnings,
        )

    # -- 内部 ---------------------------------------------------------------
    def _call_provider(self, system_prompt: str, user_prompt: str):
        """调用 provider 返回 (data, error)。provider 未配置 → 结构化错误。"""
        if self.provider is None:
            return None, ProviderNotConfiguredError()
        try:
            data = self.provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=OUTLINE_JSON_SCHEMA,
                temperature=0.3,
                max_tokens=4096,
            )
            return data, None
        except ProviderError as e:
            return None, e

    def _parse_and_validate(self, data, allowed, compressed):
        """把模型 dict 解析为 BiographyOutline 并通过白名单校验。"""
        if not isinstance(data, dict):
            return None, ["模型输出不是 JSON 对象。"]
        try:
            outline = BiographyOutline.model_validate(data)
        except ValidationError as e:
            first = _first_validation_error(e)
            return None, [f"提纲不符合契约：{first}"]
        errs = validate_outline(outline, allowed, compressed)
        if errs:
            return None, errs
        return outline, []

    @staticmethod
    def _err_result(compressed, err: ProviderError) -> OutlineGenerationResult:
        return OutlineGenerationResult(
            compressed=compressed,
            valid=False,
            errorCode=err.code,
            errorMessage=err.message,
        )


def _first_validation_error(e: ValidationError) -> str:
    try:
        err = e.errors()[0]
        loc = ".".join(str(x) for x in err.get("loc", []))
        return f"{loc}: {err.get('msg', '')}"
    except Exception:  # noqa: BLE001
        return str(e)


def _last_error_code(errs: List[str]) -> str:
    if any("不存在" in s or "事件 id" in s for s in errs):
        return "invalid_event_reference"
    return "invalid_model_output"


def _last_error_message(errs: List[str]) -> str:
    return "；".join(errs[:3]) if errs else "模型输出未通过校验。"
