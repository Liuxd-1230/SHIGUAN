import type { ButtonHTMLAttributes, ReactNode } from "react";
import { SealMark } from "./icons";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-cinnabar-700 text-paper-50 hover:bg-cinnabar-800 active:bg-cinnabar-800",
  secondary:
    "border border-ink-400/60 bg-paper-50 text-ink-800 hover:border-ink-600 hover:bg-paper-100",
  danger:
    "bg-danger text-paper-50 hover:brightness-95 active:brightness-90",
  ghost: "text-ink-600 hover:text-ink-950 hover:bg-paper-200/60",
};

/**
 * 印章按钮：主/次/危险/幽灵四态。seal 时在左侧加一枚朱砂小印点缀。
 * 统一最小触控高度 44px（移动端可达性）。键盘可达（原生 <button>）。
 */
export default function SealButton({
  variant = "primary",
  seal = false,
  className = "",
  children,
  type = "button",
  ...rest
}: {
  variant?: Variant;
  seal?: boolean;
  children: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      className={`inline-flex min-h-[2.75rem] items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {seal && <SealMark size={16} className="opacity-90" />}
      {children}
    </button>
  );
}
