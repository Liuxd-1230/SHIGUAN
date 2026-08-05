"""Phase 3C.2 头衔语义层测试：分类器 / 规则注册表 / 展示名 / 主要身份。

覆盖验收要点：
  - 领地家族按键前缀 + liege 细分（k_dali 独立→主权，封臣→领地）；
  - 政权机构（e_minister_*）→ realm_institution（Mod 规则层，不污染）；
  - 家族身份（x_nf_*）→ dynasty_identity；
  - 超帝国身份（h_*）→ sovereign_realm_title；
  - tier 不映射爵位：展示名用游戏原生名，headline 无「国王/皇帝」字样；
  - 分层优先级：user overrides > mods（按存档结构签名激活）> generic > base > 启发式；
  - Mod 规则仅在该存档出现对应标题结构时激活（不污染其他环境）。
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from biography_engine.title_semantics import (
    PrimaryIdentityResolver,
    TitleDisplayResolver,
    TitleSemanticClassifier,
    TitleSemanticRuleRegistry,
)
from models import RealmStatus, TitleSemanticType


def _entry(key, tier=None, liege=None, name=None, name_source=None, history=None):
    return {
        "key": key,
        "name": name,
        "name_source": name_source,
        "tier": tier,
        "holder_id": "p1",
        "de_facto_liege_id": liege,
        "history": history or [],
    }


class _Loc:
    """测试用本地化表（duck-typed LocalizationLoader）。"""

    def __init__(self, table):
        self._table = table

    def resolve(self, key):
        return self._table.get(key)


# ---------------------------------------------------------------------------
# 展示名解析
# ---------------------------------------------------------------------------

def test_display_name_save_name_wins():
    loc = _Loc({"k_dali": "大理王国"})
    r = TitleDisplayResolver(loc)
    name, resolved = r.display_name(_entry("k_dali", name="大理", name_source="save"))
    assert name == "大理" and resolved is True


def test_display_name_loc_fallback():
    loc = _Loc({"k_dali": "大理王国"})
    r = TitleDisplayResolver(loc)
    name, resolved = r.display_name(_entry("k_dali"))
    assert name == "大理王国" and resolved is True


def test_display_name_unresolved_falls_back_to_key():
    r = TitleDisplayResolver(None)
    name, resolved = r.display_name(_entry("k_unknown_realm"))
    assert name == "k_unknown_realm" and resolved is False


# ---------------------------------------------------------------------------
# 分类器：领地家族 + liege 细分
# ---------------------------------------------------------------------------

def test_independent_kingdom_is_sovereign():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("k_dali", tier="kingdom", liege=None))
    assert c.semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE
    assert c.confidence.value == "confirmed"
    assert any("liege_adjust:independent" in s for s in c.signals)


def test_vassal_kingdom_is_territorial():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("k_youji", tier="kingdom", liege="k_dali"))
    assert c.semanticType == TitleSemanticType.TERRITORIAL_REALM_TITLE


def test_vassal_county_is_subordinate():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("c_foo", tier="county", liege="k_dali"))
    assert c.semanticType == TitleSemanticType.SUBORDINATE_TERRITORY


def test_independent_county_is_minor_ruler():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("c_foo", tier="county", liege=None))
    assert c.semanticType == TitleSemanticType.TERRITORIAL_REALM_TITLE
    assert any("liege_adjust:independent_minor" in s for s in c.signals)


def test_empire_is_sovereign():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("e_wudai_tang", tier="empire", liege=None))
    assert c.semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE


# ---------------------------------------------------------------------------
# 分类器：机构 / 家族 / 超帝国 / 无地
# ---------------------------------------------------------------------------

def test_minister_title_is_realm_institution():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("e_minister_shizheng", name="政事堂", name_source="save"))
    assert c.semanticType == TitleSemanticType.REALM_INSTITUTION


def test_family_title_is_dynasty_identity():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("x_nf_1486", tier="barony"))
    assert c.semanticType == TitleSemanticType.DYNASTY_IDENTITY


def test_super_empire_is_sovereign():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("h_china", name="唐", name_source="save"))
    assert c.semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE
    # 2C.2：h_* 是游戏自身霸权命名空间（game_concept_hegemony），一律标记霸权。
    assert c.isHegemony is True


def test_normal_empire_is_not_hegemony():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("e_byzantium", name="拜占庭", name_source="save"))
    assert c.semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE
    assert c.isHegemony is False


def test_nomad_camp_is_temporary():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("x_c_nomad_1"))
    assert c.semanticType == TitleSemanticType.TEMPORARY_TITLE


def test_unknown_title_honest_unknown():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("zz_weird_key"))
    assert c.semanticType == TitleSemanticType.UNKNOWN
    assert c.confidence.value == "uncertain"
    assert any("无任何规则" in w for w in c.warnings)


def test_tier_is_technical_never_maps_to_peerage():
    classifier = TitleSemanticClassifier()
    c = classifier.classify(_entry("k_dali", tier="kingdom", liege=None, name="大理", name_source="save"))
    # 展示名是游戏原生名「大理」，绝不是「大理国王」；headline 也由身份解析器保证。
    assert c.displayName == "大理"
    assert "国王" not in c.displayName and "皇帝" not in c.displayName


# ---------------------------------------------------------------------------
# 规则注册表：分层与 Mod 隔离
# ---------------------------------------------------------------------------

def _write(tmp: Path, rel: str, content: str) -> Path:
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _registry_dir(tmp: Path):
    _write(tmp, "base-game.yml", """
