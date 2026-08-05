#!/usr/bin/env python3
"""Phase 3C.1 人工验收脚本：16 类角色样本 + 真实存档双样本。

用法（项目根目录）：
  python scripts/phase3c_acceptance.py
      # 仅跑 16 类脱敏样本
  python scripts/phase3c_acceptance.py data/cache/<saveId>/<sig> [...]
      # 追加真实存档缓存目录的语义层抽查（直接读受控缓存，不重新 melt）

退出码：0 = 全部通过；1 = 有失败（打印明细）。
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "server"))
sys.path.insert(0, str(ROOT / "packages" / "biography-engine" / "py"))
sys.path.insert(0, str(ROOT / "packages" / "save-schema" / "py"))
sys.path.insert(0, str(ROOT / "packages" / "biography-engine" / "py" / "tests"))

from phase3c_fixtures import CASES, check_case  # noqa: E402
from biography_engine.historical_events import HistoricalEventSemanticBuilder  # noqa: E402
from biography_engine.title_semantics import (  # noqa: E402
    PrimaryIdentityResolver,
    TitleSemanticRuleRegistry,
)
from app.services.title_reign_extractor import TitleProfileIndex  # noqa: E402

CONFIG_DIR = ROOT / "config" / "title-semantics"
# 身份表述中禁止出现的 tier 爵位硬编码词。
HARDCODED = ("皇帝", "国王", "公爵", "伯爵", "男爵", "皇帝陛下")


def verify_sample(cache_dir: Path) -> None:
    """真实存档语义层抽查：分类分布 + 无 tier 硬编码 + 不推断因果。"""
    raw = json.load(open(cache_dir / "titles.json", encoding="utf-8"))
    ts = raw.get("titles") or []
    registry = TitleSemanticRuleRegistry(CONFIG_DIR)
    idx = TitleProfileIndex(raw, semantic_registry=registry)
    cls = idx.classifications()

    dist = Counter(c.semanticType.value for c in cls.values())
    ruler_ids = idx.ruler_ids()
    print(f"  [{cache_dir.parent.name}] titles={len(ts)} 现任统治者={len(ruler_ids)}")
    print(f"    语义类型分布: {dict(dist)}")

    minister = [c for tid, c in cls.items() if str(tid).startswith("e_minister_")]
    bad = [c.titleId for c in minister if c.semanticType.value != "realm_institution"]
    assert not bad, f"e_minister_* 分类错误: {bad[:5]}"

    n_bad = 0
    for cid in list(ruler_ids)[:6]:
        identity = PrimaryIdentityResolver(cls).resolve(idx.periods(cid))
        if identity.headlineIdentity:
            for w in HARDCODED:
                if w in identity.headlineIdentity:
                    n_bad += 1
                    print(f"    !! 硬编码疑似: {cid} {identity.headlineIdentity}")
    assert n_bad == 0, "headline 出现 tier 硬编码词"

    n_sem = n_unknown = n_constraint = n_created = 0
    for cid in ruler_ids:
        sem_events, _ = HistoricalEventSemanticBuilder(
            cid, f"p{cid}", cls, idx.raw_entries()
        ).build(idx.periods(cid))
        for e in sem_events:
            n_sem += 1
            if e.acquisitionCause == "unknown":
                n_unknown += 1
                if e.narrativeConstraints:
                    n_constraint += 1
            elif e.acquisitionCause == "creation":
                n_created += 1
    print(
        f"    历史语义事件 {n_sem}；cause=unknown {n_unknown}（带约束 {n_constraint}）；"
        f"cause=creation {n_created}"
    )
    assert n_unknown == n_constraint, "存在 cause=unknown 但缺叙事约束的事件"


def main() -> int:
    print("=== Phase 3C.1 人工验收：16 类角色样本（脱敏合成数据）===")
    all_failures: list[str] = []
    for case in CASES:
        failures = check_case(case)
        status = "PASS" if not failures else "FAIL"
        print(f"  [{status}] {case['id']}：{case['title']}")
        for f in failures:
            print(f"      - {f}")
            all_failures.append(f)

    if all_failures:
        print(f"\n样本断言失败 {len(all_failures)} 条 ✗")
        return 1
    print("\n16 类样本全部通过 ✓")

    real_dirs = [Path(a) for a in sys.argv[1:]]
    if real_dirs:
        print("\n=== Phase 3C 真实存档双样本抽查（不重新 melt）===")
        for d in real_dirs:
            print(f"=== 样本: {d}")
            verify_sample(d)
        print("真实样本抽查全部通过 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
