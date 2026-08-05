"""确定性事实校验器（Phase 3B 第 8 步 + 3C.5）—— 24 条规则。

全部确定性（同输入同输出），**不调用 LLM**。对正文逐章校验，产出
`FactCheckResult`（status + issues）。WARNING/ERROR 级问题 → needs_revision；
仅 INFO 级问题不强制重写。

规则清单（24 条）：
  1  event_id_not_allowed     章节引用了不在该章允许列表的事件（每章只用该章事件）
  2  event_after_death        引用事件日期晚于人物死亡日期
  3  time_reversal            正文日期与本章事件日期明显冲突（早/晚太多）
  4  numeric_id_leak          裸数字人物/头衔 id（≥5 位连续数字）
  5  token_id_leak            tXXXX 占位 token
  6  source_path_leak         存档路径片段（landed_titles/…、character/…、*.json）
  7  internal_enum_leak       内部枚举/键（snake_case 英文如 war_won、title_gain）
  8  punctuation_double       「。。」「；。」等连续标点
  9  inferred_as_fact         本章只引用推断事件却无推断措辞
  10 conflict_as_succession   头衔变更写成「继承」且未引用 succession 事件
  11 defender_as_declared     防御战争写成「宣战/发动战争」
  12 fabricated_dialogue      虚构对白/心理描写（说：「…」/心想/内心）
  13 unverified_quoted_name   引号内人名不在已知档案事实中
  14 unverified_quoted_title  引号内头衔名不在已知头衔中
  15 death_year_mismatch      正文死亡年份与存档死亡日期不符
  16 birth_year_mismatch      正文出生年份与存档出生日期不符
  17 profile_id_leak          正文含人物原始数字 id
  18 model_meta_leak          正文含 JSON/schema/eventIds/prompt 等模型元信息
  19 empty_chapter            章节正文为空
  20 markdown_leak            正文含 markdown 围栏/URL
  # ---- 3C.5 新增 ----
  21 fact_ref_invalid         本章 factIds 为空或指向档案外的事实
  22 cause_inference          存档未记录获得途径却写成继承/征服/册封（违反叙事约束）
  23 peerage_mismatch         非独立最高统治者却写成「国王/皇帝/公爵」等爵位
  24 event_fact_grounding     事件未被任何事实锚定（事件→事实不可追溯）
"""
from __future__ import annotations

import re
from typing import List, Optional, Set

from models import (
    Biography,
    BiographyChapter,
    BiographyOutline,
    CharacterProfile,
    FactCheckIssue,
    FactCheckResult,
    FactCheckStatus,
    WarningSeverity,
)

from .models import CompressedEvent, CompressedProfile

# -- 日期解析 ---------------------------------------------------------------
_DATE_RE = re.compile(r"\b(\d{1,4})\.(\d{1,2})(?:\.(\d{1,2}))?\b")
_YEAR_RE = re.compile(r"(\d{1,4})\s*年")


def _parse_date(s: str) -> Optional[tuple[int, int, int]]:
    m = _DATE_RE.search(s)
    if m:
        return (
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3) or 1),
        )
    m = _YEAR_RE.search(s)
    if m:
        return (int(m.group(1)), 1, 1)
    return None


# -- 技术泄漏模式 -----------------------------------------------------------
_NUMERIC_ID_RE = re.compile(r"(?<![0-9])[0-9]{5,}(?![0-9])")  # 人物/头衔 id
_TOKEN_ID_RE = re.compile(r"\bt[0-9]{4,}\b")
_SOURCE_PATH_RE = re.compile(
    r"landed_titles/|character(_memory_manager)?/|\.ndjson|\.json|history/|"
    r"rawKey|sourcePath|/cache/|D:/|C:/"
)
_ENUM_RE = re.compile(r"\b[a-z]+_[a-z0-9_]+")  # snake_case 内部键
_PUNCT_RE = re.compile(r"[。；，、！？]{2}|；。|。。|，，|、、")
_DIALOGUE_RE = re.compile(r"(?:说|道|曰|心想|暗想|自语|低语|内心)[：:「“]")
_META_RE = re.compile(r"JSON|schema|eventIds|prompt|提示词|模型输出|基于以上")
_MARKDOWN_RE = re.compile(r"```|\[.*\]\(.*\)|^#{1,6}\s|https?://")
_DEATH_WRITE_RE = re.compile(r"宣战|发动战争|主动进攻|出兵攻打|率先发难")

