import type { ReactNode } from "react";

/**
 * 卷轴面板：双线边框 + 纸白底，意象为展开的一截卷轴。
 * 用于传记章节、史料面板等需要"立传"质感的区域。
 * 支持透传 id 等原生属性（传记章节需要稳定 id 供滚动同步定位）。
 */
export default function ScrollPanel({
  className = "",
  children,
  as: Tag = "section",
  ...rest
}: {
  className?: string;
  children: ReactNode;
  as?: "section" | "article" | "div" | "aside";
} & Record<string, unknown>) {
  return (
    <Tag
      className={`relative rounded-2xl border-double border-4 border-ink-400/40 bg-paper-50 px-4 py-4 sm:px-5 ${className}`}
      {...rest}
    >
      {children}
    </Tag>
  );
}
