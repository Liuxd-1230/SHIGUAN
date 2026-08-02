import { describe, it, expect } from "vitest";
import { buildDraft, eventChapterMap } from "../buildOutline";
import type {
  CharacterProfile,
  Confidence,
  EvidenceRef,
  TimelineEvent,
} from "@shiguan/save-schema";

/** 构造一条合法 TimelineEvent（含至少一个可溯源证据）。 */
function ev(p: Partial<TimelineEvent> & { id: string; type: TimelineEvent["type"] }): TimelineEvent {
  const evidence: EvidenceRef[] = p.evidence ?? [
    {
      id: `v_${p.id}`,
      sourceType: "save_block",
      description: "测试证据",
      confidence: (p.confidence ?? "confirmed") as Confidence,
    },
  ];
  return {
    date: "1000.01.01",
    title: p.id,
    description: p.id,
    confidence: "confirmed" as Confidence,
    ...p,
    evidence,
  } as TimelineEvent;
}

/** 构造一份最小合法 CharacterProfile。 */
function profile(timeline: TimelineEvent[]): CharacterProfile {
  return {
    id: "test_profile",
    name: "测试人物",
    traits: [],
    titles: [],
    residences: [],
    courtPositions: [],
    parents: [],
    spouses: [],
    children: [],
    siblings: [],
    friends: [],
    rivals: [],
    lovers: [],
    wars: [],
    imprisonments: [],
    travels: [],
    memories: [],
    timeline,
    evidenceWarnings: [],
  };
}

describe("buildDraft（传记提纲来自真实时间线，非 AI 生成）", () => {
  it("每个章节的 eventIds 都来自真实时间线，且覆盖全部事件", () => {
    const timeline = [
      ev({ id: "e1", type: "birth", date: "1000.01.01" }),
      ev({ id: "e2", type: "marriage", date: "1025.06.01" }),
      ev({ id: "e3", type: "title_gain", date: "1030.01.01" }),
      ev({ id: "e4", type: "death", date: "1070.01.01" }),
    ];
    const draft = buildDraft(profile(timeline));
    const timelineIds = new Set(timeline.map((e) => e.id));

    expect(draft.chapters.length).toBeGreaterThan(0);
    const covered = new Set<string>();
    for (const ch of draft.chapters) {
      expect(ch.eventIds.length).toBeGreaterThan(0);
      for (const id of ch.eventIds) {
        expect(timelineIds.has(id)).toBe(true); // 不得凭空捏造事件
        covered.add(id);
      }
    }
    for (const e of timeline) {
      expect(covered.has(e.id)).toBe(true); // 不得遗漏时间线事件
    }
  });

  it("缺少日期的事件排序稳定（yearOf 返回 0，排在同组最早）", () => {
    const noDate = ev({ id: "nd", type: "trait_gain", date: undefined });
    const dated = ev({ id: "dt", type: "trait_gain", date: "1100.01.01" });
    const draft = buildDraft(profile([dated, noDate]));
    const journey = draft.chapters.find((c) => c.id === "ch_journey");
    expect(journey).toBeDefined();
    expect(journey!.eventIds[0]).toBe("nd"); // 缺日期（year 0）排在显式日期之前
    expect(journey!.eventIds[1]).toBe("dt");
  });

  it("eventChapterMap 把每个事件映射到其所属章节", () => {
    const timeline = [
      ev({ id: "e1", type: "birth", date: "1000.01.01" }),
      ev({ id: "e2", type: "marriage", date: "1025.06.01" }),
    ];
    const draft = buildDraft(profile(timeline));
    const map = eventChapterMap(draft.chapters);
    for (const ch of draft.chapters) {
      for (const id of ch.eventIds) {
        expect(map[id]).toBe(ch.id);
      }
    }
  });
});
