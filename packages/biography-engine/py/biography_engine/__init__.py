"""biography-engine（Phase 3A + 3B）—— 模型提供者 + 确定性压缩 + 提纲 + 正文生成。

职责边界（不得混淆）：
  - 确定性层：把 CharacterProfile 压缩成 CompressedProfile、校验提纲、校验正文事实。
  - 生成层：调用 Provider 生成 BiographyOutline（3A）与逐章 Biography（3B）并有限修复。
  - 事实只来自存档（经压缩档案），模型不得自行添加事实；unresolved 数字名
    不进入自然语言摘要。
"""
from .biography_generator import (
    DEFAULT_MAX_CHAPTER_REPAIR,
    BiographyGenerationResult,
    BiographyGenerator,
)
from .chapter_prompts import CHAPTER_PROMPT_VERSION
from .compressor import compress_profile
from .config import provider_config
from .fact_checker import FactChecker, check_biography
from .models import COMPRESSION_VERSION, CompressedEvent, CompressedProfile, CompressedRelative
from .outline_generator import DEFAULT_MAX_REPAIR, OutlineGenerationResult, OutlineGenerator
from .prompt_builder import PROMPT_VERSION
from .validators import validate_outline

__all__ = [
    "BiographyGenerationResult",
    "BiographyGenerator",
    "CHAPTER_PROMPT_VERSION",
    "COMPRESSION_VERSION",
    "CompressedEvent",
    "CompressedProfile",
    "CompressedRelative",
    "DEFAULT_MAX_CHAPTER_REPAIR",
    "DEFAULT_MAX_REPAIR",
    "FactChecker",
    "OutlineGenerationResult",
    "OutlineGenerator",
    "PROMPT_VERSION",
    "check_biography",
    "compress_profile",
    "provider_config",
    "validate_outline",
]
