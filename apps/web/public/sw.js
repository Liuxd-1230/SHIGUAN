// 史官 SHIGUAN —— 最小 PWA Service Worker
//
// 路径判定与分支逻辑的唯一事实来源见 src/lib/swHandler.ts（有单测守护）。
// 本文件因无打包步骤无法 import，故在此内联**逐字一致**的等价实现。
// 修改任一处时，必须同步另一处（否则离线深链接会再次失效）。
//
// 安全边界（来自 Phase 1B / 1C.1 PWA 修复）：
//  - 只缓存**明确列出的同源静态资源**（shell + 构建产物）。
//  - 绝不缓存任何可能携带私有数据的响应：/api/、/uploads/、/saves/ 路径，
//    以及带 Authorization 请求头的请求、非 GET 请求、跨源请求。
//  - 导航请求（SPA 深链接）网络优先、失败回退缓存首页；导航响应本身不缓存。
//  - 激活时清理旧版本缓存，避免陈旧资源。

const CACHE = "shiguan-shell-v1";

// 明确允许缓存的静态资源（精确列表，不靠前缀猜测）。
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

// 命中即视为"可缓存静态资源"的路径前缀（仅同源）。
const CACHEABLE_PREFIXES = ["/assets/"];
// 任何含这些前缀的请求都不允许进入缓存（可能与私有数据相关）。
const NEVER_CACHE_PREFIXES = ["/api/", "/uploads/", "/saves/"];

// SPA 应用路由：离线时由导航回退到 index.html。
const APP_NAVIGATION_PATHS = ["/", "/parse", "/characters", "/design-lab"];

function isNeverCachePath(pathname) {
  return NEVER_CACHE_PREFIXES.some((p) => pathname.startsWith(p));
}
function isCacheableStaticPath(pathname, method = "GET") {
  if (method !== "GET") return false;
  if (isNeverCachePath(pathname)) return false;
  if (SHELL.includes(pathname)) return true;
  return CACHEABLE_PREFIXES.some((p) => pathname.startsWith(p));
}
function isAppNavigationPath(pathname) {
  if (APP_NAVIGATION_PATHS.includes(pathname)) return true;
  return /^\/characters\/.+/.test(pathname);
}

// —— 以下分支逻辑与 src/lib/swHandler.ts#decideFetch 完全一致 ——
function decideFetch(req) {
  const url = new URL(req.url);
  // 1. 拒绝 非 GET / 跨源 / 带 Authorization / 私有路径
  if (req.method !== "GET") return { kind: "pass" };
  if (url.origin !== self.location.origin) return { kind: "pass" };
  if (req.headers && req.headers.has("authorization")) return { kind: "pass" };
  if (isNeverCachePath(url.pathname)) return { kind: "pass" };

  // 2. 导航请求
  if (req.mode === "navigate") {
    if (!isAppNavigationPath(url.pathname)) {
      return { kind: "network-only", pathname: url.pathname };
    }
    return { kind: "navigate-app", pathname: url.pathname };
  }

  // 3. 非导航的同源静态资源
  if (isCacheableStaticPath(url.pathname)) {
    return { kind: "static-cache", pathname: url.pathname };
  }

  return { kind: "network-only", pathname: url.pathname };
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const decision = decideFetch(req);

  if (decision.kind === "pass" || decision.kind === "network-only") {
    // 私有/未知路径：直接走网络（不回退、不缓存）
    return;
  }

  if (decision.kind === "navigate-app") {
    // 网络优先；网络失败回退缓存首页（离线深链接）。导航响应本身不缓存。
    event.respondWith(
      fetch(req).catch(() => caches.match("/index.html")),
    );
    return;
  }

  // static-cache：缓存优先，回源并存
  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req)
        .then((res) => {
          if (
            res &&
            res.ok &&
            res.type === "basic" &&
            isCacheableStaticPath(new URL(req.url).pathname)
          ) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => hit);
    }),
  );
});
