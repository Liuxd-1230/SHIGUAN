"""CharacterExtractor 单测：reader stub → save-schema 契约映射（含本地化解析）。"""
from app.services.character_extractor import to_profile, to_summary
from app.services.localization import LocalizationLoader


def _stub():
    return {
        "id": "6432",
        "name": "Hua_83EF",
        "birth": "726.1.1",
        "death": None,
        "alive": True,
        "culture": "asian_han_chinese",
        "faith": "41",
        "dynasty": "9067",
        "evidence_warnings": ["faith", "dynasty", "primary_title"],
    }


def _loader_with_culture() -> LocalizationLoader:
    loader = LocalizationLoader()
    # 直接注入，模拟已加载的简中本地化
    loader._data["zh-Hans"] = {"asian_han_chinese": "汉文化"}
    loader._data["en"] = {"asian_han_chinese": "Han Chinese"}
    return loader


def test_to_summary_no_loader():
    s = to_summary(_stub())
    assert s.id == "6432"
    assert s.name == "Hua_83EF"
    assert s.culture.id == "asian_han_chinese"
    assert s.culture.resolved is False  # 无 loader，保留原键
    assert s.faith.id == "41"  # token-id，未解析
    assert s.faith.resolved is False
    assert s.dynasty.id == "9067"
    assert s.isAlive is True


def test_to_summary_with_loader_resolves_culture():
    s = to_summary(_stub(), _loader_with_culture())
    assert s.culture.name == "汉文化"
    assert s.culture.resolved is True
    # 名称键未在 loader 中 → 保留原键，不伪造
    assert s.name == "Hua_83EF"
    # faith/dynasty 仍是 token-id，无法本地化
    assert s.faith.resolved is False
    assert s.dynasty.resolved is False


def test_to_summary_dead():
    stub = _stub()
    stub["alive"] = False
    stub["death"] = "800.1.1"
    s = to_summary(stub)
    assert s.isAlive is False
    assert s.deathDate == "800.1.1"


def test_to_profile_partial():
    p = to_profile(_stub(), _loader_with_culture())
    assert p.id == "6432"
    assert p.culture.name == "汉文化"
    # 无法解析的字段保持为空，绝不伪造
    assert p.traits == []
    assert p.titles == []
    assert p.spouses == []
    # 最小可信内容（Phase 2A.1 十一）：至少包含可确认的出生事件，且带证据；
    # 未解析字段（faith/dynasty/primary_title）以 EvidenceWarning 标记，不伪造。
    assert len(p.timeline) == 1
    assert p.timeline[0].type.value == "birth"
    assert p.timeline[0].evidence
    assert any(w.code == "unresolved_faith" for w in p.evidenceWarnings)
    assert any(w.code == "unresolved_dynasty" for w in p.evidenceWarnings)
    assert any(w.code == "unresolved_primary_title" for w in p.evidenceWarnings)