# 推断措辞（出现任一即认为文本已标注推断性质）。
_HEDGE_WORDS = ("推断", "推测", "据推断", "可能", "或为", "大概", "疑似", "相传", "据称")

# 规则 15/16：自述生死年份（前缀 / 后缀两种形态）。
_DEATH_YEAR_PREFIX_RE = re.compile(r"(?:卒于|逝世于|死于|去世于)\s*(\d{1,4})\s*年")
_DEATH_YEAR_SUFFIX_RE = re.compile(r"(\d{1,4})\s*年\s*(?:逝世|去世|卒|身亡|殁)")
_BIRTH_YEAR_PREFIX_RE = re.compile(r"(?:生于|出生于|诞于)\s*(\d{1,4})\s*年")
_BIRTH_YEAR_SUFFIX_RE = re.compile(r"(\d{1,4})\s*年\s*(?:出生|诞生|降生)")

# 3C.5 新增规则的正则。
# 规则 22：因果推断词汇（存档未记录获得途径时出现 → 推断因果）。
_CAUSE_INFERENCE_RE = re.compile(
    r"继承|征服|篡位|篡夺|册封|分封|攻取|攻占|占领|战利|战后所得|以战功|因战获|夺取|吞并"
)
# 规则 23：把身份写成爵位（realmStatus 非独立最高统治者时出现 → 错配）。
_PEERAGE_AS_IDENTITY_RE = re.compile(
    r"(?:成为|自立为|即位为|加冕为|登基为|受封为)(?:.{0,6}?)(?:国王|皇帝|公爵|伯爵|男爵)"
)


