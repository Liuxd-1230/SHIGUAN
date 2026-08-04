import { describe, it, expect } from "vitest";
import { deriveTitleBits } from "../titleBits";
import type { TitlePeriod } from "@shiguan/save-schema";

function period(over: Partial<TitlePeriod> & { titleId: string; name: string }): TitlePeriod {
  return { isCurrent: true, ...over };
}

describe("deriveTitleBits（P0：顶部头衔与 titles 面板同源）", () => {
  it("无任何头衔 → no_titles，非统治者", () => {
    const b = deriveTitleBits([]);
    expect(b.status).toBe("no_titles");
    expect(b.isRuler).toBe(false);
    expect(b.primaryTitle).toBeUndefined();
  });

  it("仅有历史任期（非现任）→ no_titles", () => {
    const b = deriveTitleBits([
      period({ titleId: "d_old", name: "旧公国", isCurrent: false, tier: "duchy" }),
    ]);
    expect(b.status).toBe("no_titles");
    expect(b.isRuler).toBe(false);
  });

  it("现任头衔取最高等级为主头衔", () => {
    const b = deriveTitleBits([
      period({ titleId: "c_a", name: "甲县", tier: "county" }),
      period({ titleId: "k_b", name: "乙王国", tier: "kingdom" }),
      period({ titleId: "d_c", name: "丙公国", tier: "duchy" }),
    ]);
    expect(b.status).toBe("resolved");
    expect(b.primaryTitle?.id).toBe("k_b");
    expect(b.primaryTitle?.name).toBe("乙王国");
    expect(b.highestTitleTier).toBe("kingdom");
    expect(b.isRuler).toBe(true);
  });

  it("多个同级 → 按 titleId 稳定顺序取一个（确定性）", () => {
    const b = deriveTitleBits([
      period({ titleId: "k_z", name: "z 王国", tier: "kingdom" }),
      period({ titleId: "k_a", name: "a 王国", tier: "kingdom" }),
    ]);
    expect(b.status).toBe("resolved");
    expect(b.primaryTitle?.id).toBe("k_a"); // 稳定顺序
    expect(b.highestTitleTier).toBe("kingdom");
  });

  it("现任头衔等级全部未知 → tier_unknown，不伪造主头衔", () => {
    const b = deriveTitleBits([
      period({ titleId: "x_mc_1", name: "某大队", tier: undefined }),
    ]);
    expect(b.status).toBe("tier_unknown");
    expect(b.primaryTitle).toBeUndefined();
    expect(b.isRuler).toBe(true);
  });

  it("未解析名 → resolved=false 如实标注", () => {
    const b = deriveTitleBits([period({ titleId: "c_raw", name: "c_raw", tier: "county" })]);
    expect(b.status).toBe("resolved");
    expect(b.primaryTitle?.resolved).toBe(false);
  });
});