version: 1
rules:
  - id: landed_e
    match: { key_re: "^(?!e_minister_)e_" }
    classify: { semantic_type: sovereign_realm_title, confidence: confirmed }
    adjust_by_liege: true
  - id: landed_k
    match: { prefix: "k_" }
    classify: { semantic_type: territorial_realm_title, confidence: confirmed }
    adjust_by_liege: true
""")
    _write(tmp, "generic.yml", """
version: 1
rules:
  - id: generic_x_family
    match: { prefix: "x_nf_" }
    classify: { semantic_type: dynasty_identity, confidence: confirmed }
""")
    _write(tmp, "mods/my-mod.yml", """
meta:
  mods: ["ugc_123456"]
  title_signatures: ["d_special_"]
version: 1
rules:
  - id: special_office
    match: { prefix: "d_special_" }
    classify: { semantic_type: personal_office, confidence: confirmed }
""")
    _write(tmp, "user-overrides.yml", """
version: 1
rules:
  - id: override_e
    match: { prefix: "e_" }
    classify: { semantic_type: special_mod_title, confidence: confirmed }
""")
    return tmp


def test_registry_layers_user_overrides_wins():
    with tempfile.TemporaryDirectory() as d:
        reg = TitleSemanticRuleRegistry(Path(d))
        assert reg.count() == 0  # 空目录安全
    with tempfile.TemporaryDirectory() as d:
        _registry_dir(Path(d))
        reg = TitleSemanticRuleRegistry(Path(d))
        classifier = TitleSemanticClassifier(reg)
        c = classifier.classify(_entry("e_foo", liege=None))
        # user overrides 层优先：e_ 被覆盖为 special_mod_title。
        assert c.semanticType == TitleSemanticType.SPECIAL_MOD_TITLE
        assert c.sourceRule == "user-overrides.yml:override_e"


def test_registry_mod_rules_activate_by_title_signature():
    with tempfile.TemporaryDirectory() as d:
        _registry_dir(Path(d))
        reg = TitleSemanticRuleRegistry(Path(d))
        classifier = TitleSemanticClassifier(reg)
        # 该存档出现 d_special_ 前缀标题 → 激活 my-mod.yml 规则（classify_all 按存档结构签名识别）。
        cls, active = classifier.classify_all([_entry("d_special_office")])
        assert len(active) == 1 and active[0]["file"] == "my-mod.yml"
        assert cls["d_special_office"].semanticType == TitleSemanticType.PERSONAL_OFFICE
        assert cls["d_special_office"].sourceRule == "my-mod.yml:special_office"


def test_registry_mod_rules_do_not_pollute_other_saves():
    with tempfile.TemporaryDirectory() as d:
        _registry_dir(Path(d))
        reg = TitleSemanticRuleRegistry(Path(d))
        classifier = TitleSemanticClassifier(reg)
        # 该存档没有 d_special_ 前缀，也没有对应 mod 标识 → mod 规则不激活。
        cls, active = classifier.classify_all(
            [_entry("d_ordinary_duchy", tier="duchy", liege="k_king")]
        )
        assert active == []
        c = cls["d_ordinary_duchy"]
        assert c.semanticType == TitleSemanticType.TERRITORIAL_REALM_TITLE
        assert c.sourceRule in ("heuristic", "base-game.yml:landed_k")


def test_registry_mod_rules_activate_by_mod_id():
    with tempfile.TemporaryDirectory() as d:
        _registry_dir(Path(d))
        reg = TitleSemanticRuleRegistry(Path(d))
        classifier = TitleSemanticClassifier(reg)
        # 存档声明了 ugc_123456 这个 Mod → my-mod.yml 激活。
        cls, active = classifier.classify_all(
            [_entry("d_special_office"), _entry("e_something", liege=None)],
            active_mod_ids=["mod/ugc_123456.mod"],
        )
        assert len(active) == 1 and active[0]["file"] == "my-mod.yml"
        # d_special_ 由 mod 层命中（user 层无此规则）。
        assert cls["d_special_office"].semanticType == TitleSemanticType.PERSONAL_OFFICE
        assert cls["d_special_office"].sourceRule == "my-mod.yml:special_office"
        # e_ 被 user-overrides.yml 覆盖为 special_mod_title（user 层 > mod 层 > base 层）。
        assert cls["e_something"].semanticType == TitleSemanticType.SPECIAL_MOD_TITLE
        assert cls["e_something"].sourceRule == "user-overrides.yml:override_e"


def test_registry_missing_dir_is_empty_safe():
    reg = TitleSemanticRuleRegistry(Path("no/such/dir/xyz"))
    assert reg.count() == 0
    classifier = TitleSemanticClassifier(reg)
    c = classifier.classify(_entry("k_dali", tier="kingdom", liege=None))
    # 无规则 → 启发式兜底。
    assert c.semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE
    assert c.sourceRule == "heuristic"


def test_corrupt_yaml_skipped():
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "base-game.yml", "not: [valid: yaml:::")
        reg = TitleSemanticRuleRegistry(Path(d))
        assert reg.count() == 0


# ---------------------------------------------------------------------------
# 主要身份解析
# ---------------------------------------------------------------------------

def _classify_save(entries, user=None):
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d), "base-game.yml", """
version: 1
rules:
  - id: landed_e
    match: { key_re: "^(?!e_minister_)e_" }
    classify: { semantic_type: sovereign_realm_title, confidence: confirmed }
    adjust_by_liege: true
  - id: landed_k
    match: { prefix: "k_" }
    classify: { semantic_type: territorial_realm_title, confidence: confirmed }
    adjust_by_liege: true
  - id: landed_d
    match: { prefix: "d_" }
    classify: { semantic_type: territorial_realm_title, confidence: confirmed }
    adjust_by_liege: true
  - id: landed_c
    match: { prefix: "c_" }
    classify: { semantic_type: subordinate_territory, confidence: confirmed }
    adjust_by_liege: true
  - id: landed_b
    match: { prefix: "b_" }
    classify: { semantic_type: subordinate_territory, confidence: confirmed }
    adjust_by_liege: true
