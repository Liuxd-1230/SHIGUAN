import type { ComponentType, SVGProps } from "react";
import type { Confidence } from "@shiguan/save-schema";
import { CONFIDENCE_LABELS } from "../lib/labels";
import { cn } from "../lib/cn";
import { CheckSeal, InfoDot, WarnMark } from "./icons";

/**
 * 证据置信度徽标：一律"图标 + 形状 + 文字"三重表达，
 * 绝不只靠颜色区分（无障碍硬性要求）。
 *  - confirmed：玉色 · 对勾圆印 · 文字"确认"
 *  - inferred ：靛青 · 信息点 · 文字"推断"
 *  - uncertain：琥珀 · 惊叹三角 · 文字"存疑"
 */
const MAP: Record<
  Confidence,
  {
    Icon: ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;
    cls: string;
  }
> = {
  confirmed: {
    Icon: CheckSeal,
    cls: "border-jade-700/60 text-jade-700 bg-jade-500/10",
  },
  inferred: {
    Icon: InfoDot,
    cls: "border-indigo-700/50 text-indigo-700 bg-indigo-500/10",
  },
  uncertain: {
    Icon: WarnMark,
    cls: "border-uncertain/60 text-uncertain bg-uncertain/10",
  },
};

export default function EvidenceBadge({
  value,
  showLabel = true,
  className = "",
}: {
  value: Confidence;
  /** 是否显示文字标签（紧凑列表可关，但图标形状仍保留）。 */
  showLabel?: boolean;
  className?: string;
}) {
  const { Icon, cls } = MAP[value];
  const label = CONFIDENCE_LABELS[value];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] leading-none",
        cls,
        className,
      )}
      title={`证据置信度：${label}`}
    >
      <Icon size={12} className="shrink-0" />
      {showLabel && <span>{label}</span>}
    </span>
  );
}
