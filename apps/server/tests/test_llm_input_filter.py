"""LLM 输入过滤（M5.1 4.3）：unresolved 数字人物名不得进入自然语言摘要。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from models import CharacterRef

from app.services.llm_input_filter import (
    sanitize_character_ref_for_llm,
    sanitize_character_refs_for_llm,
)


def test_resolved_ref_kept():
    ref = CharacterRef(id="9536", name="毛里齐奥", resolved=True)
    assert sanitize_character_ref_for_llm(ref) == "毛里齐奥"


def test_unresolved_digit_name_filtered():
    """resolved=false 且 name 是纯数字 → 不写入自然语言摘要（保留 id 内部追踪）。"""
    ref = CharacterRef(id="9536", name="9536", resolved=False)
    assert sanitize_character_ref_for_llm(ref) is None


def test_unresolved_missing_resolved_flag_filtered():
    """resolved 缺失（旧数据，None）且 name 是数字 → 同样保守过滤。"""
    ref = CharacterRef(id="9536", name="9536")
    assert sanitize_character_ref_for_llm(ref) is None


def test_internal_key_name_kept():
    """非数字内部 key（如 loc key）不算数字占位，原样返回（不编造不删除）。"""
    ref = CharacterRef(id="117825", name="max_chinese_male_name_117825", resolved=False)
    assert sanitize_character_ref_for_llm(ref) == "max_chinese_male_name_117825"


def test_dict_input_supported():
    assert sanitize_character_ref_for_llm({"id": "9", "name": "理古", "resolved": True}) == "理古"
    assert sanitize_character_ref_for_llm({"id": "9", "name": "9", "resolved": False}) is None


def test_none_and_empty():
    assert sanitize_character_ref_for_llm(None) is None
    assert sanitize_character_ref_for_llm({"id": "9", "name": ""}) is None


def test_batch_filter_order():
    refs = [
        CharacterRef(id="1", name="华", resolved=True),
        CharacterRef(id="2", name="2", resolved=False),
        CharacterRef(id="3", name="仲容", resolved=True),
    ]
    assert sanitize_character_refs_for_llm(refs) == ["华", "仲容"]