""")
        if user:
            _write(Path(d), "user-overrides.yml", user)
        reg = TitleSemanticRuleRegistry(Path(d))
        classifier = TitleSemanticClassifier(reg)
        cls, _ = classifier.classify_all(entries)
        return cls


def test_identity_independent_ruler_dual_kingdoms():
    entries = [
        _entry("k_dali", tier="kingdom", liege=None, name="大理", name_source="save"),
        _entry("k_viet", tier="kingdom", liege=None, name="安南", name_source="save"),
    ]
    cls = _classify_save(entries)
    from models import TitlePeriod

    periods = [
        TitlePeriod(titleId="k_dali", name="大理", tier=None, isCurrent=True),
        TitlePeriod(titleId="k_viet", name="安南", tier=None, isCurrent=True),
    ]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.INDEPENDENT_RULER
    assert ident.headlineIdentity == "大理的最高统治者"
    assert ident.primaryRealmTitle.name == "大理"
    assert ident.secondaryIdentities == ["安南的最高统治者"]
    # 禁止出现 tier 爵位硬编码。
    assert "国王" not in ident.headlineIdentity and "皇帝" not in ident.headlineIdentity


def test_identity_vassal_ruler():
    entries = [
        _entry("k_youji", tier="kingdom", liege="k_dali", name="幽蓟", name_source="save"),
    ]
    cls = _classify_save(entries)
    from models import TitlePeriod

    periods = [TitlePeriod(titleId="k_youji", name="幽蓟", isCurrent=True)]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.VASSAL_RULER
    assert ident.headlineIdentity == "幽蓟的领主"


def test_identity_landless_official():
    entries = [
        _entry("e_minister_shizheng", name="政事堂", name_source="save"),
    ]
    cls = _classify_save(entries)
    from models import TitlePeriod

    periods = [TitlePeriod(titleId="e_minister_shizheng", name="政事堂", isCurrent=True)]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.LANDLESS_OFFICIAL
    # 3C.7：政权机构不表示个人任职，只如实标注「（政权机构）」。
    assert ident.headlineIdentity == "政事堂（政权机构）"
    assert "任职" not in ident.headlineIdentity
    assert ident.primaryOffice is not None


def test_identity_former_ruler():
    entries = [_entry("k_dali", tier="kingdom", liege=None, name="大理", name_source="save")]
    cls = _classify_save(entries)
    from models import TitlePeriod

    periods = [TitlePeriod(titleId="k_dali", name="大理", start="930.1.1", end="940.1.1", isCurrent=False)]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.FORMER_RULER
    assert "大理" in ident.headlineIdentity


def test_identity_hegemony_ruler():
    """2C.2：持有霸权（h_*）头衔 → 身份标记 isHegemony，供前端展示「霸权」。"""
    entries = [_entry("h_china", tier="empire", liege=None, name="唐", name_source="save")]
    cls = _classify_save(entries)
    from models import TitlePeriod

    periods = [TitlePeriod(titleId="h_china", name="唐", tier=None, isCurrent=True)]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.INDEPENDENT_RULER
    assert ident.headlineIdentity == "唐的最高统治者"
    assert ident.isHegemony is True


def test_identity_plain_empire_not_hegemony():
    entries = [_entry("e_byzantium", tier="empire", liege=None, name="拜占庭", name_source="save")]
    cls = _classify_save(entries)
    from models import TitlePeriod

    periods = [TitlePeriod(titleId="e_byzantium", name="拜占庭", tier=None, isCurrent=True)]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.INDEPENDENT_RULER
    assert ident.isHegemony is False


def test_identity_courtier_with_past_office_only():
    entries = [_entry("e_minister_li", name="吏部", name_source="save")]
    cls = _classify_save(entries)
    from models import TitlePeriod

    # 只有过往官职、无现任头衔 → 廷臣（推断）。
    periods = [TitlePeriod(titleId="e_minister_li", name="吏部", start="930.1.1", end="940.1.1", isCurrent=False)]
    ident = PrimaryIdentityResolver(cls).resolve(periods)
    assert ident.realmStatus == RealmStatus.COURTIER


def test_identity_unknown_with_no_data():
    cls = _classify_save([])
    ident = PrimaryIdentityResolver(cls).resolve([])
    assert ident.realmStatus == RealmStatus.UNKNOWN
    assert ident.headlineIdentity == "身份未明"


def test_classify_all_returns_save_wide_classifications():
    entries = [
        _entry("k_dali", tier="kingdom", liege=None),
        _entry("x_nf_1486"),
        _entry("e_minister_li", name="吏部", name_source="save"),
    ]
    cls = _classify_save(entries)
    assert cls["k_dali"].semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE
    assert cls["x_nf_1486"].semanticType == TitleSemanticType.DYNASTY_IDENTITY
    assert cls["e_minister_li"].semanticType == TitleSemanticType.REALM_INSTITUTION