class FactChecker:
    """确定性正文事实校验器（20 条规则）。"""

    def check(
        self,
        *,
        chapters: List[BiographyChapter],
        outline: BiographyOutline,
        compressed: CompressedProfile,
        profile: CharacterProfile,
    ) -> FactCheckResult:
        issues: List[FactCheckIssue] = []
        allowed_by_chapter = {c.id: set(c.eventIds) for c in outline.chapters}
        event_by_id = {e.eventId: e for e in compressed.selectedEvents}
        known_names = self._known_names(compressed)
        known_titles = self._known_titles(compressed)

        for ch in chapters:
            allowed = allowed_by_chapter.get(ch.id, set())
            evs = [event_by_id[eid] for eid in ch.eventIds if eid in event_by_id]
            # 规则 1：每章只用该章允许的事件。
            for eid in ch.eventIds:
                if eid not in allowed:
                    issues.append(self._issue(
                        "event_id_not_allowed", WarningSeverity.ERROR,
                        f"章节「{ch.id}」引用了不在该章允许列表的事件 id：{eid}",
                        "只引用该章提纲中列出的事件 id。",
                    ))
            # 规则 19：空正文。
            if not ch.content or not ch.content.strip():
                issues.append(self._issue(
                    "empty_chapter", WarningSeverity.ERROR,
                    f"章节「{ch.id}」正文为空。",
                    "补全该章正文。",
                ))
            # 规则 2：死亡后事件。
            if profile.deathDate:
                dk = _parse_date(profile.deathDate)
                for e in evs:
                    ed = _parse_date(e.date) if e.date else None
                    if ed and dk and ed > dk:
                        issues.append(self._issue(
                            "event_after_death", WarningSeverity.WARNING,
                            f"章节「{ch.id}」引用了死亡日期之后的事件 {e.eventId}（{e.date}）。",
                            "删除死亡后的事件引用。",
                        ))
            # 规则 3：正文日期与本章事件明显冲突（时间倒置 / 超前）。
            text_dates = [
                d for d in (_parse_date(m.group(0)) for m in _DATE_RE.finditer(ch.content)) if d
            ]
            text_dates += [
                d for d in (_parse_date(m.group(0)) for m in _YEAR_RE.finditer(ch.content)) if d
            ]
            event_dates = [d for d in (_parse_date(e.date) if e.date else None for e in evs) if d]
            if event_dates:
                lo = min(event_dates)
                hi = max(event_dates)
                for td in text_dates:
                    if td[0] < lo[0] - 3:
                        issues.append(self._issue(
                            "time_reversal", WarningSeverity.WARNING,
                            f"章节「{ch.id}」提到 {td[0]} 年，早于本章最早事件（{lo[0]} 年）过多，可能时间倒置。",
                            "核对正文日期与本章事件时间。",
                        ))
                        break
                    if td[0] > hi[0] + 3:
                        issues.append(self._issue(
                            "time_reversal", WarningSeverity.WARNING,
                            f"章节「{ch.id}」提到 {td[0]} 年，晚于本章最晚事件（{hi[0]} 年）过多。",
                            "核对正文日期与本章事件时间。",
                        ))
                        break
            # 规则 4/5/6/7/8/12/18/20：技术泄漏与文风。
            self._leak_checks(ch, issues)
            # 规则 9：推断当事实。
            if evs and all(e.confidence.value == "inferred" for e in evs):
                if not any(h in ch.content for h in _HEDGE_WORDS):
                    issues.append(self._issue(
                        "inferred_as_fact", WarningSeverity.WARNING,
                        f"章节「{ch.id}」只依据推断事件，但正文没有推断措辞（据推断/可能/推测）。",
                        "以「据推断」等方式如实标注推断性质。",
                    ))
            # 规则 10：记录冲突写成继承。
            has_succession = any(e.type == "succession" for e in evs)
            has_title_gain = any(e.type == "title_gain" for e in evs)
            if has_title_gain and not has_succession and "继承" in ch.content:
                issues.append(self._issue(
                    "conflict_as_succession", WarningSeverity.WARNING,
                    f"章节「{ch.id}」将头衔变更写成「继承」，但该变更记录为 title_gain（存档未直述为继承）。",
                    "按存档记录写「获得/持有」，不写继承。",
                ))
            # 规则 11：防御战争写成主动宣战。
            if any(e.type == "war" and "防御" in (e.title or "") for e in evs):
                if _DEATH_WRITE_RE.search(ch.content):
                    issues.append(self._issue(
                        "defender_as_declared", WarningSeverity.ERROR,
                        f"章节「{ch.id}」将防御战争写成「宣战/主动进攻」。",
                        "防御战争应写「卷入/抵御」，绝不写主动宣战。",
                    ))
            # 规则 13/14：引号内人名/头衔必须在已知事实中。
            for name in _QUOTED_RE.findall(ch.content):
                if name in known_names:
                    continue
                if name in known_titles:
                    continue
                issues.append(self._issue(
                    "unverified_quoted_name", WarningSeverity.WARNING,
                    f"章节「{ch.id}」引用了档案中查不到的人/头衔名「{name}」。",
                    "只写档案证据中出现的人名与头衔名。",
                ))
            # 规则 15/16：正文自述生死年份与档案不符。
            if profile.deathDate:
                dk = _parse_date(profile.deathDate)
                if dk:
                    for m in _DEATH_YEAR_PREFIX_RE.finditer(ch.content):
                        if int(m.group(1)) != dk[0]:
                            issues.append(self._issue(
                                "death_year_mismatch", WarningSeverity.WARNING,
                                f"章节「{ch.id}」自述死于 {m.group(1)} 年，与存档死亡日期 {profile.deathDate} 不符。",
                                "按存档死亡日期写。",
                            ))
                    for m in _DEATH_YEAR_SUFFIX_RE.finditer(ch.content):
                        if int(m.group(1)) != dk[0]:
                            issues.append(self._issue(
                                "death_year_mismatch", WarningSeverity.WARNING,
                                f"章节「{ch.id}」自述死于 {m.group(1)} 年，与存档死亡日期 {profile.deathDate} 不符。",
                                "按存档死亡日期写。",
                            ))
            if profile.birthDate:
                bk = _parse_date(profile.birthDate)
                if bk:
                    for m in _BIRTH_YEAR_PREFIX_RE.finditer(ch.content):
                        if int(m.group(1)) != bk[0]:
                            issues.append(self._issue(
                                "birth_year_mismatch", WarningSeverity.WARNING,
                                f"章节「{ch.id}」自述生于 {m.group(1)} 年，与存档出生日期 {profile.birthDate} 不符。",
                                "按存档出生日期写。",
                            ))
                    for m in _BIRTH_YEAR_SUFFIX_RE.finditer(ch.content):
                        if int(m.group(1)) != bk[0]:
                            issues.append(self._issue(
                                "birth_year_mismatch", WarningSeverity.WARNING,
                                f"章节「{ch.id}」自述生于 {m.group(1)} 年，与存档出生日期 {profile.birthDate} 不符。",
                                "按存档出生日期写。",
                            ))

            # ---- 3C.5 新增规则：事实引用 / 事实锚定 / 因果推断 / 爵位错配 ----
            # 规则 21：本章 factIds 必须非空且全部指向压缩档案中的事实。
            fact_ids = {f.id for f in compressed.facts}
            for fid in ch.factIds or []:
                if fid not in fact_ids:
                    issues.append(self._issue(
                        "fact_ref_invalid", WarningSeverity.ERROR,
                        f"章节「{ch.id}」引用了档案中不存在的事实 id：{fid}。",
                        "只引用「事实（id 列表）」中列出的事实。",
                    ))
            if not (ch.factIds or []):
                issues.append(self._issue(
                    "fact_ref_invalid", WarningSeverity.WARNING,
                    f"章节「{ch.id}」没有关联任何事实 id（factIds 为空）。",
                    "由事件回填本章事实（identity + 事件锚定事实）。",
                ))
            # 规则 24：每个 eventId 必须被至少一条事实锚定（事件→事实可追溯）。
            fact_by_event: dict[str, str] = {}
            for f in compressed.facts:
                for eid in f.sourceEventIds or []:
                    fact_by_event.setdefault(eid, f.id)
            for eid in ch.eventIds:
                if eid not in fact_by_event:
                    issues.append(self._issue(
                        "event_fact_grounding", WarningSeverity.WARNING,
                        f"章节「{ch.id}」引用的事件 {eid} 没有被任何事实锚定。",
                        "确保该事件存在于压缩档案事实集中。",
                    ))
            # 规则 22：获得原因未知却写成继承/征服/册封等因果。
            unknown_cause_events = [
                ev
                for ev in (compressed.historicalEvents or [])
                if ev.acquisitionCause is not None
                and ev.acquisitionCause.value == "unknown"
                and ev.date in {e.date for e in evs}
            ]
            if unknown_cause_events and _CAUSE_INFERENCE_RE.search(ch.content):
                issues.append(self._issue(
                    "cause_inference", WarningSeverity.ERROR,
                    f"章节「{ch.id}」把存档未记录途径的领地获得写成了"
                    "继承/征服/册封等具体原因（违反叙事约束）。",
                    "按档案写「获得/持有」，不推断因果。",
                ))
            # 规则 23：身份表述写成爵位（与 realmStatus 不符）。
            if compressed.identity.realmStatus not in (None, "independent_ruler"):
                if _PEERAGE_AS_IDENTITY_RE.search(ch.content):
                    issues.append(self._issue(
                        "peerage_mismatch", WarningSeverity.WARNING,
                        f"章节「{ch.id}」把非独立最高统治者的身份写成了"
                        "「国王/皇帝/公爵」等爵位（headlineIdentity 用游戏原生头衔名）。",
                        "按档案 headlineIdentity / realmStatus 表述身份。",
                    ))

        if not issues:
            return FactCheckResult(status=FactCheckStatus.PASS, issues=[])
        status = (
            FactCheckStatus.NEEDS_REVISION
            if any(i.severity in (WarningSeverity.WARNING, WarningSeverity.ERROR) for i in issues)
            else FactCheckStatus.PASS
        )
        return FactCheckResult(status=status, issues=issues)

    # -- 内部 ---------------------------------------------------------------
    def _leak_checks(self, ch: BiographyChapter, issues: List[FactCheckIssue]) -> None:
        c = ch.content or ""
        checks = [
            ("numeric_id_leak", WarningSeverity.ERROR, _NUMERIC_ID_RE.search(c),
             "正文不应出现裸数字人物/头衔 id。", "删除数字 id，改用档案中的可读名。"),
            ("token_id_leak", WarningSeverity.ERROR, _TOKEN_ID_RE.search(c),
             "正文不应出现 tXXXX 占位 token。", "删除占位 token。"),
            ("source_path_leak", WarningSeverity.ERROR, _SOURCE_PATH_RE.search(c),
             "正文不应出现存档内部路径片段。", "删除路径片段。"),
            ("internal_enum_leak", WarningSeverity.WARNING, _ENUM_RE.search(c),
             "正文不应出现内部枚举/键（snake_case 英文）。", "用中文自然语言表述。"),
            ("punctuation_double", WarningSeverity.WARNING, _PUNCT_RE.search(c),
             "正文出现「。。」「；。」等连续标点。", "修正标点。"),
            ("fabricated_dialogue", WarningSeverity.ERROR, _DIALOGUE_RE.search(c),
             "正文出现虚构对白/心理描写（禁止）。", "删除对白与内心活动，只写有据事实。"),
            ("model_meta_leak", WarningSeverity.WARNING, _META_RE.search(c),
             "正文不应出现 JSON/schema/prompt 等模型元信息。", "删除元信息。"),
            ("markdown_leak", WarningSeverity.WARNING, _MARKDOWN_RE.search(c),
             "正文不应出现 markdown 围栏/链接/标题标记。", "删除 markdown 标记。"),
        ]
        for rule, sev, hit, msg, fix in checks:
            if hit:
                issues.append(self._issue(rule, sev, f"章节「{ch.id}」{msg}", fix))

    def _known_names(self, compressed: CompressedProfile) -> Set[str]:
        names: Set[str] = set()
        if compressed.identity.displayName:
            names.add(compressed.identity.displayName)
        for block in (
            compressed.family,
            compressed.relationships,
        ):
            for f in block:
                name = f.split("：", 1)[-1].split("、")[0].strip("（）() ")
                if name:
                    names.add(name)
        for r in compressed.relatives:
            names.add(r.name)
        for e in compressed.selectedEvents:
            for n in e.relatedNames:
                names.add(n)
        return names

    def _known_titles(self, compressed: CompressedProfile) -> Set[str]:
        titles: Set[str] = set()
        for name in compressed.territorialDomain.currentMajorTerritories:
            titles.add(name)
        for name in (
            compressed.personalOffices
            + compressed.realmInstitutions
            + compressed.religiousOffices
            + compressed.honors
            + compressed.claims
        ):
            titles.add(name)
        if compressed.identity.primaryRealmTitle:
            titles.add(compressed.identity.primaryRealmTitle)
        if compressed.identity.primaryOffice:
            titles.add(compressed.identity.primaryOffice)
        for ev in compressed.historicalEvents:
            titles.add(ev.summary)
        return titles

    @staticmethod
    def _issue(rule: str, severity: WarningSeverity, message: str, fix: str) -> FactCheckIssue:
        return FactCheckIssue(rule=rule, severity=severity, message=message, suggestedFix=fix)


# 引号内名称（中文书名号/引号两种形态）。
_QUOTED_RE = re.compile(r"[「『]([^」』]{1,24})[」』]")

# 便捷入口：对整本传记校验（Biography 已含 chapter.eventIds）。
def check_biography(
    biography: Biography,
    *,
    outline: BiographyOutline,
    compressed: CompressedProfile,
    profile: CharacterProfile,
) -> FactCheckResult:
    return FactChecker().check(
        chapters=biography.chapters,
        outline=outline,
        compressed=compressed,
        profile=profile,
    )
