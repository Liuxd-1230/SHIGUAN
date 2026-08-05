"""Phase 3C.1 人工验收基准 —— 16 类角色样本（全部为脱敏合成数据）。

每个样本是一份合成 titles.json（绝不来自真实存档），配合确定性断言：
  - expectedHeadlineIdentity / realmStatus / primaryRealmTitle；
  - personalOffices / realmInstitutions（现任官职/机构聚合）；
  - forbiddenInterpretations（身份表述中**不得出现**的词，如按 tier 硬编码的
    「皇帝/国王/公爵/伯爵/男爵」，或伪造的「继承/征服/册封」因果）。

run_case() 把样本跑完 TitleProfileIndex → 分类 → 身份 → 聚合 → 语义事件，
check_case() 返回断言失败列表（空 = 通过）。供 pytest 与 scripts/phase3c_acceptance.py
共同复用，保证人工验收与 CI 断言同源。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from biography_engine.historical_events import HistoricalEventSemanticBuilder
from biography_engine.title_semantics import (
    PrimaryIdentityResolver,
    TitleSemanticClassifier,
    TitleSemanticRuleRegistry,
    aggregate_entities,
)
from app.services.title_reign_extractor import TitleProfileIndex

CONFIG_DIR = Path(__file__).resolve().parents[4] / "config" / "title-semantics"

# 合成样本的默认任期（900.1.1 起现任）。
_DEFAULT_HISTORY = [
    {"date": "900.1.1", "holder_id": "c1", "kind": "holder"},
]


def _entry(
    key: str,
    name: str,
    tier: Optional[str] = None,
    liege: Optional[str] = None,
    history: Optional[list] = None,
    holder: str = "c1",
    name_source: str = "save",
) -> dict:
    return {
        "key": key,
        "name": name,
        "name_source": name_source,
        "tier": tier,
        "holder_id": holder,
        "de_facto_liege_id": liege,
        "history": list(history if history is not None else _DEFAULT_HISTORY),
    }


def _raw(entries: list) -> dict:
    return {"schema_version": 1, "reader_version": "0.1.0", "titles": list(entries), "warnings": []}


# 个人官职（Mod 规则演示）规则文件：title_signatures 匹配存档标题结构才激活。
PERSONAL_OFFICE_MOD_FILE = """# 合成 Mod 规则（脱敏）：尚书令属个人官职
version: 1
meta:
  title_signatures: ["e_taizai_"]
rules:
  - id: synthetic_personal_office
    match: { prefix: "e_taizai_" }
    classify: { semantic_type: personal_office, confidence: confirmed }
