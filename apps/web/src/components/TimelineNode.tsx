import type { TimelineEvent } from "@shiguan/save-schema";
import { eventTypeLabel } from "../lib/labels";
import { cn } from "../lib/cn";
import EvidenceBadge from "./EvidenceBadge";
import { motion, AnimatePresence } from "framer-motion";

/**
 * 时间线节点（单条事件）。提取自原 Timeline，便于复用与无障碍强化：
 *  - 用原生 <button>，键盘可达，最小触控高度 44px；
 *  - aria-current 标记当前选中项；
 *  - 置信度用 EvidenceBadge（图标 + 形状 + 文字）双表达，不靠颜色；
 *  - 克制动效：当前章节连接线轻微点亮（inChapter）；当前节点激活瞬间播放一次柔和脉冲。
 *    脉冲与过渡均由外层 <MotionConfig reducedMotion="user"> 统一降级（减弱动效时立即就位）。
 */
export default function TimelineNode({
  event,
  active,
  inChapter,
  onSelect,
}: {
  event: TimelineEvent;
  active: boolean;
  inChapter: boolean;
  onSelect: (id: string) => void;
}) {
  const cls = active
    ? "border-cinnabar-700/70 bg-cinnabar-700/5"
    : inChapter
      ? "border-gold-500/40 bg-paper-200/40"
      : "border-transparent hover:bg-paper-200/40";
  return (
    <li className="relative ml-3">
      {/* 当前章节连接线轻微点亮（CSS 过渡，减弱动效时由媒体查询即时切换） */}
      <span
        aria-hidden
        className={cn(
          "absolute -left-3 top-0 h-full w-0.5 transition-colors duration-300",
          inChapter ? "bg-gold-500/70" : "bg-ink-400/40",
        )}
      />
      <button
        type="button"
        onClick={() => onSelect(event.id)}
        data-event-id={event.id}
        aria-current={active ? "true" : undefined}
        aria-pressed={active}
        title={eventTypeLabel(event.type)}
        className={cn(
          "relative block min-h-[2.75rem] w-full rounded-lg border p-3 text-left transition-colors",
          cls,
        )}
      >
        {/* 当前节点激活瞬间播放一次柔和脉冲（仅激活时挂载，去激活即移除） */}
        <AnimatePresence>
          {active && (
            <motion.span
              key="pulse"
              aria-hidden
              initial={{ opacity: 0.5, scale: 0.92 }}
              animate={{ opacity: 0, scale: 1.18 }}
              transition={{ duration: 0.7, ease: "easeOut" }}
              className="pointer-events-none absolute inset-0 rounded-lg ring-2 ring-cinnabar-700/40"
            />
          )}
        </AnimatePresence>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-ink-600">
            {event.date ?? "日期不详"}
          </span>
          <EvidenceBadge value={event.confidence} showLabel={false} />
        </div>
        <p
          className={cn(
            "mt-1 text-sm",
            active ? "font-medium text-ink-950" : "text-ink-800",
          )}
        >
          {event.title}
        </p>
      </button>
    </li>
  );
}
