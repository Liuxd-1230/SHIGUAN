import type { ReactNode } from "react";

/**
 * 史书式标题：可选眉题（朱砂小字）+ 衬线大标题。
 * level 控制语义层级（h1/h2/h3），视觉通过 className 微调。
 */
export default function PageHeading({
  title,
  eyebrow,
  level = 1,
  className = "",
  children,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  level?: 1 | 2 | 3;
  className?: string;
  children?: ReactNode;
}) {
  const Tag = (`h${level}` as "h1" | "h2" | "h3");
  return (
    <div className={className}>
      {eyebrow && (
        <p className="mb-1 text-xs font-medium uppercase tracking-[0.2em] text-cinnabar-700">
          {eyebrow}
        </p>
      )}
      <Tag className="font-serif text-2xl font-bold text-ink-950 sm:text-3xl">
        {title}
      </Tag>
      {children}
    </div>
  );
}
