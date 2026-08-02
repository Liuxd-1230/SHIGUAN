import type { ElementType, ReactNode } from "react";

/**
 * 史馆表面：承载内容的纸张面板。variant 区分层级：
 *  - raised：抬升的主表面（纸白）
 *  - inset：内嵌/凹陷（淡赭）
 *  - flat：与页面同底
 */
const VARIANTS = {
  raised:
    "bg-paper-50 border border-ink-400/40 shadow-[0_1px_0_rgb(var(--ink-950)/0.05)]",
  inset: "bg-paper-200/50 border border-ink-400/30",
  flat: "bg-paper-100",
} as const;

export default function MuseumSurface({
  as: Tag = "div",
  variant = "raised",
  className = "",
  children,
  ...rest
}: {
  as?: ElementType;
  variant?: keyof typeof VARIANTS;
  className?: string;
  children: ReactNode;
} & Record<string, unknown>) {
  return (
    <Tag
      className={`rounded-2xl ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </Tag>
  );
}
