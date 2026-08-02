import type { TimelineEvent } from "@shiguan/save-schema";
import { KEY_EVENT_TYPES } from "../lib/labels";
import EmptyState from "./EmptyState";
import TimelineNode from "./TimelineNode";

export type TimelineDensity = "all" | "key";

export default function Timeline({
  events,
  activeId,
  activeChapterEventIds,
  onSelect,
  density,
}: {
  events: TimelineEvent[];
  activeId: string | null;
  /** 当前章节对应的事件集合（用于滚动时同步高亮）。 */
  activeChapterEventIds: Set<string>;
  onSelect: (id: string) => void;
  density: TimelineDensity;
}) {
  const shown =
    density === "key"
      ? events.filter((e) => KEY_EVENT_TYPES.has(e.type))
      : events;

  return (
    <div>
      <h2 className="font-serif text-lg font-bold text-ink-900">时间线</h2>
      {density === "key" && (
        <p className="mt-1 text-[11px] text-ink-500">
          仅显示关键事件（共 {shown.length} / {events.length}）
        </p>
      )}
      {shown.length === 0 ? (
        <EmptyState
          className="mt-3"
          title="没有可显示的时间线事件"
          description="切换为「全部事件」或选择其他人物试试。"
        />
      ) : (
        <ol className="mt-3 space-y-2 border-l border-ink-400/50 pl-1">
          {shown.map((ev) => (
            <TimelineNode
              key={ev.id}
              event={ev}
              active={ev.id === activeId}
              inChapter={activeChapterEventIds.has(ev.id)}
              onSelect={onSelect}
            />
          ))}
        </ol>
      )}
    </div>
  );
}
