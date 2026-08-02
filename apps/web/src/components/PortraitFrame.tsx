import { useState } from "react";
import { cn } from "../lib/cn";

/**
 * 肖像 / 纹章框。
 *
 * 重要：绝不替换 CK3 人物的真实文化信息——本组件只展示调用方显式传入的
 * name / cultureLabel 等字段，不做任何文化改写或臆造。
 *
 * 渲染策略（优雅降级）：
 *  - 传入 imageUrl 且可加载 → 显示图像；
 *  - 无图像或加载失败 → 退化为"姓氏首字"的朱砂印式字母组合（不依赖外部素材）。
 * 装饰性图像一律 aria-hidden、空 alt，避免打扰读屏。
 */
export default function PortraitFrame({
  name,
  cultureLabel,
  imageUrl,
  size = 96,
  className = "",
}: {
  name: string;
  /** 真实文化标签（如"法兰克""契丹"），由调用方提供，组件不臆造。 */
  cultureLabel?: string;
  /** 可选肖像/纹章图地址；缺失或失败时退化为字母印。 */
  imageUrl?: string;
  size?: number;
  className?: string;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  const showImage = !!imageUrl && !imgFailed;
  const initial = name?.trim()?.[0] ?? "?";

  return (
    <figure className={cn("flex flex-col items-center", className)}>
      <div
        className="relative inline-flex items-center justify-center overflow-hidden rounded-full border-2 border-gold-500/60 bg-paper-50 shadow-[0_1px_0_rgb(var(--ink-950)/0.06)]"
        style={{ width: size, height: size }}
        role="img"
        aria-label={`${name}${cultureLabel ? `（${cultureLabel}）` : ""} 的肖像`}
      >
        {showImage ? (
          <img
            src={imageUrl}
            alt=""
            aria-hidden
            className="h-full w-full object-cover"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <span className="font-serif text-3xl font-bold text-ink-800">
            {initial}
          </span>
        )}
      </div>
      {cultureLabel && (
        <figcaption className="mt-1 text-[11px] text-ink-600">
          {cultureLabel}
        </figcaption>
      )}
    </figure>
  );
}
