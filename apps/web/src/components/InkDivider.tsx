import { cn } from "../lib/cn";
import { SealMark } from "./icons";

type Variant = "line" | "dotted" | "seal";

/**
 * 墨色分隔线（装饰）。variant：
 *  - line：单线
 *  - dotted：虚线
 *  - seal：双线夹一枚朱砂小印（仪式感，仍属装饰）
 * 默认 aria-hidden（装饰）；仅当提供 label 时暴露于无障碍树（带 aria-label）。
 */
export default function InkDivider({
  variant = "line",
  label,
  className = "",
  animateInk = false,
}: {
  variant?: Variant;
  label?: string;
  className?: string;
  /** 进入视口时墨线自左向右铺开（用于传记章节首屏），减弱动效时由媒体查询即时就位。 */
  animateInk?: boolean;
}) {
  const lineCls =
    variant === "dotted"
      ? "border-t border-dashed border-ink-400/40"
      : "border-t border-ink-400/40";
  const inkAnim = animateInk ? "origin-left animate-ink-draw" : "";

  if (variant === "seal") {
    return (
      <div
        className={cn("flex items-center gap-3", className)}
        role="separator"
        aria-hidden={label ? undefined : true}
      >
        <span className="h-px flex-1 bg-ink-400/40" />
        <SealMark size={16} className="shrink-0 text-cinnabar-700" />
        <span className="h-px flex-1 bg-ink-400/40" />
        {label && <span className="sr-only">{label}</span>}
      </div>
    );
  }

  if (label) {
    return (
      <div
        className={cn("my-1 flex items-center gap-2", className)}
        role="separator"
        aria-label={label}
      >
        <span className={cn("h-px flex-1", lineCls)} />
        <span className="text-xs text-ink-500">{label}</span>
        <span className={cn("h-px flex-1", lineCls)} />
      </div>
    );
  }

  if (animateInk) {
    return (
      <span
        className={cn("block h-px bg-ink-400/40", inkAnim, "my-1", className)}
        aria-hidden="true"
      />
    );
  }

  return (
    <hr
      className={cn(lineCls, "my-1", className)}
      aria-hidden="true"
    />
  );
}
