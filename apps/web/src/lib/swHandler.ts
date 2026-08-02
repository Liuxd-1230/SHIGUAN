/**
 * Service Worker 请求处理（可测试的纯逻辑）。
 *
 * 本文件是 public/sw.js 的「被测试唯一事实来源」——sw.js 因无打包步骤无法 import，
 * 故在 sw.js 中内联了**逐字一致**的等价实现（见 sw.js 顶部注释，改动须同步）。
 *
 * 分支顺序（关键，决定了离线深链接能否真实回退）：
 *   1) 先拒绝 非 GET / 跨源 / 带 Authorization / 私有路径（直接走网络，绝不缓存）；
 *   2) 若是导航请求（request.mode === "navigate"）：
 *        - 仅当 isAppNavigationPath 的公开前端路由才网络优先、失败回退 /index.html；
 *        - 不缓存导航响应（避免缓存任何私有人物数据）；
 *   3) 非导航的同源静态资源才进入缓存优先 + 回源并存逻辑。
 */
import {
  isNeverCachePath,
  isCacheableStaticPath,
  isAppNavigationPath,
} from "./swCachePolicy";

export type FetchDecision =
  | { kind: "pass" } // 直接走网络（不缓存）：非 GET / 跨源 / 鉴权 / 私有路径
  | { kind: "network-only"; pathname: string } // 未知公开路径：走网络，不缓存、不回退
  | { kind: "navigate-app"; pathname: string } // 应用路由导航：网络优先，失败回退 /index.html
  | { kind: "static-cache"; pathname: string }; // 同源静态资源：缓存优先 + 回源并存

export interface FetchContext {
  url: URL;
  method: string;
  mode: string;
  hasAuthorization: boolean;
  origin: string;
  swOrigin: string;
}

/** 仅做分支判定，不触碰网络/缓存，便于单测验证实际顺序。 */
export function decideFetch(ctx: FetchContext): FetchDecision {
  // 1. 拒绝 非 GET / 跨源 / 带 Authorization / 私有路径（直接走网络，绝不缓存）
  if (ctx.method !== "GET") return { kind: "pass" };
  if (ctx.origin !== ctx.swOrigin) return { kind: "pass" };
  if (ctx.hasAuthorization) return { kind: "pass" };
  if (isNeverCachePath(ctx.url.pathname)) return { kind: "pass" };

  // 2. 导航请求
  if (ctx.mode === "navigate") {
    if (!isAppNavigationPath(ctx.url.pathname)) {
      // 未知公开路径（/api/* 已在上面拦截）：不回退缓存，直接走网络
      return { kind: "network-only", pathname: ctx.url.pathname };
    }
    // 应用路由：网络优先，失败回退缓存首页；不缓存导航响应
    return { kind: "navigate-app", pathname: ctx.url.pathname };
  }

  // 3. 非导航的同源静态资源：缓存优先 + 回源并存
  if (isCacheableStaticPath(ctx.url.pathname)) {
    return { kind: "static-cache", pathname: ctx.url.pathname };
  }

  // 其它公开路径：走网络，不缓存
  return { kind: "network-only", pathname: ctx.url.pathname };
}

export interface ResponderDeps {
  fetchImpl: typeof fetch;
  caches: CacheStorage;
  cacheName: string;
  indexFallback: string; // 通常为 "/index.html"
}

/** 把分支判定转为真实响应（可注入 fake fetch / fake caches 进行单测）。 */
export async function respondTo(
  decision: FetchDecision,
  request: Request,
  deps: ResponderDeps,
): Promise<Response> {
  switch (decision.kind) {
    case "pass":
    case "network-only":
      // 私有/未知路径：直接走网络，不回退、不缓存
      return deps.fetchImpl(request);

    case "navigate-app": {
      // 网络优先；网络失败时回退缓存中的首页（离线深链接）。
      // 注意：绝不在这里缓存导航响应，以免缓存任何私有人物数据。
      try {
        return await deps.fetchImpl(request);
      } catch {
        const cache = await deps.caches.open(deps.cacheName);
        const fallback = await cache.match(deps.indexFallback);
        if (fallback) return fallback;
        throw new Error("离线且缓存中无 index.html 回退");
      }
    }

    case "static-cache": {
      const cache = await deps.caches.open(deps.cacheName);
      const hit = await cache.match(request);
      if (hit) return hit;
      const res = await deps.fetchImpl(request);
      // 只缓存同源 basic 的 2xx 响应（再次校验白名单）
      if (
        res &&
        res.ok &&
        res.type === "basic" &&
        isCacheableStaticPath(new URL(request.url).pathname)
      ) {
        cache.put(request, res.clone());
      }
      return res;
    }
  }
}
