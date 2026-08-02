/**
 * PWA 缓存策略（纯函数，便于单元测试）。
 *
 * 本文件是 public/sw.js 中"路径判定逻辑"的**被测试唯一事实来源**。
 * Service Worker 无法 import 本模块（无打包步骤），因此 sw.js 内联了等价实现，
 * 并须与下方常量/函数保持同步（见 sw.js 顶部注释）。
 *
 * 安全边界：绝不缓存任何可能携带私有数据的路径（/api/ /uploads/ /saves/）、
 * 非 GET 请求、带 Authorization 的请求、跨源请求。
 */

export const CACHEABLE_PREFIXES = ["/assets/"] as const;
export const NEVER_CACHE_PREFIXES = ["/api/", "/uploads/", "/saves/"] as const;

/** SPA 应用路由：离线时由导航回退到 index.html。 */
export const APP_NAVIGATION_PATHS = [
  "/",
  "/parse",
  "/characters",
  "/design-lab",
] as const;

/** 任何含这些前缀的路径都不允许进入缓存（可能与私有数据相关）。 */
export function isNeverCachePath(pathname: string): boolean {
  return NEVER_CACHE_PREFIXES.some((p) => pathname.startsWith(p));
}

/**
 * 判断某个路径是否应作为"同源静态资源"缓存。
 * @param pathname 请求路径（以 / 开头）
 * @param method   HTTP 方法，默认 GET
 */
export function isCacheableStaticPath(
  pathname: string,
  method: string = "GET",
): boolean {
  if (method !== "GET") return false;
  if (isNeverCachePath(pathname)) return false;
  if (
    pathname === "/" ||
    pathname === "/index.html" ||
    pathname === "/manifest.webmanifest" ||
    pathname === "/icon.svg"
  ) {
    return true;
  }
  return CACHEABLE_PREFIXES.some((p) => pathname.startsWith(p));
}

/** 是否为 SPA 应用路由（离线深链接应回退到 index.html）。 */
export function isAppNavigationPath(pathname: string): boolean {
  if ((APP_NAVIGATION_PATHS as readonly string[]).includes(pathname)) return true;
  return /^\/characters\/.+/.test(pathname);
}
