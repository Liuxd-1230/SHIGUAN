"""头衔语义层（Phase 3C.2）—— 确定性规则，不涉及 LLM。

解决的问题（来自真实存档）：
  - 同一存档里 k_dali(大理)/k_viet(安南) 是主权王国，e_minister_*（政事堂/御史台/
    枢密院/六部）是政权机构，x_nf_*（梁家族）是家族身份头衔 —— 把它们统统
    「视为头衔列表」会抹平叙事差异。
  - 禁止按 tier 硬编码爵位（barony→男爵 / county→伯爵 / duchy→公爵 /
    kingdom→国王 / empire→皇帝）：展示名一律用游戏原生名（存档直书 → 本地化表
    → 原 key 回退），tier 只作为技术属性保留。

模块组成：
  1. `TitleSemanticRuleRegistry` —— 从 config/title-semantics/ 加载分层规则
     （user overrides > mods/ > generic.yml > base-game.yml > 启发式兜底）。
  2. `TitleSemanticClassifier` —— 把一条 titles.json 条目分类为契约
     TitleClassification（含展示名 / 判据 / 置信度 / 来源规则）。
  3. `TitleDisplayResolver` —— 展示名解析（游戏原生名，tier 不映射爵位）。
  4. `PrimaryIdentityResolver` —— 依据某人物当前头衔结构推导主要身份
     （headlineIdentity / realmStatus / primaryRealmTitle …）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from models import (
    CharacterIdentity,
    Confidence,
    EntityRef,
    EvidenceRef,
    RealmStatus,
    TitleClassification,
    TitlePeriod,
    TitleSemanticType,
    TitleTier,
)

# 分层优先级（从高到低）。
LAYER_ORDER = ("user", "mod", "generic", "base")

# 规则匹配用信号键（写入 TitleClassification.signals）。
_SIGNAL_KEY_PREFIX = "key_prefix"
_SIGNAL_TIER = "tier"
_SIGNAL_LIEGE = "liege"
_SIGNAL_RULE = "rule"
_SIGNAL_HEURISTIC = "heuristic"

# 领地家族（可与 liege 信号联合细分主权/领地/从属）。
_REALM_TYPES = {
    TitleSemanticType.SOVEREIGN_REALM_TITLE,
    TitleSemanticType.TERRITORIAL_REALM_TITLE,
    TitleSemanticType.SUBORDINATE_TERRITORY,
}
# 官职类（个人官职 / 政权机构 / 宗教职务）。
_OFFICE_TYPES = {
    TitleSemanticType.PERSONAL_OFFICE,
    TitleSemanticType.REALM_INSTITUTION,
    TitleSemanticType.RELIGIOUS_OFFICE,
}

_TIER_RANK = {
    TitleTier.BARONY: 0,
    TitleTier.COUNTY: 1,
    TitleTier.DUCHY: 2,
    TitleTier.KINGDOM: 3,
    TitleTier.EMPIRE: 4,
}

_TIER_MAP = {
    "barony": TitleTier.BARONY,
    "county": TitleTier.COUNTY,
    "duchy": TitleTier.DUCHY,
    "kingdom": TitleTier.KINGDOM,
    "empire": TitleTier.EMPIRE,
}


def _tier_of(raw: Optional[str]) -> Optional[TitleTier]:
    return _TIER_MAP.get(raw or "")


def _date_key(s: Optional[str]) -> tuple:
    """CK3 日期数值排序键（日期未零填充，必须数值比较）。未知 → 排最后。"""
    if not s:
        return (9999, 1, 1)
    parts = str(s).split(".")
    try:
        nums = tuple(int(p) for p in parts[:3])
    except ValueError:
        return (9999, 1, 1)
    return nums + (0,) * (3 - len(nums))


# ---------------------------------------------------------------------------
# 规则模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TitleSemanticRule:
    """一条语义规则（AND 语义：全部给定的 match 条件都满足才命中）。

    layer 决定优先级（user > mod > generic > base）；heuristic 由代码内置
    （永不来自文件）。adjust_by_liege 表示命中后可再按 de_facto_liege_id
    细分主权（liege=None）与封臣领地（liege 存在），用于 base 层领地规则。
    """
    id: str
    layer: str
    classify: TitleSemanticType
    confidence: Confidence
    source: str = ""                 # 规则文件（如 base-game.yml）
    adjust_by_liege: bool = False
    # 匹配条件（全部可选，AND 语义）。
    prefix: Optional[str] = None
    key_re: Optional[str] = None
    tier: Optional[str] = None
    name_contains: Optional[str] = None
    name_source: Optional[str] = None
    liege_is_null: Optional[bool] = None  # True=要求 liege 为空（独立）

    def matches(self, entry: dict) -> bool:
        key = entry.get("key") or ""
        if self.prefix and not key.startswith(self.prefix):
            return False
        if self.key_re and not re.search(self.key_re, key):
            return False
        if self.tier and entry.get("tier") != self.tier:
            return False
        if self.name_contains:
            name = (entry.get("name") or "").lower()
            if self.name_contains.lower() not in name:
                return False
        if self.name_source and entry.get("name_source") != self.name_source:
            return False
        if self.liege_is_null is not None:
            liege = entry.get("de_facto_liege_id")
            is_null = liege is None or str(liege) == "" or str(liege) == "0"
            if is_null != self.liege_is_null:
                return False
        return True


# ---------------------------------------------------------------------------
# 规则注册表（config/title-semantics/）
# ---------------------------------------------------------------------------

class TitleSemanticRuleRegistry:
    """分层规则注册表。

    目录约定（config/title-semantics/）：
      - user-overrides.yml   用户私有覆盖（最高优先；必须被 .gitignore 忽略）
      - mods/*.yml           特定 Mod 规则（按 mod 标识/标题结构签名匹配）
      - generic.yml          Mod 无关的安全规则
      - base-game.yml        基座游戏规则
    匹配顺序：user > mod > generic > base，首个命中的层生效；
    全部未命中 → 内置启发式（heuristic 层）。
    """

    def __init__(self, config_dir: str | Path | None = None) -> None:
        self._rules: dict[str, list[TitleSemanticRule]] = {layer: [] for layer in LAYER_ORDER}
        self._mod_files: list[dict] = []  # 每个 mod 规则文件的元数据（mods / title_signatures / 文件名）
        self.config_dir = Path(config_dir) if config_dir else None
        if self.config_dir is not None:
            self._load_dir(self.config_dir)

    def _load_dir(self, d: Path) -> None:
        if not d.is_dir():
            return
        # user overrides（层 user）
        user_file = d / "user-overrides.yml"
        if user_file.is_file():
            self._load_file(user_file, "user")
        # mods/（层 mod，先收集元数据再装规则）
        mods_dir = d / "mods"
        if mods_dir.is_dir():
            for f in sorted(mods_dir.glob("*.yml")):
                self._load_file(f, "mod")
        # generic
        generic = d / "generic.yml"
        if generic.is_file():
            self._load_file(generic, "generic")
        # base-game
        base = d / "base-game.yml"
        if base.is_file():
            self._load_file(base, "base")

    def _load_file(self, path: Path, layer: str) -> None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # 文件缺失/损坏：静默跳过（不影响其他层）。调用方可用 count() 检查。
            return
        if not isinstance(data, dict):
            return
        meta = data.get("meta") or {}
        if layer == "mod":
            self._mod_files.append(
                {
                    "file": path.name,
                    "mods": [str(m) for m in (meta.get("mods") or [])],
                    "title_signatures": [str(t) for t in (meta.get("title_signatures") or [])],
                }
            )
        for raw in data.get("rules") or []:
            if not isinstance(raw, dict):
                continue
            rule = self._rule_from_raw(raw, layer, path.name)
            if rule is not None:
                self._rules[layer].append(rule)

    @staticmethod
    def _rule_from_raw(raw: dict, layer: str, filename: str) -> Optional[TitleSemanticRule]:
        rid = str(raw.get("id") or "").strip()
        if not rid:
            return None
        cls = raw.get("classify") or {}
        if isinstance(cls, str):
            cls = {"semantic_type": cls}
        semantic = TitleSemanticType(cls.get("semantic_type"))
        conf_raw = str(cls.get("confidence") or "inferred")
        confidence = Confidence(conf_raw) if conf_raw in ("confirmed", "inferred", "uncertain") else Confidence.INFERRED
        match = raw.get("match") or {}
        return TitleSemanticRule(
            id=rid,
            layer=layer,
            classify=semantic,
            confidence=confidence,
            source=f"{filename}:{rid}",
            adjust_by_liege=bool(raw.get("adjust_by_liege")),
            prefix=match.get("prefix"),
            key_re=match.get("key_re"),
            tier=match.get("tier"),
            name_contains=match.get("name_contains"),
            name_source=match.get("name_source"),
            liege_is_null=match.get("liege_is_null"),
        )

    def count(self) -> int:
        return sum(len(v) for v in self._rules.values())

    def active_mod_rule_files(
        self,
        active_mod_ids: Optional[List[str]] = None,
        save_title_keys: Optional[List[str]] = None,
    ) -> List[dict]:
        """给定当前存档的 mod 标识与全部 title key，返回「激活」的 mod 规则文件。

        一个 mod 规则文件激活当且仅当：
          - 其 `mods` 任一子串出现在 active_mod_ids 中（真实 Mod 标识匹配），或
          - 其 `title_signatures` 任一前缀出现在本存档 title key 中（由存档内
            标题结构证据推断该 Mod 生效 —— 用于无法拿到 Mod 标识的场合）。
        两个列表都空的文件永不激活（不污染其他存档环境）。
        """
        out: List[dict] = []
        ids = [str(m).lower() for m in (active_mod_ids or [])]
        keys = [str(k) for k in (save_title_keys or [])]
        for f in self._mod_files:
            mods = [str(m).lower() for m in f.get("mods", [])]
            sigs = [str(s) for s in f.get("title_signatures", [])]
            if not mods and not sigs:
                continue
            hit = any(any(m in i for i in ids) for m in mods) if mods else False
            if not hit and sigs:
                hit = any(any(k.startswith(s) for k in keys) for s in sigs)
            if hit:
                out.append(f)
        return out

    def match(
        self, entry: dict, active_mod_files: Optional[List[dict]] = None
    ) -> Optional[TitleSemanticRule]:
        """按层优先级返回首个命中规则；全部未命中 → None（调用方走启发式）。"""
        for layer in LAYER_ORDER:
            rules = self._rules[layer]
            if layer == "mod":
                if not active_mod_files:
                    continue
                active_files = {f["file"] for f in active_mod_files}
                rules = [r for r in rules if r.source.split(":")[0] in active_files]
            for r in rules:
                if r.matches(entry):
                    return r
        return None


# ---------------------------------------------------------------------------
# 启发式兜底（基座游戏标题键结构）
# ---------------------------------------------------------------------------

def _heuristic_classify(entry: dict) -> tuple[TitleSemanticType, Confidence, List[str]]:
    key = entry.get("key") or ""
    if key.startswith("e_minister_"):
        # 政权机构形态（政事堂/御史台/枢密院/六部）——基座游戏无此前缀，属
        # 特定 Mod；无规则命中时保持 heuristic 兜底但标 inferred，交由
        # mods/user 层规则覆盖。
        return TitleSemanticType.REALM_INSTITUTION, Confidence.INFERRED, ["heuristic:e_minister_"]
    if key.startswith("h_"):
        return TitleSemanticType.SOVEREIGN_REALM_TITLE, Confidence.CONFIRMED, ["key_prefix:h_"]
    if key.startswith("x_nf_"):
        return TitleSemanticType.DYNASTY_IDENTITY, Confidence.CONFIRMED, ["key_prefix:x_nf_"]
    if key.startswith("x_c_nomad_"):
        return TitleSemanticType.TEMPORARY_TITLE, Confidence.INFERRED, ["key_prefix:x_c_nomad_"]
    if key.startswith("x_script_"):
        return TitleSemanticType.SPECIAL_MOD_TITLE, Confidence.INFERRED, ["key_prefix:x_script_"]
    if key.startswith("x_"):
        return TitleSemanticType.TEMPORARY_TITLE, Confidence.INFERRED, ["key_prefix:x_"]
    if key.startswith("e_"):
        return TitleSemanticType.SOVEREIGN_REALM_TITLE, Confidence.CONFIRMED, ["key_prefix:e_"]
    if key.startswith("k_") or key.startswith("d_"):
        return TitleSemanticType.TERRITORIAL_REALM_TITLE, Confidence.CONFIRMED, ["key_prefix:" + key[:1] + "_"]
    if key.startswith("c_") or key.startswith("b_"):
        return TitleSemanticType.SUBORDINATE_TERRITORY, Confidence.CONFIRMED, ["key_prefix:" + key[:1] + "_"]
    return TitleSemanticType.UNKNOWN, Confidence.UNCERTAIN, ["heuristic:none"]


def _liege_adjust(
    entry: dict,
    semantic: TitleSemanticType,
) -> tuple[TitleSemanticType, List[str]]:
    """按 de_facto_liege_id 细分领地家族（仅 base/heuristic 层的领地规则调用）。

    liege 为空（独立）：
      - e_/k_/d_ 级领地 → sovereign_realm_title（独立最高统治者）
      - c_/b_ 级领地 → territorial_realm_title（独立小领主，非从属）
    liege 存在（封臣）：
      - e_/k_/d_ → territorial_realm_title（封臣领地王国/公国）
      - c_/b_ → subordinate_territory（从属领地）
    规则层命中（user/mod/generic）返回的语义不在此调整 —— 显式规则优先。
    """
    liege = entry.get("de_facto_liege_id")
    is_null = liege is None or str(liege) == "" or str(liege) == "0"
    tier = _tier_of(entry.get("tier"))
    is_minor = tier in (TitleTier.BARONY, TitleTier.COUNTY)
    if is_null:
        if semantic == TitleSemanticType.SUBORDINATE_TERRITORY and is_minor:
            return TitleSemanticType.TERRITORIAL_REALM_TITLE, ["liege_adjust:independent_minor"]
        if semantic in (TitleSemanticType.SOVEREIGN_REALM_TITLE, TitleSemanticType.TERRITORIAL_REALM_TITLE):
            return TitleSemanticType.SOVEREIGN_REALM_TITLE, ["liege_adjust:independent"]
    else:
        if semantic in (TitleSemanticType.SOVEREIGN_REALM_TITLE, TitleSemanticType.TERRITORIAL_REALM_TITLE):
            return TitleSemanticType.TERRITORIAL_REALM_TITLE, ["liege_adjust:vassal"]
        if semantic == TitleSemanticType.TERRITORIAL_REALM_TITLE and is_minor:
            return TitleSemanticType.SUBORDINATE_TERRITORY, ["liege_adjust:subordinate"]
    return semantic, []


# ---------------------------------------------------------------------------
# 展示名解析（游戏原生名，tier 不映射爵位）
# ---------------------------------------------------------------------------

class TitleDisplayResolver:
    """把 titles.json 条目解析为游戏原生展示名。

    顺序（诚实性优先，全部未命中才回退原 key，绝不编造）：
      1. 存档直书可读名（name_source=save，如 title_name_data 里的中文名）；
      2. 本地化表（loc，duck-typed：仅需 .resolve(key) -> Optional[str]）；
      3. 回退原 key（resolved=False）。
    返回 (display_name, resolved)。
    """

    def __init__(self, loc=None) -> None:
        # loc 为可空对象，只需有 resolve(key) 方法（如 LocalizationLoader）。
        self.loc = loc

    def display_name(self, entry: dict) -> tuple[str, bool]:
        key = entry.get("key") or ""
        name = entry.get("name") or ""
        if name and entry.get("name_source") == "save":
            return name, True
        if self.loc is not None and key:
            resolved = self.loc.resolve(key)
            if resolved:
                return resolved, True
        if name:
            return name, name != key
        return key, False


# ---------------------------------------------------------------------------
# 分类器
# ---------------------------------------------------------------------------

class TitleSemanticClassifier:
    """把 titles.json 条目分类为 TitleClassification（确定性）。

    classify_all 一次性分类全部条目（供 TitleProfileIndex 缓存复用），
    并同时产出每条目的展示名（displayName）与判据。
    """

    def __init__(
        self,
        registry: Optional[TitleSemanticRuleRegistry] = None,
        display_resolver: Optional[TitleDisplayResolver] = None,
    ) -> None:
        self.registry = registry or TitleSemanticRuleRegistry()
        self.display = display_resolver or TitleDisplayResolver()

    def _classify_one(self, entry: dict, active_mod_files=None) -> TitleClassification:
        key = entry.get("key") or ""
        display_name, resolved = self.display.display_name(entry)
        rule = self.registry.match(entry, active_mod_files)
        signals: List[str] = []
        if key.startswith("b_") or key.startswith("c_") or key.startswith("d_") \
                or key.startswith("k_") or key.startswith("e_") or key.startswith("h_") \
                or key.startswith("x_"):
            signals.append(f"{_SIGNAL_KEY_PREFIX}:{key.split('_')[0]}_")
        tier = _tier_of(entry.get("tier"))
        if tier is not None:
            signals.append(f"{_SIGNAL_TIER}:{tier.value}")
        liege = entry.get("de_facto_liege_id")
        is_null = liege is None or str(liege) == "" or str(liege) == "0"
        signals.append(f"{_SIGNAL_LIEGE}:{'None' if is_null else str(liege)}")

        warnings: List[str] = []
        if rule is not None:
            semantic = rule.classify
            confidence = rule.confidence
            source_rule = rule.source
            signals.append(f"{_SIGNAL_RULE}:{rule.source}")
            # 仅 base/heuristic 层领地规则做 liege 细分；显式规则（user/mod/generic）不覆盖。
            if rule.adjust_by_liege or rule.layer == "heuristic":
                adjusted, adj_signals = _liege_adjust(entry, semantic)
                if adjusted != semantic:
                    signals.extend(adj_signals)
                    semantic = adjusted
            if not resolved:
                warnings.append(f"展示名未解析（回退 key {key}，本地化表缺失或未命中）。")
        else:
            semantic, confidence, hsig = _heuristic_classify(entry)
            signals.extend(hsig)
            if semantic != TitleSemanticType.UNKNOWN:
                adjusted, adj_signals = _liege_adjust(entry, semantic)
                if adjusted != semantic:
                    signals.extend(adj_signals)
                    semantic = adjusted
            source_rule = "heuristic"
            if semantic == TitleSemanticType.UNKNOWN:
                warnings.append(f"头衔 {key} 无任何规则与启发式信号，语义无法确认。")
            if not resolved:
                warnings.append(f"展示名未解析（回退 key {key}）。")

        return TitleClassification(
            titleId=key,
            semanticType=semantic,
            confidence=confidence,
            displayName=display_name,
            tier=tier,
            signals=signals,
            warnings=warnings,
            sourceRule=source_rule,
        )

    def classify(
        self, entry: dict, active_mod_files: Optional[List[dict]] = None
    ) -> TitleClassification:
        return self._classify_one(entry, active_mod_files)

    def classify_all(
        self,
        entries: List[dict],
        active_mod_ids: Optional[List[str]] = None,
    ) -> tuple[Dict[str, TitleClassification], List[dict]]:
        """批量分类全部条目 → (titleId -> TitleClassification, active_mod_files)。

        先依据存档 mod 标识 + 全部 title key 计算激活的 mod 规则文件，再逐条分类。
        """
        keys = [str(e.get("key") or "") for e in entries]
        active = self.registry.active_mod_rule_files(active_mod_ids, keys)
        out: Dict[str, TitleClassification] = {}
        for entry in entries:
            key = entry.get("key") or ""
            if not key:
                continue
            out[key] = self._classify_one(entry, active)
        return out, active


# ---------------------------------------------------------------------------
# 主要身份判定（PrimaryIdentityResolver）
# ---------------------------------------------------------------------------

def _entity_ref(classification: TitleClassification) -> EntityRef:
    key = classification.titleId
    return EntityRef(
        id=key,
        name=classification.displayName,
        type="title",
        resolved=classification.displayName != key,
        sourcePath=f"landed_titles/{key}",
    )


def _headline_for(title_name: str, realm_status: str) -> str:
    """主要身份 headline（确定性文案；只用游戏原生名，不出现 tier 爵位词）。"""
    if realm_status == "independent_ruler":
        return f"{title_name}的最高统治者"
    if realm_status == "vassal_ruler":
        return f"{title_name}的领主"
    return title_name


def aggregate_entities(
    periods: List[TitlePeriod],
    classifications: Dict[str, TitleClassification],
) -> Dict[str, List[EntityRef]]:
    """现任头衔按语义类型聚合（3C.2 前端分区数据）。

    返回：
      majorTerritories（主权/领地王国及以上）、subordinateTerritories（伯/男爵领）、
      personalOffices / realmInstitutions / religiousOffices / honors / claims。
    排序：等级降序 → 展示名稳定序（确定性）。
    """
    current = [p for p in periods if getattr(p, "isCurrent", False)]
    buckets: Dict[str, List[TitlePeriod]] = {
        "major": [],
        "minor": [],
        "offices": [],
        "institutions": [],
        "religious": [],
        "honors": [],
        "claims": [],
    }
    for p in current:
        cls = classifications.get(p.titleId)
        if cls is None:
            continue
        st = cls.semanticType
        if st in (TitleSemanticType.SOVEREIGN_REALM_TITLE, TitleSemanticType.TERRITORIAL_REALM_TITLE):
            buckets["major"].append(p)
        elif st == TitleSemanticType.SUBORDINATE_TERRITORY:
            buckets["minor"].append(p)
        elif st == TitleSemanticType.PERSONAL_OFFICE:
            buckets["offices"].append(p)
        elif st == TitleSemanticType.REALM_INSTITUTION:
            buckets["institutions"].append(p)
        elif st == TitleSemanticType.RELIGIOUS_OFFICE:
            buckets["religious"].append(p)
        elif st == TitleSemanticType.HONORARY_TITLE:
            buckets["honors"].append(p)
        elif st == TitleSemanticType.CLAIM_ONLY:
            buckets["claims"].append(p)

    def _refs(ps: List[TitlePeriod]) -> List[EntityRef]:
        out = []
        for p in sorted(ps, key=lambda p: (p.titleId,)):
            cls = classifications.get(p.titleId)
            if cls is None:
                continue
            ref = _entity_ref(cls)
            out.append(ref)
        return out

    return {
        "majorTerritories": _refs(buckets["major"]),
        "subordinateTerritories": _refs(buckets["minor"]),
        "personalOffices": _refs(buckets["offices"]),
        "realmInstitutions": _refs(buckets["institutions"]),
        "religiousOffices": _refs(buckets["religious"]),
        "honors": _refs(buckets["honors"]),
        "claims": _refs(buckets["claims"]),
    }


class PrimaryIdentityResolver:
    """依据某人物当前头衔结构推导主要身份（CharacterIdentity）。

    确定性规则：
      - 现任头衔中语义为 SOVEREIGN_REALM_TITLE 的领地 → independent_ruler；
      - 否则现任领地（TERRITORIAL / SUBORDINATE）→ vassal_ruler（或独立小领主）；
      - 无领地但现任官职/机构 → landless_official；
      - 无领地但现任宗教职务 → religious_leader；
      - 无现任头衔但有历史任期 → former_ruler；
      - 其余无法判定 → unknown（绝不把「无现任头衔」一律写成平民）。
    primaryRealmTitle = 现任最高等级主权/领地头衔（同级按 titleId 稳定取一）；
    headline 使用该头衔游戏原生展示名 + 地位限定词（无 tier 爵位词）。
    """

    def __init__(self, classifications: Dict[str, TitleClassification]) -> None:
        # titleId -> TitleClassification（由 TitleSemanticClassifier.classify_all 产出）。
        self._cls = classifications

    def resolve(
        self,
        periods: List[TitlePeriod],
    ) -> CharacterIdentity:
        """periods 为某人物全部任期（TitleReignExtractor.extract 产出）。"""
        current = [p for p in periods if getattr(p, "isCurrent", False)]
        cur_by_key: Dict[str, TitlePeriod] = {p.titleId: p for p in current}
        cls_by_key = {
            k: c for k, c in self._cls.items() if k in cur_by_key
        }

        evidence: List[EvidenceRef] = []
        warnings: List[str] = []
        for key in sorted(cls_by_key):
            c = cls_by_key[key]
            if c.confidence == Confidence.INFERRED:
                warnings.append(
                    f"头衔 {key} 的语义分类为推断（{c.sourceRule}），身份判定据此降级。"
                )
            if not c.displayName or c.displayName == key:
                warnings.append(f"头衔 {key} 展示名未解析，身份表述使用原始 key。")

        def _evidence(key: str, desc: str) -> EvidenceRef:
            return EvidenceRef(
                id=f"identity-{key}",
                sourceType="title",
                sourcePath=f"landed_titles/{key}",
                rawKey=key,
                description=desc,
                confidence=Confidence.CONFIRMED,
            )

        # 排序：等级降序 → titleId 稳定顺序。
        def _sort_key(p: TitlePeriod):
            c = cls_by_key.get(p.titleId)
            return (
                -(_TIER_RANK.get(c.tier, -1) if c and c.tier is not None else -1),
                p.titleId,
            )

        sovereign = sorted(
            [k for k in cls_by_key if cls_by_key[k].semanticType == TitleSemanticType.SOVEREIGN_REALM_TITLE],
            key=lambda k: cur_by_key[k].titleId,
        )
        territorial = sorted(
            [k for k in cls_by_key if cls_by_key[k].semanticType == TitleSemanticType.TERRITORIAL_REALM_TITLE],
            key=lambda k: cur_by_key[k].titleId,
        )
        subordinate = sorted(
            [k for k in cls_by_key if cls_by_key[k].semanticType == TitleSemanticType.SUBORDINATE_TERRITORY],
            key=lambda k: cur_by_key[k].titleId,
        )
        offices = sorted(
            [k for k in cls_by_key if cls_by_key[k].semanticType == TitleSemanticType.PERSONAL_OFFICE],
            key=lambda k: cur_by_key[k].titleId,
        )
        institutions = sorted(
            [k for k in cls_by_key if cls_by_key[k].semanticType == TitleSemanticType.REALM_INSTITUTION],
            key=lambda k: cur_by_key[k].titleId,
        )
        religious = sorted(
            [k for k in cls_by_key if cls_by_key[k].semanticType == TitleSemanticType.RELIGIOUS_OFFICE],
            key=lambda k: cur_by_key[k].titleId,
        )

        all_realm = sovereign + territorial + subordinate
        all_realm.sort(key=lambda k: _sort_key(cur_by_key[k]))

        identity_confidence = Confidence.CONFIRMED
        if any(cls_by_key[k].confidence == Confidence.INFERRED for k in all_realm):
            identity_confidence = Confidence.INFERRED
        if any(cls_by_key[k].confidence == Confidence.UNCERTAIN for k in all_realm):
            identity_confidence = Confidence.UNCERTAIN

        if sovereign:
            status = RealmStatus.INDEPENDENT_RULER
            primary_key = sovereign[0]
            primary_ref = _entity_ref(cls_by_key[primary_key])
            headline = _headline_for(primary_ref.name, status.value)
            evidence.append(
                _evidence(primary_key, "landed_titles 顶层 holder（独立主权头衔）")
            )
            secondary = [
                _headline_for(cls_by_key[k].displayName, status.value)
                for k in sovereign[1:]
            ]
            return CharacterIdentity(
                headlineIdentity=headline,
                realmStatus=status,
                primaryRealmTitle=primary_ref,
                secondaryIdentities=secondary,
                confidence=identity_confidence,
                warnings=warnings,
                evidence=evidence,
            )

        if territorial or subordinate:
            # 独立小领主（无 liege 的 c_/b_）也在 territorial 集合里被细分过；
            # 无法从 period 单独判 liege 时按 subordinate 集合判断。
            status = RealmStatus.VASSAL_RULER
            primary_key = (territorial + subordinate)[0]
            primary_ref = _entity_ref(cls_by_key[primary_key])
            headline = _headline_for(primary_ref.name, status.value)
            evidence.append(
                _evidence(primary_key, "landed_titles 记录的封地持有（主领地）")
            )
            return CharacterIdentity(
                headlineIdentity=headline,
                realmStatus=status,
                primaryRealmTitle=primary_ref,
                secondaryIdentities=[],
                confidence=identity_confidence,
                warnings=warnings,
                evidence=evidence,
            )

        # 无领地：官职 / 机构 / 宗教职务。
        if offices or institutions:
            primary_key = (offices + institutions)[0]
            primary_ref = _entity_ref(cls_by_key[primary_key])
            return CharacterIdentity(
                headlineIdentity=f"{primary_ref.name}任职",
                realmStatus=RealmStatus.LANDLESS_OFFICIAL,
                primaryOffice=primary_ref,
                secondaryIdentities=[],
                confidence=identity_confidence,
                warnings=warnings,
                evidence=[_evidence(primary_key, "landed_titles 记录的官职/机构职务")],
            )

        if religious:
            primary_key = religious[0]
            primary_ref = _entity_ref(cls_by_key[primary_key])
            return CharacterIdentity(
                headlineIdentity=primary_ref.name,
                realmStatus=RealmStatus.RELIGIOUS_LEADER,
                primaryOffice=primary_ref,
                secondaryIdentities=[],
                confidence=identity_confidence,
                warnings=warnings,
                evidence=[_evidence(primary_key, "landed_titles 记录的宗教职务")],
            )

        # 无现任头衔：有历史任期 → 前统治者；否则无法判定。
        if periods:
            past = sorted(periods, key=lambda p: _date_key(p.start))
            last = past[-1]
            last_cls = self._cls.get(last.titleId)
            if last_cls is not None and last_cls.semanticType in _REALM_TYPES:
                return CharacterIdentity(
                    headlineIdentity=f"{last_cls.displayName}的前统治者",
                    realmStatus=RealmStatus.FORMER_RULER,
                    primaryRealmTitle=_entity_ref(last_cls),
                    secondaryIdentities=[],
                    confidence=Confidence.INFERRED,
                    warnings=warnings + ["该人物无现任头衔；依据历史任期判定为前统治者。"],
                    evidence=[_evidence(last.titleId, "landed_titles 历史任期（非现任）")],
                )
            return CharacterIdentity(
                headlineIdentity="廷臣",
                realmStatus=RealmStatus.COURTIER,
                secondaryIdentities=[],
                confidence=Confidence.INFERRED,
                warnings=warnings + ["该人物无现任领地与官职，判定为廷臣（推断）。"],
                evidence=[],
            )

        return CharacterIdentity(
            headlineIdentity="身份未明",
            realmStatus=RealmStatus.UNKNOWN,
            secondaryIdentities=[],
            confidence=Confidence.UNCERTAIN,
            warnings=warnings + ["无任何可用的头衔/官职数据，身份无法判定。"],
            evidence=[],
        )
