"""正文生成编排（Phase 3B 第 7 步）—— 逐章生成 + FactChecker + 有限修复。

每章独立一次模型调用：只传该章允许的事件（`build_chapter_prompts` 过滤）。
对每章先做结构校验（id / eventIds 白名单），再跑确定性 FactChecker；
存在问题且未耗尽重试 → 只重传该章（至多 `DEFAULT_MAX_CHAPTER_REPAIR` 次）；
重试耗尽仍存在问题 → **仍产出 Biography 但 factCheck.status = needs_revision**
（保存层按 needs_revision 落库，绝不伪装成功）。

Provider 级错误（不可达 / 超时 / 未配置）→ 直接失败返回，不产出半成品。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import ValidationError

from models import (
    Biography,
    BiographyChapter,
    BiographyChapterOutline,
    BiographyOutline,
    CharacterProfile,
    FactCheckIssue,
    FactCheckResult,
    FactCheckStatus,
)

from .chapter_prompts import (
    CHAPTER_JSON_SCHEMA,
    build_chapter_prompts,
    build_chapter_repair_prompt,
)
from .compressor import compress_profile
from .fact_checker import FactChecker
from .models import CompressedEvent, CompressedProfile
from .outline_generator import _first_validation_error
from .providers.base import (
    LlmProvider,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderOutputError,
)

# 每章修复重试上限（原始 1 次 + 至多 N 次修复请求）。
DEFAULT_MAX_CHAPTER_REPAIR = 2


@dataclass
class BiographyGenerationResult:
    biography: Optional[Biography] = None
    compressed: Optional[CompressedProfile] = None
    valid: bool = False
    retryCount: int = 0
    warnings: List[str] = field(default_factory=list)
    errorCode: Optional[str] = None
    errorMessage: Optional[str] = None
    factCheck: Optional[FactCheckResult] = None


class BiographyGenerator:
    """在给定 LlmProvider 之上逐章生成传记正文。"""

    def __init__(self, provider: Optional[LlmProvider] = None, max_repair: int = DEFAULT_MAX_CHAPTER_REPAIR):
        self.provider = provider
        self.max_repair = max_repair

    # -- 生成 ---------------------------------------------------------------
    def generate(
        self,
        profile: CharacterProfile,
        outline: BiographyOutline,
        *,
        include_inferred: bool = True,
        include_uncertain: bool = True,
        max_events: int = 200,
        profile_digest: Optional[str] = None,
        on_progress=None,
        is_cancelled=None,
    ) -> BiographyGenerationResult:
        """逐章生成正文。

        `on_progress(completed, total)`：每完成一章回调一次（供异步任务进度 UI）。
        `is_cancelled() -> bool`：每次生成前检查，True 则中止（返回 errorCode="cancelled"）。
        """
        # 1) 确定性压缩（与提纲生成同源；校验提纲事件全部仍在压缩选择内）。
        compressed = compress_profile(
            profile,
            max_events=max_events,
            include_inferred=include_inferred,
            include_uncertain=include_uncertain,
        )
        event_by_id = {e.eventId: e for e in compressed.selectedEvents}
        missing = [
            eid
            for c in outline.chapters
            for eid in c.eventIds
            if eid not in event_by_id
        ]
        if missing:
            return BiographyGenerationResult(
                compressed=compressed,
                valid=False,
                errorCode="outline_event_missing",
                errorMessage=(
                    f"提纲引用了当前压缩档案之外的事件：{sorted(set(missing))[:5]}"
                    "。请以相同压缩设置重新生成提纲。"
                ),
            )

        # 2) 逐章生成。
        chapters_out: List[BiographyChapter] = []
        all_issues: List[FactCheckIssue] = []
        retry_count = 0
        total = len(outline.chapters)
        for idx, ch_outline in enumerate(outline.chapters, start=1):
            if is_cancelled is not None and is_cancelled():
                return BiographyGenerationResult(
                    compressed=compressed,
                    valid=False,
                    retryCount=retry_count,
                    errorCode="cancelled",
                    errorMessage="正文生成已取消。",
                )
            ch, retries, err, issues = self._generate_chapter(
                profile, compressed, outline, ch_outline
            )
            retry_count += retries
            if err is not None:
                return BiographyGenerationResult(
                    compressed=compressed,
                    valid=False,
                    retryCount=retry_count,
                    errorCode=err.code,
                    errorMessage=err.message,
                )
            assert ch is not None
            chapters_out.append(ch)
            all_issues.extend(issues)
            if on_progress is not None:
                on_progress(idx, total)

        # 3) 汇总 FactCheck（重试耗尽仍有问题的章节 → needs_revision）。
        if all_issues:
            fact_check = FactCheckResult(
                status=FactCheckStatus.NEEDS_REVISION, issues=all_issues
            )
        else:
            fact_check = FactCheckResult(status=FactCheckStatus.PASS, issues=[])

        biography = Biography(
            profileId=profile.id,
            style=outline.style,
            chapters=chapters_out,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            modelName=getattr(self.provider, "model", None) or "unknown",
            factCheck=fact_check,
            profileDigest=profile_digest,
        )
        return BiographyGenerationResult(
            biography=biography,
            compressed=compressed,
            valid=fact_check.status == FactCheckStatus.PASS,
            retryCount=retry_count,
            warnings=compressed.warnings,
            factCheck=fact_check,
        )

    # -- 内部 ---------------------------------------------------------------
    def _generate_chapter(
        self,
        profile: CharacterProfile,
        compressed: CompressedProfile,
        outline: BiographyOutline,
        ch_outline: BiographyChapterOutline,
    ) -> tuple[Optional[BiographyChapter], int, Optional[ProviderError], List[FactCheckIssue]]:
        """生成单个章节。返回 (chapter, retry_count, error, issues)。

        重试耗尽仍有 FactCheck 问题：返回该章正文 + 问题列表（不伪装成功），
        由调用方汇总为 needs_revision；Provider 级错误直接返回 error。
        """
        allowed = set(ch_outline.eventIds)
        system_prompt, user_prompt = build_chapter_prompts(
            compressed, ch_outline, outline.style
        )
        mini_outline = BiographyOutline(
            profileId=outline.profileId, style=outline.style, chapters=[ch_outline]
        )
        checker = FactChecker()

        current_prompt = user_prompt
        retry = 0
        while True:
            data, err = self._call_provider(system_prompt, current_prompt)
            if err is not None:
                if isinstance(err, ProviderOutputError) and retry < self.max_repair:
                    retry += 1
                    current_prompt = build_chapter_repair_prompt(user_prompt, [err.message])
                    continue
                return None, retry, err, []

            ch, errs = self._parse_chapter(data, ch_outline, allowed)
            if ch is None:
                if errs and retry < self.max_repair:
                    retry += 1
                    current_prompt = build_chapter_repair_prompt(user_prompt, errs)
                    continue
                return None, retry, ProviderError("；".join(errs[:3])), []

            # 确定性 FactCheck（本章子集 + 单章提纲）。
            fc = checker.check(
                chapters=[ch],
                outline=mini_outline,
                compressed=compressed,
                profile=profile,
            )
            if fc.status == FactCheckStatus.PASS:
                return ch, retry, None, []
            if retry < self.max_repair:
                retry += 1
                current_prompt = build_chapter_repair_prompt(
                    user_prompt, [i.message for i in fc.issues]
                )
                continue
            # 重试耗尽：保留正文，问题交给调用方汇总（needs_revision）。
            return ch, retry, None, fc.issues

    def _call_provider(self, system_prompt: str, user_prompt: str):
        """调用 provider 返回 (data, error)。provider 未配置 → 结构化错误。"""
        if self.provider is None:
            return None, ProviderNotConfiguredError()
        try:
            data = self.provider.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=CHAPTER_JSON_SCHEMA,
                temperature=0.4,
                max_tokens=2048,
            )
            return data, None
        except ProviderError as e:
            return None, e

    def _parse_chapter(self, data, ch_outline: BiographyChapterOutline, allowed: set):
        """把模型 dict 解析为 BiographyChapter 并通过本章白名单校验。"""
        if not isinstance(data, dict):
            return None, ["模型输出不是 JSON 对象。"]
        try:
            ch = BiographyChapter.model_validate(data)
        except ValidationError as e:
            return None, [f"章节不符合契约：{_first_validation_error(e)}"]
        errs: List[str] = []
        if ch.id != ch_outline.id:
            errs.append(f"章节 id 与提纲不符：期望 {ch_outline.id}，得到 {ch.id}。")
        for eid in ch.eventIds:
            if eid not in allowed:
                errs.append(f"章节引用了不在本章允许列表的事件 id：{eid}")
        if errs:
            return None, errs
        return ch, []
