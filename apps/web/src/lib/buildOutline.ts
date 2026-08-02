import type {
  BiographyChapter,
  BiographyStyle,
  CharacterProfile,
  EventType,
  TimelineEvent,
} from "@shiguan/save-schema";

export interface DraftBiography {
  style: BiographyStyle;
  chapters: BiographyChapter[];
}

// 由存档时间线确定性分章（非 AI 生成，仅作传记壳演示）。
const CHAPTER_GROUPS: { key: string; title: string; types: EventType[] }[] = [
  { key: "origin", title: "出身与家世", types: ["birth", "child_birth"] },
  { key: "marriage", title: "婚姻与联盟", types: ["marriage", "divorce"] },
  { key: "rule", title: "头衔与统治", types: ["title_gain", "title_loss", "succession", "court_position"] },
  { key: "war", title: "战争与危机", types: ["war", "imprisonment", "exile"] },
  { key: "journey", title: "信仰与历程", types: ["conversion", "travel", "trait_gain"] },
  { key: "end", title: "晚年与身后", types: ["death", "success", "failure", "other"] },
];

function yearOf(ev: TimelineEvent): number {
  if (!ev.date) return 0;
  const m = ev.date.match(/(\d{1,4})/);
  return m ? parseInt(m[1], 10) : 0;
}

function confidenceTag(c: TimelineEvent["confidence"]): string {
  if (c === "confirmed") return "";
  if (c === "inferred") return "（据推断）";
  return "（史载不详）";
}

/** 把一条时间线事件整理为一句正文。 */
function toSentence(ev: TimelineEvent): string {
  return `${ev.description}${confidenceTag(ev.confidence)}`;
}

/**
 * 从完整档案的时间线确定性生成章节提纲与正文草稿。
 * 每章 eventIds 全部来自真实时间线（符合契约：非空且存在）。
 */
export function buildDraft(profile: CharacterProfile): DraftBiography {
  const style: BiographyStyle = "vernacular_annals";

  const buckets = new Map<string, TimelineEvent[]>();
  for (const ev of profile.timeline) {
    const group = CHAPTER_GROUPS.find((g) => g.types.includes(ev.type)) ?? CHAPTER_GROUPS[CHAPTER_GROUPS.length - 1];
    const list = buckets.get(group.key) ?? [];
    list.push(ev);
    buckets.set(group.key, list);
  }

  const chapters: BiographyChapter[] = [];
  for (const group of CHAPTER_GROUPS) {
    const events = buckets.get(group.key);
    if (!events || events.length === 0) continue;
    events.sort((a, b) => yearOf(a) - yearOf(b));
    const sentences = events.map((e) => toSentence(e));
    chapters.push({
      id: `ch_${group.key}`,
      title: group.title,
      content: `${profile.name}·${group.title}：${sentences.join("；")}。`,
      eventIds: events.map((e) => e.id),
    });
  }

  return { style, chapters };
}

/** 建立 eventId -> chapterId 映射，用于滚动同步高亮。 */
export function eventChapterMap(chapters: BiographyChapter[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const ch of chapters) {
    for (const id of ch.eventIds) map[id] = ch.id;
  }
  return map;
}
