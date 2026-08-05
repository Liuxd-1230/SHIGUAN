#!/usr/bin/env python3
"""Phase 3C.7：梁开 997.8.28 存档重新审计（7 个问题的取证脚本）。

只做信息取证，输出 JSON + 人类可读摘要；绝不修改代码/契约。
数据来源：data/audit/liangkai-997/melt/（一次 prepare --with-melted 的产物）。

回答交接文档第九节的 7 个问题：
  1. 梁开成为最高统治者时的 raw type 是什么。
  2. 唐 / h_china / e_jinwang / e_liangnan / e_zhongyuan 等 title 的关系。
  3. 三省六部 title 是 appointment / appointment_succession / granted 还是其他。
  4. 同日大量 title 变化是否包含多种不同 cause。
  5. 修复前后梁开历史事件数量变化。
  6. 修复前后确定性史料摘要变化。
  7. 修复前后 AI Prompt 中事实数量变化。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (
    ROOT / "apps" / "server",
    ROOT / "packages" / "save-schema" / "py",
    ROOT / "packages" / "biography-engine" / "py",
):
    sys.path.insert(0, str(_p))

from app.services.title_reign_extractor import TitleProfileIndex, build_semantic_title_events  # noqa: E402
from biography_engine.historical_events import HistoricalEventSemanticBuilder  # noqa: E402

MELT = ROOT / "data" / "audit" / "liangkai-997" / "melt"
PID = "50366145"  # 梁开（meta.player_id / played_character.character）


def load_titles() -> dict:
    return json.loads((MELT / "titles.json").read_text(encoding="utf-8"))


def load_character(pid: str) -> dict:
    for line in (MELT / "characters.ndjson").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if str(rec.get("id")) == str(pid):
            return rec
    raise KeyError(pid)


def analyze_liangkai() -> dict:
    titles_doc = load_titles()
    titles = titles_doc["titles"]
    idx = TitleProfileIndex(titles_doc)
    periods = idx.periods(PID)
    classifications = idx.classifications()
    raw_entries = idx.raw_entries()

    # ---- Q1：梁开成为最高统治者时的 raw type ----
    # 最高头衔 = 当前持有的 empire 级头衔中，通过 history 找到梁开首次持有该头衔的条目。
    held = [t for t in titles if str(t.get("holder_id")) == PID]
    top = [t for t in held if t.get("tier") in ("empire",)]
    q1: list[dict] = []
    for t in sorted(top, key=lambda x: str(x.get("key"))):
        h = t.get("history") or []
        first = next((e for e in h if str(e.get("holder_id")) == PID), None)
        q1.append(
            {
                "key": t.get("key"),
                "name": t.get("name"),
                "first_hold_date": first.get("date") if first else None,
                "raw_type": first.get("raw_type") if first else None,
                "kind": first.get("kind") if first else None,
                "history_len": len(h),
            }
        )

    # ---- Q2：唐 / h_china / e_jinwang / e_liangnan / e_zhongyuan 关系 ----
    q2_keys = [
        "h_china", "e_jinwang", "e_liangnan", "e_zhongyuan",
        "e_liangyi", "k_youji",
    ]
    q2: list[dict] = []
    by_key = {str(t.get("key")): t for t in titles}
    for k in q2_keys:
        t = by_key.get(k)
        if t is None:
            q2.append({"key": k, "present": False})
            continue
        djl = t.get("de_jure_liege_id")
        djl_key = next(
            (str(x.get("key")) for x in titles if str(x.get("title_id")) == str(djl)),
            None,
        ) if djl else None
        q2.append(
            {
                "key": k,
                "title_id": t.get("title_id"),
                "name": t.get("name"),
                "tier": t.get("tier"),
                "holder": t.get("holder_id"),
                "de_jure_liege_id": djl,
                "de_jure_liege_key": djl_key,
                "history_len": len(t.get("history") or []),
                "is_liangkai_held": str(t.get("holder_id")) == PID,
            }
        )

    # ---- Q3：三省六部 title raw_type 分布 ----
    # 三省六部：中书省/门下省/尚书省 + 吏部/户部/礼部/兵部/刑部/工部。
    shengbu_keys = [
        "e_minister_shizheng", "e_minister_zhongshu", "e_minister_menxia",
        "e_minister_shangshu", "e_minister_li", "e_minister_hu",
        "e_minister_li2", "e_minister_bing", "e_minister_xing", "e_minister_gong",
    ]
    # 更稳的口径：key 含 minister 或 名称含 部/省。
    shengbu = [t for t in titles if "minister" in str(t.get("key"))]
    q3_census: Counter = Counter()
    q3_total = 0
    for t in shengbu:
        for e in t.get("history") or []:
            rt = e.get("raw_type")
            if rt is not None:
                q3_census[rt] += 1
                q3_total += 1
    q3: dict = {
        "title_count": len(shengbu),
        "history_total": sum(len(t.get("history") or []) for t in shengbu),
        "explicit_raw_type_total": q3_total,
        "raw_type_census": dict(sorted(q3_census.items())),
        "titles_sample": [
            {"key": t.get("key"), "name": t.get("name"), "holder": t.get("holder_id"),
             "history_len": len(t.get("history") or [])}
            for t in shengbu[:15]
        ],
    }

    # ---- Q4：同日大量 title 变化是否含多种 cause ----
    # 对梁开全部 title gain：按 (date, semanticType) 分组，统计每组 distinct raw_type。
    builder = HistoricalEventSemanticBuilder(PID, "梁开", classifications, raw_entries)
    sem_events, timeline_events = builder.build(periods)
    # 用原始 title change 口径：每个任期段的 start 日 + 对应 history 条目 raw_type。
    q4_gain_changes: list[dict] = []
    for t in held:
        key = str(t.get("key"))
        entry = raw_entries.get(key) or {}
        hist = entry.get("history") or []
        for e in hist:
            if str(e.get("holder_id")) == PID:
                q4_gain_changes.append(
                    {
                        "date": e.get("date"),
                        "key": key,
                        "name": (entry.get("name") or key),
                        "raw_type": e.get("raw_type"),
                        "kind": e.get("kind"),
                    }
                )
    by_date = defaultdict(list)
    for g in q4_gain_changes:
        by_date[str(g["date"])].append(g)
    multi_days = []
    for date, changes in sorted(by_date.items(), key=lambda kv: kv[0]):
        rts = {c["raw_type"] for c in changes}
        kinds = {c["kind"] for c in changes}
        if len(changes) > 1 and (len(rts) > 1 or len(kinds) > 1):
            multi_days.append(
                {
                    "date": date,
                    "change_count": len(changes),
                    "raw_types": sorted(rts, key=str),
                    "kinds": sorted(kinds, key=str),
                    "titles": [f"{c['name']}({c['raw_type']})" for c in changes],
                }
            )
    q4: dict = {
        "gain_change_total": len(q4_gain_changes),
        "distinct_dates": len(by_date),
        "multi_cause_days": multi_days[:12],
        "multi_cause_day_count": len(multi_days),
    }

    # ---- Q5：修复前后梁开历史事件数量变化 ----
    # 新（3C.7）：同日不同 cause 拆分 → 事件数 = sem_events 数。
    # 旧（聚合只取第一个 title 的 cause）：按 (date, semanticType, direction) 合并成一条。
    new_events = list(sem_events)
    old_group_key = defaultdict(int)
    for e in new_events:
        k = (e.date, e.semanticType.value)
        old_group_key[k] += 1
    old_events = len(old_group_key)
    q5: dict = {
        "new_historical_events": len(new_events),
        "old_merged_events_approx": old_events,
        "delta": len(new_events) - old_events,
        "new_timeline_events": len(timeline_events),
    }

    # ---- Q6：修复前后确定性史料摘要变化 ----
    # 抽样对比：取 952.8.16 / 955.1.22 等大日，列出新语义事件的标题/描述。
    big_dates = sorted(
        {str(c["date"]) for c in q4_gain_changes}, key=lambda s: s
    )[-5:]
    q6: dict = {
        "big_dates": big_dates,
        "new_event_titles_by_date": {
            d: [
                {
                    "title": e.semanticType.value,
                    "description": e.summary,
                    "cause": e.acquisitionCause.value if e.acquisitionCause else None,
                    "relatedTitleIds": list(e.relatedTitleIds),
                }
                for e in new_events
                if str(e.date) == d
            ]
            for d in big_dates
        },
    }

    # ---- Q7：修复前后 AI Prompt 事实数量变化 ----
    # 事实数量 ≈ 输入压缩档案的事件条目数（新语义事件拆分后更多）。
    try:
        from biography_engine.compressor import compress_profile
        from app.services.character_extractor import to_profile
        stub = load_character(PID)
        profile = to_profile(stub, title_events=timeline_events)
        compressed = compress_profile(
            profile, max_events=200, include_inferred=True, include_uncertain=True
        )
        q7 = {
            "compressed_event_count": len(compressed.selectedEvents),
            "note": "AI Prompt 输入事实 ≈ 压缩档案 selectedEvents（拆分后逐条带 cause，条目数增加）。",
        }
    except Exception as exc:  # noqa: BLE001
        q7 = {"error": str(exc)}

    return {
        "q1_liangkai_top_title": q1,
        "q2_title_relations": q2,
        "q3_shengbu": q3,
        "q4_multi_cause_days": q4,
        "q5_event_count_before_after": q5,
        "q6_summary_before_after": q6,
        "q7_prompt_facts": q7,
    }


def main() -> int:
    out = analyze_liangkai()
    out_path = ROOT / "data" / "audit" / "liangkai-997" / "liangkai-7-questions.json"
    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已写出：{out_path}")
    print()
    print("=== Q1 梁开最高头衔首持（raw type）===")
    for q in out["q1_liangkai_top_title"]:
        print(f"  {q['key']} {q['name']} @{q['first_hold_date']} raw={q['raw_type']} kind={q['kind']}")
    print()
    print("=== Q2 关键头衔关系 ===")
    for q in out["q2_title_relations"]:
        print(
            f"  {q.get('key')}: id={q.get('title_id')} tier={q.get('tier')} "
            f"holder={q.get('holder')} djl={q.get('de_jure_liege_key')} hist={q.get('history_len')}"
        )
    print()
    print("=== Q3 三省六部 raw_type 分布 ===")
    print(" ", out["q3_shengbu"]["raw_type_census"])
    print()
    print("=== Q4 同日多 cause ===")
    q4 = out["q4_multi_cause_days"]
    print(f"  gain 变更总数: {q4['gain_change_total']}；多 cause 日: {q4['multi_cause_day_count']}")
    for d in q4["multi_cause_days"][:6]:
        print(f"  {d['date']}: {d['change_count']} 条 -> {d['raw_types']}")
    print()
    print("=== Q5 事件数量变化 ===")
    print(" ", out["q5_event_count_before_after"])
    print()
    print("=== Q6 摘要对照（最后 5 个大日）===")
    for d, evs in out["q6_summary_before_after"]["new_event_titles_by_date"].items():
        print(f"  [{d}]")
        for e in evs:
            print(f"    - {e['title']} | cause={e['cause']} | {e['description'][:60]}")
    print()
    print("=== Q7 Prompt 事实数量 ===")
    print(" ", out["q7_prompt_facts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
