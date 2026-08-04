"""biography-engine（Phase 3A）—— 模型提供者 + 确定性压缩 + 传记提纲生成。

职责边界（不得混淆）：
  - 这里只负责把 CharacterProfile 压缩成 CompressedProfile、调用 Provider 生成
    BiographyOutline 并校验；**不生成最终正文**（Phase 3B）。
  - 事实只来自存档（经压缩档案），模型不得自行添加事实；unresolved 数字名
    不进入自然语言摘要。
"""
from .compressor import compress_profile
from .config import provider_config
from .models import COMPRESSION_VERSION, CompressedEvent, CompressedProfile, CompressedRelative
from .outline_generator import DEFAULT_MAX_REPAIR, OutlineGenerationResult, OutlineGenerator
from .prompt_builder import PROMPT_VERSION
from .validators import validate_outline

__all__ = [
    "COMPRESSION_VERSION",
    "CompressedEvent",
    "CompressedProfile",
    "CompressedRelative",
    "DEFAULT_MAX_REPAIR",
    "OutlineGenerationResult",
    "OutlineGenerator",
    "PROMPT_VERSION",
    "compress_profile",
    "provider_config",
    "validate_outline",
]
