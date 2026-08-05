"""TitleReignExtractor —— 从 titles.json 聚合单个角色的头衔与统治经历（M3）。

Rust ck3-reader 的 prepare 已把 landed_titles 反解为 titles.json：
每个头衔含 key / name / name_source / tier / holder_id / de_facto_liege_id /
history（按日期排序的持有者变更记录，Format A: date=ID；Format B:
date={type=created/destroyed holder=ID}）。

本模块把它聚合为契约的 TitlePeriod[]：
  - 现任头衔：entry.holder_id == 目标角色 → isCurrent=True、end=None。
  - 过往任职：history 中 holder 连续同值段 → 一段 (start, end)，end 为下一变更日。
  - 名字解析顺序：存档直书可读名（name_source=save）→ 实体索引（含 loc 解析）→
    本地化表 → 回退 key（不伪造）。
  - 现任但 history 无对应段（如 history 为空）→ start=None，诚实留空。

M3 追加（TitleProfileIndex）：
  - 一次性反解全部人物的头衔（列表页摘要 + 人物页档案共用，不重复扫描 titles.json）。
  - primaryTitle / highestTitleTier / isRuler：仅由“当前持有”判定（top-level holder），
    等级取当前头衔最高者；多个同级取稳定顺序并标 inferred warning；等级全部未知则留空。
  - title_gain / title_loss / succession 时间线事件：仅当存在明确 holder 变更 + 日期时生成。
  - 头衔顶层 holder 与 history 末项 holder 冲突 → warning，不静默覆盖。

诚实性原则（贯穿 Phase 2B）：
  - 查不到的名字绝不编造：name 回退为 key。
  - 未知起止日期置空，不猜。
  - tier 未知（key 前缀无法推导）→ None，不强造。
  - 推断的 primaryTitle 不会自动生成“继位”事件；只有明确 holder 变更 + 日期才生成事件。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models import (
    Confidence,
    EntityRef,
    EvidenceRef,
    EvidenceWarning,
    EventType,
    TimelineEvent,
    TitlePeriod,
    TitleTier,
    WarningSeverity,
)

from app.services.entity_index_builder import ReferenceResolver
from app.services.localization import LocalizationLoader

from biography_engine.historical_events import HistoricalEventSemanticBuilder
from biography_engine.title_semantics import (
    TitleClassification,
    TitleDisplayResolver,
    TitleSemanticClassifier,
    TitleSemanticRuleRegistry,
)

TIER_MAP = {
    "barony": TitleTier.BARONY,
    "county": TitleTier.COUNTY,
    "duchy": TitleTier.DUCHY,
    "kingdom": TitleTier.KINGDOM,
    "empire": TitleTier.EMPIRE,
}

_TIER_RANK = {
    TitleTier.BARONY: 0,
    TitleTier.COUNTY: 1,
    TitleTier.DUCHY: 2,
    TitleTier.KINGDOM: 3,
    TitleTier.EMPIRE: 4,
}


def _tier_of(raw: Optional[str]) -> Optional[TitleTier]:
    return TIER_MAP.get(raw or "")  # unknown → None


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


def _reign_runs(
    history: list[dict], cid: str
) -> list[list[Optional[str]]]:
    """把 history 中 holder 连续同值段聚合为 [(start, end)]。

    end=None 表示该段在 history 末尾仍未结束（开放段）。
    history 为空 → 空列表（调用方自行处理"现任但无历史段"）。
    """
    runs: list[list[Optional[str]]] = []
    run_start: Optional[str] = None
    for h in history:
        date = h.get("date")
        holder_raw = h.get("holder_id")
        holder = str(holder_raw) if holder_raw is not None else None
        if holder == cid:
            if run_start is None:
                run_start = date
        else:
            if run_start is not None:
                runs.append([run_start, date])  # 段止于下一变更日
                run_start = None
    if run_start is not None:
        runs.append([run_start, None])  # 开放段
    return runs


def _title_ref(period: TitlePeriod) -> EntityRef:
    """把任期转成轻量 EntityRef（用于 relatedTitles / 证据面板）。"""
    return EntityRef(
        id=period.titleId,
        name=period.name,
        type="title",
        resolved=period.name != period.titleId,
        sourcePath=period.sourcePath,
    )


class TitleReignExtractor:
    """从 titles.json 提取单个角色的头衔与统治经历（输出契约 TitlePeriod[]）。"""

    def __init__(
        self,
        loc: Optional[LocalizationLoader] = None,
        resolver: Optional[ReferenceResolver] = None,
    ) -> None:
        self.loc = loc
        self.resolver = resolver

    def _title_name(self, entry: dict) -> str:
        key = entry.get("key") or ""
        name = entry.get("name") or ""
        if name and entry.get("name_source") == "save":
            return name  # 存档直书可读名（真实存档 title_name_data.name 为中文）
        # 实体索引（可能含 loc/def 解析后的可读名）优先于裸 key。
        if self.resolver is not None:
            ref = self.resolver.resolve("title", key)
            if ref.resolved:
                return ref.name
        if self.loc and key:
            resolved = self.loc.resolve(key)
            if resolved:
                return resolved
        return name or key  # 不伪造

    def _periods_by_holder(self, entry: dict) -> dict[str, list[TitlePeriod]]:
        """单头衔 → 各 holder 的任期段聚合（extract 与 TitleProfileIndex 共用，避免两套逻辑）。

        现任 holder 即使不在 history 中也产生一段（start=None，诚实留空）。
        """
        key = entry.get("key") or ""
        if not key:
            return {}
        name = self._title_name(entry)
        tier = _tier_of(entry.get("tier"))
        src = f"landed_titles/{key}"
        history = entry.get("history") or []
        current = str(entry.get("holder_id") or "")
        holders: set[str] = {
            str(h["holder_id"]) for h in history if h.get("holder_id") is not None
        }
        if current:
            holders.add(current)
        out: dict[str, list[TitlePeriod]] = {}
        for cid in holders:
            is_current = current == cid
            runs = _reign_runs(history, cid)
            if is_current and not runs:
                # 现任但 history 无该角色段（如 history 为空）→ 起点未知，诚实置空。
                out.setdefault(cid, []).append(
                    TitlePeriod(
                        titleId=key,
                        name=name,
                        tier=tier,
                        start=None,
                        end=None,
                        isCurrent=True,
                        sourcePath=src,
                    )
                )
                continue
            for start, end in runs:
                # 仅"当前持有者"的开放段标 isCurrent=True；其余（含异常开放段）为 False。
                is_open = end is None and is_current
                out.setdefault(cid, []).append(
                    TitlePeriod(
                        titleId=key,
                        name=name,
                        tier=tier,
                        start=start,
                        end=None if is_open else end,
                        isCurrent=is_open,
                        sourcePath=src,
                    )
                )
        return out

    def extract(self, raw_titles: dict, character_id: str) -> list[TitlePeriod]:
        cid = str(character_id)
        periods: list[TitlePeriod] = []
        for entry in raw_titles.get("titles") or []:
            periods.extend(self._periods_by_holder(entry).get(cid, []))
        # 未知 start 排最后，其余按 CK3 日期数值升序。
        periods.sort(key=lambda p: (_date_key(p.start), p.titleId))
        return periods


@dataclass
class TitleSummaryBits:
    """供 CharacterSummary 合并的头衔摘要位（由 TitleProfileIndex 产出）。"""

    primary: Optional[EntityRef] = None
    highestTier: Optional[TitleTier] = None
    isRuler: bool = False
    warningCount: int = 0


def build_semantic_title_events(
    character_id: str,
    character_name: str,
    periods: list[TitlePeriod],
    classifications: dict[str, TitleClassification],
    raw_entries: dict[str, dict],
) -> tuple[list, list[TimelineEvent]]:
    """3C.3：把任期聚合为「按语义类型拆分」的历史语义事件 + 时间线事件。

    取代旧版 build_title_events：
      - 同一天获得主权王国 + 官职 + 机构 → 拆分为 identity_transition /
        institution_transition 等多条（不再把一次征服/继承的所有头衔混成一条）；
      - 领地获得原因除 kind=created 直接证实为「创建」外一律 UNKNOWN，
        并带「不得推断因果」叙事约束（时间相近绝不推断继承/征服/册封）；
      - 历史语义事件与时间线事件同源产出（同一批变更，两种视图）。
    返回 (historical_semantic_events, timeline_events)，与
    HistoricalEventSemanticBuilder.build 的返回顺序一致。
    """
    builder = HistoricalEventSemanticBuilder(
        character_id, character_name, classifications, raw_entries
    )
    return builder.build(periods)


class TitleProfileIndex:
    """M3：从 titles.json 一次性反解全部人物的头衔聚合索引。

    供列表页摘要（primaryTitle / highestTitleTier / isRuler / warning 计数）
    与人物页档案（titles[] + 时间线事件 + warnings）复用，避免每次请求
    重复扫描 titles.json（O(人物 × 头衔)）。
    """

    def __init__(
        self,
        raw_titles: dict,
        loc: Optional[LocalizationLoader] = None,
        resolver: Optional[ReferenceResolver] = None,
        semantic_registry: Optional[TitleSemanticRuleRegistry] = None,
        active_mod_ids: Optional[list[str]] = None,
    ) -> None:
        self._extractor = TitleReignExtractor(loc=loc, resolver=resolver)
        # 3C.2：头衔语义分类（titleId -> TitleClassification），一次反解全存档缓存。
        self._classifications: dict[str, TitleClassification] = {}
        # 3C.3：原始 titles.json 条目（titleId -> entry，供因果解析与展示名）。
        self._raw_entries: dict[str, dict] = {}
        self._active_mod_files: list[dict] = []
        # character_id -> 全部任期（现任 + 过往）。
        self._periods: dict[str, list[TitlePeriod]] = {}
        # character_id -> 头衔相关证据告警（冲突 / 多同级推断）。
        self._warnings: dict[str, list[EvidenceWarning]] = {}
        # character_id -> 摘要位（惰性计算后缓存）。
        self._bits: dict[str, TitleSummaryBits] = {}
        self._build(raw_titles, loc=loc, semantic_registry=semantic_registry, active_mod_ids=active_mod_ids)

    def _build(
        self,
        raw_titles: dict,
        loc: Optional[LocalizationLoader] = None,
        semantic_registry: Optional[TitleSemanticRuleRegistry] = None,
        active_mod_ids: Optional[list[str]] = None,
    ) -> None:
        classifier = TitleSemanticClassifier(
            semantic_registry or TitleSemanticRuleRegistry(),
            TitleDisplayResolver(loc=loc),
        )
        entries = [e for e in raw_titles.get("titles") or [] if e.get("key")]
        self._classifications, self._active_mod_files = classifier.classify_all(
            entries, active_mod_ids=active_mod_ids
        )
        self._raw_entries = {str(e.get("key")): e for e in entries}
        for entry in entries:
            key = entry.get("key") or ""
            if not key:
                continue
            by_holder = self._extractor._periods_by_holder(entry)
            for cid, ps in by_holder.items():
                self._periods.setdefault(cid, []).extend(ps)
            # 冲突检测：顶层 holder 与 history 末项 holder 不一致 → warning，不静默覆盖。
            current = str(entry.get("holder_id") or "")
            history = entry.get("history") or []
            if current and history:
                last = history[-1].get("holder_id")
                if last is not None and str(last) != current:
                    self._add_warning(
                        current,
                        EvidenceWarning(
                            code="title_holder_conflict",
                            message=(
                                f"头衔 {key} 顶层 holder({current}) 与 history 末项 "
                                f"holder({last}) 不一致；以顶层 holder 认定现任，不静默覆盖。"
                            ),
                            severity=WarningSeverity.WARNING,
                            sourcePath=f"landed_titles/{key}",
                        ),
                    )
        for ps in self._periods.values():
            ps.sort(key=lambda p: (_date_key(p.start), p.titleId))

    def _add_warning(self, cid: str, w: EvidenceWarning) -> None:
        self._warnings.setdefault(cid, []).append(w)

    # ---- 3C：语义分类访问器 ------------------------------------------------
    def classifications(self) -> dict[str, TitleClassification]:
        """全存档头衔语义分类（titleId -> TitleClassification）。"""
        return self._classifications
    def raw_entries(self) -> dict[str, dict]:
        """原始 titles.json 条目（titleId -> entry，供因果/展示名解析）。"""
        return self._raw_entries

    def active_mod_files(self) -> list[dict]:
        return self._active_mod_files

    def periods(self, character_id: str) -> list[TitlePeriod]:
        return list(self._periods.get(str(character_id)) or [])

    def warnings(self, character_id: str) -> list[EvidenceWarning]:
        return list(self._warnings.get(str(character_id)) or [])

    def ruler_ids(self) -> set[str]:
        """当前持有至少一个头衔的人物 id 集合（供 rulerOnly 筛选 / isRuler 判定）。"""
        return {
            cid
            for cid, ps in self._periods.items()
            if any(p.isCurrent for p in ps)
        }

    def holder_ids_for_title(self, title_query: str) -> set[str]:
        """按头衔名（含 key 与解析后名）反查持有者 id 集合（M5 搜索）。

        子串匹配（不区分大小写）：`titleQuery=幽蓟` 或 `k_youji` 均可命中。
        返回空集表示无匹配（调用方应据此过滤为空，而不是返回全部）。
        """
        needle = (title_query or "").strip().lower()
        if not needle:
            return set()
        out: set[str] = set()
        for cid, ps in self._periods.items():
            for p in ps:
                for n in (p.name, p.titleId):
                    if n and needle in str(n).lower():
                        out.add(cid)
                        break
        return out

    def primary_bits(self, character_id: str) -> TitleSummaryBits:
        """按需计算摘要位（primaryTitle / highestTier / isRuler / warning 计数）。

        规则（Phase 2B 第十二节）：
          1) 只依据“当前持有”的头衔（top-level holder）。
          2) 取当前头衔中等级最高者为主头衔。
          3) 多个同级 → 按 id 稳定顺序取一个，并产生 inferred warning。
          4) 等级全部未知 → 无可靠依据，主头衔留空（不强行标记 confirmed）。
        """
        cid = str(character_id)
        cached = self._bits.get(cid)
        if cached is not None:
            return cached
        current = [p for p in self._periods.get(cid, []) if p.isCurrent]
        if not current:
            bits = TitleSummaryBits()
        else:
            best = max(current, key=lambda p: _TIER_RANK.get(p.tier, -1))
            best_tier = best.tier
            chosen: Optional[TitlePeriod] = best
            warn_count = 0
            if best_tier is None:
                # 全部当前头衔等级未知 → 无可靠主头衔依据。
                chosen = None
                self._add_warning(
                    cid,
                    EvidenceWarning(
                        code="primary_title_unresolved",
                        message=(
                            "该人物持有头衔，但头衔等级无法从 key 前缀推导，"
                            "无法判定主头衔（不强行推断）。"
                        ),
                        severity=WarningSeverity.INFO,
                    ),
                )
            else:
                ties = [p for p in current if p.tier == best_tier]
                if len(ties) > 1:
                    chosen = sorted(ties, key=lambda p: p.titleId)[0]
                    self._add_warning(
                        cid,
                        EvidenceWarning(
                            code="primary_title_inferred",
                            message=(
                                f"同时持有多个 {best_tier.value} 级头衔"
                                f"（{'、'.join(sorted(p.titleId for p in ties))}），"
                                f"主头衔按 id 稳定顺序取 {chosen.titleId}（推断）。"
                            ),
                            severity=WarningSeverity.INFO,
                            sourcePath=chosen.sourcePath,
                        ),
                    )
                    warn_count = 1
            primary = (
                _title_ref(chosen) if chosen is not None else None
            )
            bits = TitleSummaryBits(
                primary=primary,
                highestTier=best_tier,
                isRuler=True,
                warningCount=warn_count,
            )
        self._bits[cid] = bits
        return bits
