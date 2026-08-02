/** 中文标签映射，集中管理避免散落。 */
import type { Confidence } from "@shiguan/save-schema";

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  confirmed: "确认",
  inferred: "推断",
  uncertain: "存疑",
};

/** 证据来源类别的中文名称（用于"史料依据"面板）。 */
export const SOURCE_TYPE_LABELS: Record<string, string> = {
  save_block: "存档数据块",
  localization: "本地化文本",
  memory: "记忆片段",
  war: "战争记录",
  title: "头衔记录",
  other: "其它来源",
};

/** 时间线事件类型的中文名称（用于密度筛选提示等）。 */
export const EVENT_TYPE_LABELS: Record<string, string> = {
  birth: "诞生",
  death: "离世",
  marriage: "婚姻",
  divorce: "离异",
  child_birth: "子嗣出生",
  succession: "继承",
  title_gain: "获封",
  title_loss: "失封",
  war: "战争",
  imprisonment: "囚禁",
  exile: "流放",
  travel: "行旅",
  court_position: "任职",
  conversion: "改信",
  trait_gain: "特质",
  success: "功业",
  failure: "挫折",
  other: "其它",
};

/** "关键事件"类型（用于时间线密度控制中的"关键事件"视图）。 */
export const KEY_EVENT_TYPES = new Set<string>([
  "birth",
  "death",
  "marriage",
  "divorce",
  "succession",
  "title_gain",
  "title_loss",
  "war",
  "imprisonment",
  "exile",
]);

export function sourceTypeLabel(key: string): string {
  return SOURCE_TYPE_LABELS[key] ?? key;
}

export function eventTypeLabel(key: string): string {
  return EVENT_TYPE_LABELS[key] ?? key;
}

export function confidenceLabel(c: Confidence): string {
  return CONFIDENCE_LABELS[c] ?? c;
}
