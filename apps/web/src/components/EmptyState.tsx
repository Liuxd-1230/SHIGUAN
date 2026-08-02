import type { ReactNode } from "react";
import { cn } from "../lib/cn";

/**
 * 空状态 / 占位（史馆留白）。用于"没有时间线事件""未选择事件"等场景。
 * role="status" 让读屏知晓状态变化；icon 为装饰时由调用方提供 aria-hidden 元素。
 */
export default function EmptyState({
  icon,
  title,
  description,
  action,
  className = "",
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-ink-400/50 bg-paper-50/60 px-5 py-8 text-center",
        className,
      )}
    >
      {icon && <div className="mb-3 text-ink-400">{icon}</div>}
      <p className="font-serif text-base text-ink-800">{title}</p>
      {description && (
        <p className="mt-1 text-sm text-ink-600">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
