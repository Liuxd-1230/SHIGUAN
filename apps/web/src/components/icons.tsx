/**
 * 内联 SVG 图标集（东方数字史馆）。
 * 所有图标使用 currentColor，便于跟随文字颜色；装饰用途时加 aria-hidden。
 * 置信度/状态一律"图标 + 文字/形状"双表达，绝不只靠颜色区分。
 */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base({ size = 18, ...props }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

/** 印章（朱砂落印意象）：圆角方印 + 中缝。用于品牌/完成态。 */
export function SealMark(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 9h8M8 13h8" />
      <path d="M12 7v10" opacity="0.5" />
    </svg>
  );
}

/** 确认：双圈 + 对勾（玉色语境下表示 confirmed）。 */
export function CheckSeal(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.2l2.4 2.4 4.6-5" />
    </svg>
  );
}

/** 失败 / 错误：方印 + 叉。 */
export function CrossMark(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </svg>
  );
}

/** 存疑：三角惊叹（不确定）。 */
export function WarnMark(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 4l8.5 14.5H3.5L12 4z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="17" r="0.6" fill="currentColor" />
    </svg>
  );
}

/** 推断：实心圆点 + 外环（信息/推断语境）。 */
export function InfoDot(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3" fill="currentColor" />
    </svg>
  );
}

/** 等待 / 挂起：空心圆。 */
export function CircleHollow(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="8.5" />
    </svg>
  );
}

/** 跳过：双横杠。 */
export function SkipMark(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M6 10h12M6 14h12" />
    </svg>
  );
}

/** 运行中：旋转由 CSS animate-spin 控制。 */
export function Spinner(props: IconProps) {
  return (
    <svg {...base(props)} className={`animate-slow-spin ${props.className ?? ""}`}>
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </svg>
  );
}

export function CrownIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 8l3.5 4L12 5l4.5 7L20 8l-1.5 9h-13L4 8z" />
    </svg>
  );
}

export function BookIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 5h9a2 2 0 0 1 2 2v12H7a2 2 0 0 0-2 2V5z" />
      <path d="M19 5h0v14" />
    </svg>
  );
}

export function ScrollIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7 5h8a3 3 0 0 1 3 3v9a2 2 0 0 0 2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z" />
      <path d="M7 5a2 2 0 0 0-2 2v1h2" />
    </svg>
  );
}

export function MountainIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 19l6-11 4 6 3-4 5 9z" />
    </svg>
  );
}

export function ChevronLeft(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M14 6l-6 6 6 6" />
    </svg>
  );
}

export function ChevronRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10 6l6 6-6 6" />
    </svg>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 4l8.5 14.5H3.5L12 4z" />
      <path d="M12 10v4" />
      <circle cx="12" cy="17" r="0.6" fill="currentColor" />
    </svg>
  );
}