"""

CASES = [
    {
        "id": "independent_emperor",
        "title": "独立皇帝（e_ 无封君）",
        "titles": [_entry("e_zhongyuan", "中原", tier="empire", liege=None)],
        "expect": {
            "realmStatus": "independent_ruler",
            "headlineIdentity": "中原的最高统治者",
            "primaryRealmTitleId": "e_zhongyuan",
            "forbiddenInterpretations": ["皇帝", "陛下", "男爵", "伯爵", "公爵", "国王"],
        },
    },
    {
        "id": "independent_king",
        "title": "独立国王（k_ 无封君）",
        "titles": [_entry("k_dali", "大理", tier="kingdom", liege=None)],
        "expect": {
            "realmStatus": "independent_ruler",
            "headlineIdentity": "大理的最高统治者",
            "primaryRealmTitleId": "k_dali",
            "forbiddenInterpretations": ["国王"],
        },
    },
    {
        "id": "super_empire_identity",
        "title": "超帝国身份头衔（h_* 无封君）",
        "titles": [_entry("h_huaxia", "华夏", tier=None, liege=None)],
        "expect": {
            "realmStatus": "independent_ruler",
            "headlineIdentity": "华夏的最高统治者",
            "primaryRealmTitleId": "h_huaxia",
            "forbiddenInterpretations": ["皇帝"],
        },
    },
    {
        "id": "vassal_duke",
        "title": "封臣公爵（d_ 有封君）",
        "titles": [_entry("d_youji", "幽蓟", tier="duchy", liege="k_dali")],
        "expect": {
            "realmStatus": "vassal_ruler",
            "headlineIdentity": "幽蓟的领主",
            "primaryRealmTitleId": "d_youji",
            "forbiddenInterpretations": ["公爵"],
        },
    },
    {
        "id": "vassal_count",
        "title": "封臣伯爵（c_ 有封君）",
        "titles": [_entry("c_weizhou", "魏州", tier="county", liege="k_dali")],
        "expect": {
            "realmStatus": "vassal_ruler",
            "headlineIdentity": "魏州的领主",
            "primaryRealmTitleId": "c_weizhou",
            "forbiddenInterpretations": ["伯爵"],
        },
    },
    {
        "id": "vassal_baron",
        "title": "封臣男爵（b_ 有封君）",
        "titles": [_entry("b_yunmen", "云门", tier="barony", liege="c_weizhou")],
        "expect": {
            "realmStatus": "vassal_ruler",
            "headlineIdentity": "云门的领主",
            "primaryRealmTitleId": "b_yunmen",
            "forbiddenInterpretations": ["男爵"],
        },
    },
    {
        "id": "independent_minor_lord",
        "title": "独立小领主（c_ 无封君）",
        "titles": [_entry("c_guzhu", "孤竹", tier="county", liege=None)],
        "expect": {
            # 当前 RealmStatus 单一枚举无法区分「独立小领主」，诚实落到 vassal_ruler
            # （headline 用「的领主」，不写爵位词）。
            "realmStatus": "vassal_ruler",
            "headlineIdentity": "孤竹的领主",
            "primaryRealmTitleId": "c_guzhu",
            "forbiddenInterpretations": ["伯爵"],
        },
    },
    {
        "id": "institution_official",
        "title": "无地机构官员（e_minister_*）",
        "titles": [_entry("e_minister_shizheng", "政事堂", tier=None, liege=None)],
        "expect": {
            "realmStatus": "landless_official",
            # 3C.7：政权机构不表示个人任职 —— 只如实标注「（政权机构）」。
            "headlineIdentity": "政事堂（政权机构）",
            "primaryOfficeId": "e_minister_shizheng",
            "realmInstitutions": ["政事堂"],
            "forbiddenInterpretations": ["帝国", "国王", "政事堂任职"],
        },
    },
    {
        "id": "personal_office_holder",
        "title": "个人官职（Mod 规则经标题结构签名激活）",
        "overlay": ("test-personal-office.yml", PERSONAL_OFFICE_MOD_FILE),
        "titles": [_entry("e_taizai_shangshu", "尚书令", tier=None, liege=None)],
        "expect": {
            "realmStatus": "landless_official",
            "headlineIdentity": "尚书令任职",
            "primaryOfficeId": "e_taizai_shangshu",
            "personalOffices": ["尚书令"],
            "forbiddenInterpretations": ["帝国"],
            # 规则未激活的环境里不得借光：同 key 应落到 base e_ 规则（主权领地）。
            "isolationExpectation": {
                "classificationSemantic": None,  # 断言点单独处理
            },
        },
    },
    {
        "id": "religious_leader",
        "title": "宗教领袖（k_papal_state 教宗国）",
        "titles": [_entry("k_papal_state", "教宗国", tier=None, liege=None)],
        "expect": {
            "realmStatus": "religious_leader",
            "headlineIdentity": "教宗国",
            "primaryOfficeId": "k_papal_state",
            "forbiddenInterpretations": ["国王", "皇帝"],
        },
    },
    {
        "id": "dynasty_identity_holder",
        "title": "家族身份头衔持有者（x_nf_*，无领地）",
        "titles": [_entry("x_nf_liang", "梁", tier=None, liege=None)],
        "expect": {
            "realmStatus": "courtier",
            "headlineIdentity": "廷臣",
            "forbiddenInterpretations": ["皇帝", "王国", "最高统治者"],
        },
    },
    {
        "id": "temporary_title_holder",
        "title": "临时头衔持有者（x_c_nomad_*，无领地）",
        "titles": [_entry("x_c_nomad_camp", "营地", tier=None, liege=None)],
        "expect": {
            "realmStatus": "courtier",
            "headlineIdentity": "廷臣",
            "forbiddenInterpretations": ["皇帝", "最高统治者"],
        },
    },
    {
        "id": "former_ruler",
        "title": "前统治者（仅历史任期）",
        "titles": [
            _entry(
                "d_youji",
                "幽蓟",
                tier="duchy",
                liege=None,
                holder="c2",
                history=[
                    {"date": "800.1.1", "holder_id": "c1", "kind": "holder"},
                    {"date": "860.5.5", "holder_id": "c2", "kind": "holder"},
                ],
            ),
        ],
        "expect": {
            "realmStatus": "former_ruler",
            "headlineIdentity": "幽蓟的前统治者",
            "primaryRealmTitleId": "d_youji",
            "forbiddenInterpretations": ["的领主"],
        },
    },
    {
        "id": "courtier",
        "title": "廷臣（有头衔记录但无领地/官职）",
        "titles": [
            # 无领地无官职的 x_ 头衔（heuristic → temporary_title），不构成身份。
            _entry("x_script_event_1", "脚本头衔", tier=None, liege=None),
        ],
        "expect": {
            "realmStatus": "courtier",
            "headlineIdentity": "廷臣",
            "forbiddenInterpretations": ["平民", "皇帝"],
        },
    },
    {
        "id": "unknown_identity",
        "title": "身份未明（存档无任何头衔记录）",
        "titles": [],
        "expect": {
            "realmStatus": "unknown",
            "headlineIdentity": "身份未明",
            "forbiddenInterpretations": ["平民", "廷臣"],
        },
    },
    {
        "id": "multi_title_same_day_split",
        "title": "同日大量头衔变更按语义类型拆分（不推断因果）",
        "titles": [
            _entry(
                "e_zhongyuan",
                "中原",
                tier="empire",
                liege=None,
                history=[{"date": "950.1.1", "holder_id": "c1", "kind": "created"}],
            ),
            _entry(
                "c_weizhou",
                "魏州",
                tier="county",
                liege="e_zhongyuan",
                history=[{"date": "952.8.16", "holder_id": "c1", "kind": "holder"}],
            ),
            _entry(
                "c_guzhu",
                "孤竹",
                tier="county",
                liege="e_zhongyuan",
                history=[{"date": "952.8.16", "holder_id": "c1", "kind": "holder"}],
            ),
            _entry(
                "e_minister_shizheng",
                "政事堂",
                tier=None,
                liege=None,
                history=[{"date": "952.8.16", "holder_id": "c1", "kind": "holder"}],
            ),
        ],
        "expect": {
            "realmStatus": "independent_ruler",
            "headlineIdentity": "中原的最高统治者",
            "semanticEventCount": 3,
            "semanticTypes": ["identity_transition", "territorial_gain", "institution_transition"],
            "territorialGainTitles": ["c_weizhou", "c_guzhu"],  # 同日同语义合并为一条
            "forbiddenInterpretations": ["继承", "征服", "册封"],
        },
    },
]


def _build_registry(case: dict, use_overlay: bool = True) -> TitleSemanticRuleRegistry:
    """加载 config/title-semantics；case 指定 overlay（Mod 规则）时叠加到临时目录。"""
    if not use_overlay or not case.get("overlay"):
        return TitleSemanticRuleRegistry(CONFIG_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "title-semantics" / "mods"
        d.mkdir(parents=True)
        fname, content = case["overlay"]
        (d / fname).write_text(content, encoding="utf-8")
        # base-game/generic 也复制过去，保证分层完整。
        src = CONFIG_DIR
        for f in ("base-game.yml", "generic.yml"):
            (Path(tmp) / "title-semantics" / f).write_text(
                (src / f).read_text(encoding="utf-8"), encoding="utf-8"
            )
        return TitleSemanticRuleRegistry(Path(tmp) / "title-semantics")


def run_case(case: dict) -> dict:
    """跑完整管线，返回身份/聚合/语义事件等结果供断言。"""
    registry = _build_registry(case)
    idx = TitleProfileIndex(
        _raw(case["titles"]), semantic_registry=registry, active_mod_ids=case.get("mods") or []
    )
    cls = idx.classifications()
    periods = idx.periods("c1")
    identity = PrimaryIdentityResolver(cls).resolve(periods)
    aggregates = aggregate_entities(periods, cls)
    sem_events, timeline_events = HistoricalEventSemanticBuilder(
        "c1", "梁克贞", cls, idx.raw_entries()
    ).build(periods)
    return {
        "identity": identity,
        "classifications": cls,
        "aggregates": aggregates,
        "semantic_events": sem_events,
        "timeline_events": timeline_events,
        "periods": periods,
    }


def check_case(case: dict) -> list[str]:
    """断言样本预期；返回失败信息列表（空 = 通过）。"""
    failures: list[str] = []
    exp = case["expect"]
    r = run_case(case)
    ident = r["identity"]
    aggs = r["aggregates"]

    def _refs(key: str) -> list:
        return [e.name for e in (aggs.get(key) or [])]

    actual_status = ident.realmStatus.value
    if actual_status != exp.get("realmStatus"):
        failures.append(f"[{case['id']}] realmStatus={actual_status} != {exp.get('realmStatus')}")

    if ident.headlineIdentity != exp.get("headlineIdentity"):
        failures.append(
            f"[{case['id']}] headlineIdentity={ident.headlineIdentity!r} != {exp.get('headlineIdentity')!r}"
        )

    if exp.get("primaryRealmTitleId"):
        got = (ident.primaryRealmTitle.id if ident.primaryRealmTitle else None)
        if got != exp["primaryRealmTitleId"]:
            failures.append(f"[{case['id']}] primaryRealmTitle={got} != {exp['primaryRealmTitleId']}")

    if exp.get("primaryOfficeId"):
        got = (ident.primaryOffice.id if ident.primaryOffice else None)
        if got != exp["primaryOfficeId"]:
            failures.append(f"[{case['id']}] primaryOffice={got} != {exp['primaryOfficeId']}")

    if exp.get("personalOffices"):
        got = _refs("personalOffices")
        if not all(n in got for n in exp["personalOffices"]):
            failures.append(f"[{case['id']}] personalOffices={got} 缺 {exp['personalOffices']}")

    if exp.get("realmInstitutions"):
        got = _refs("realmInstitutions")
        if not all(n in got for n in exp["realmInstitutions"]):
            failures.append(f"[{case['id']}] realmInstitutions={got} 缺 {exp['realmInstitutions']}")

    # 禁止解释：headline / 语义事件摘要中不得出现指定词（tier 爵位硬编码 / 伪造因果）。
    haystack = ident.headlineIdentity
    for ev in r["semantic_events"]:
        haystack += " " + ev.summary
    for bad in exp.get("forbiddenInterpretations") or []:
        if bad in haystack:
            failures.append(f"[{case['id']}] 出现禁止词 {bad!r}（headline/语义摘要）")

    # 语义事件断言（multi_title_same_day_split 专用）。
    if "semanticEventCount" in exp:
        types = [e.semanticType.value for e in r["semantic_events"]]
        for want in exp.get("semanticTypes") or []:
            if want not in types:
                failures.append(f"[{case['id']}] 语义事件缺类型 {want}（实际 {types}）")
        if len(r["semantic_events"]) != exp["semanticEventCount"]:
            failures.append(
                f"[{case['id']}] 语义事件数 {len(r['semantic_events'])} != {exp['semanticEventCount']}"
            )
        tg = [
            e for e in r["semantic_events"] if e.semanticType.value == "territorial_gain"
        ]
        if tg:
            tids = tg[0].relatedTitleIds
            if sorted(tids) != sorted(exp.get("territorialGainTitles") or []):
                failures.append(f"[{case['id']}] 同日同语义未正确合并：{tids}")
            if tg[0].acquisitionCause != "unknown" or not tg[0].narrativeConstraints:
                failures.append(f"[{case['id']}] 领地获得未如实标 unknown/无约束")
        # 创建（kind=created）被证实为 creation。
        created = [e for e in r["semantic_events"] if e.acquisitionCause == "creation"]
        if not created:
            failures.append(f"[{case['id']}] kind=created 未解析为 creation")

    # Mod 规则隔离（personal_office_holder 专用）：未激活时不得借光。
    iso = exp.get("isolationExpectation")
    if iso is not None:
        plain = run_case({**case, "overlay": None})
        pc = plain["classifications"].get("e_taizai_shangshu")
        if pc is None:
            failures.append(f"[{case['id']}] 无 overlay 时该 key 无分类")
        elif pc.semanticType.value == "personal_office":
            failures.append(
                f"[{case['id']}] 无 overlay 时 Mod 规则被错误激活（{pc.semanticType.value}）"
            )
    return failures


def all_cases_ok() -> tuple[bool, list[str]]:
    all_failures: list[str] = []
    for case in CASES:
        all_failures.extend(check_case(case))
    return (not all_failures, all_failures)
