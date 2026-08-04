import type { EntityRef, TitlePeriod, TitleTier, TitleStatus } from "@shiguan/save-schema";

/**
 * 由 TitlePeriod[] 确定性推导主头衔摘要位（P0：顶部头衔与 titles 面板同源）。
 *
 * 与后端 `TitleProfileIndex.primary_bits`（apps/server/app/services/title_reign_extractor.py）
 * 保持同一套规则：
 *   1) 只依据「当前持有」的头衔（isCurrent）；
 *   2) 取当前头衔中等级最高者为主头衔（barony < county < duchy < kingdom < empire）；
 *   3) 多个同级 → 按 titleId 稳定顺序取一个（确定性）；
 *   4) 等级全部未知 → 无可靠依据，主头衔留空，状态为 tier_unknown（不强行标记）。
 *
 * 仅当 titles 为空 → no_titles（确认无现任头衔）。
 */
export interface DerivedTitleBits {
  primaryTitle?: EntityRef;
  highestTitleTier?: TitleTier;
  isRuler: boolean;
  status: TitleStatus;
}

const TIER_RANK: Record<TitleTier, number> = {
  barony: 0,
  county: 1,
  duchy: 2,
  kingdom: 3,
  empire: 4,
};

export function deriveTitleBits(periods: TitlePeriod[]): DerivedTitleBits {
  const current = periods.filter((p) => p.isCurrent);
  if (current.length === 0) {
    return { isRuler: false, status: "no_titles" };
  }
  // 等级未知（tier 缺省）→ rank 最低，绝不优先；全部未知时 best 也为 undefined。
  let best: TitlePeriod | undefined;
  let bestRank = -1;
  for (const p of current) {
    const rank = p.tier ? TIER_RANK[p.tier] : -1;
    if (rank > bestRank) {
      bestRank = rank;
      best = p;
    }
  }
  const bestTier = best?.tier;
  if (bestTier == null) {
    return { isRuler: true, status: "tier_unknown" };
  }
  const ties = current.filter((p) => p.tier === bestTier).sort((a, b) => a.titleId.localeCompare(b.titleId));
  const chosen = ties[0];
  return {
    primaryTitle: {
      id: chosen.titleId,
      name: chosen.name,
      type: "title",
      resolved: chosen.name !== chosen.titleId,
    },
    highestTitleTier: bestTier,
    isRuler: true,
    status: "resolved",
  };
}
