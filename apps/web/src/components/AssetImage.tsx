import { useState } from "react";
import { cn } from "../lib/cn";

/**
 * 装饰性素材图（东方素材接入点）。
 *
 * 优雅降级：素材缺失或加载失败时整节点消失（return null），绝不阻塞渲染或抛错。
 * 装饰用途默认 aria-hidden + 空 alt；仅当调用方明确提供 alt 时才暴露给读屏。
 */
export default function AssetImage({
  src,
  alt = "",
  className = "",
  eager = false,
}: {
  src: string;
  alt?: string;
  className?: string;
  eager?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) return null;
  const decorative = alt.trim() === "";
  return (
    <img
      src={src}
      alt={alt}
      aria-hidden={decorative ? true : undefined}
      className={cn(className)}
      loading={eager ? "eager" : "lazy"}
      onError={() => setFailed(true)}
    />
  );
}
