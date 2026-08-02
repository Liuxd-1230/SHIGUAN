import type { EvidenceWarning, TimelineEvent } from "@shiguan/save-schema";
import { sourceTypeLabel } from "../lib/labels";
import EvidenceBadge from "./EvidenceBadge";
import EmptyState from "./EmptyState";
import { motion, AnimatePresence } from "framer-motion";

export default function EvidencePanel({
  event,
  warnings,
}: {
  event?: TimelineEvent;
  warnings: EvidenceWarning[];
}) {
  // 区分"当前事件关联告警"与"人物全局告警"，优先展示前者。
  const eventWarnings = event
    ? warnings.filter((w) => w.relatedEventId === event.id)
    : [];
  const globalWarnings = event
    ? warnings.filter((w) => w.relatedEventId !== event.id)
    : warnings;

  return (
    <div>
      <h2 className="font-serif text-lg font-bold text-ink-900">史料依据</h2>

      <AnimatePresence mode="wait" initial={false}>
        {event ? (
          <motion.div
            key={event.id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="mt-3"
          >
            <p className="text-sm text-ink-600">
              当前事件：<span className="text-ink-900">{event.title}</span>
            </p>
            <ul className="mt-3 space-y-2">
              {event.evidence.length === 0 && (
                <li className="text-sm text-ink-500">
                  该事件暂无证据引用（契约要求至少关联一条 EvidenceRef）。
                </li>
              )}
              {event.evidence.map((e) => (
                <li
                  key={e.id}
                  className="rounded-lg border border-ink-400/40 bg-paper-50/70 p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] uppercase tracking-wide text-ink-500">
                      {sourceTypeLabel(e.sourceType)}
                    </span>
                    <EvidenceBadge value={e.confidence} />
                  </div>
                  <p className="mt-1 text-sm text-ink-900">{e.description}</p>
                  {e.rawKey && (
                    <p className="mt-1 break-all text-[11px] text-ink-500">
                      原始键：{e.rawKey}
                    </p>
                  )}
                  {e.sourcePath ? (
                    <p className="mt-1 break-all text-[11px] text-ink-500">
                      来源路径：{e.sourcePath}
                    </p>
                  ) : (
                    <p className="mt-1 text-[11px] text-cinnabar-700">
                      （来源路径缺失，无法精确定位）
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </motion.div>
        ) : (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <EmptyState
              className="mt-3"
              title="在时间线中选择一个事件"
              description="即可查看其史料依据与来源路径。"
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* 当前事件关联告警 */}
      {eventWarnings.length > 0 && (
        <div className="mt-5">
          <h3 className="text-sm font-medium text-cinnabar-700">当前事件告警</h3>
          <ul className="mt-2 space-y-2">
            {eventWarnings.map((w, i) => (
              <li
                key={`e${i}`}
                className="rounded-lg border border-cinnabar-700/40 bg-cinnabar-700/5 p-3 text-sm text-ink-700"
              >
                <span className="text-cinnabar-700">[{w.severity}]</span>{" "}
                {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 人物全局告警（与当前事件无关） */}
      {globalWarnings.length > 0 && (
        <div className="mt-5">
          <h3 className="text-sm font-medium text-ink-500">
            人物全局告警（{globalWarnings.length}）
          </h3>
          <ul className="mt-2 space-y-2">
            {globalWarnings.map((w, i) => (
              <li
                key={`g${i}`}
                className="rounded-lg border border-ink-400/40 bg-paper-50/70 p-3 text-sm text-ink-700"
              >
                <span className="text-ink-500">[{w.severity}]</span> {w.message}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
