/**
 * 轻量路由（History API）。支持：
 *  - /                      起始页
 *  - /parse                 解析过程页
 *  - /characters            人物选择页
 *  - /characters/:id        人物传记页（刷新可恢复：读取 path 后重新取档）
 *  - 其它路径               notfound
 *
 * 不引入 react-router，保持依赖克制。浏览器前进/后退通过 popstate 驱动；
 * 程序内跳转通过 navigate()（pushState + 自定义事件通知订阅者）。
 */
import { useSyncExternalStore } from "react";

export type RouteName =
  | "start"
  | "parse"
  | "select"
  | "bio"
  | "designlab"
  | "notfound";

export interface Route {
  name: RouteName;
  path: string;
  params: { characterId?: string; saveId?: string };
}

export const ROUTES = {
  start: "/",
  parse: "/parse",
  characters: "/characters",
  character: (id: string) => `/characters/${encodeURIComponent(id)}`,
  // 真实存档浏览：URL 携带 saveId，刷新/深链可恢复（规范：真实路由恢复）。
  savesCharacters: (saveId: string) =>
    `/saves/${encodeURIComponent(saveId)}/characters`,
  saveCharacter: (saveId: string, id: string) =>
    `/saves/${encodeURIComponent(saveId)}/characters/${encodeURIComponent(id)}`,
  designlab: "/design-lab",
} as const;

const NAV_EVENT = "shiguan:navigate";

export function parsePath(pathname: string): Route {
  const p = pathname || "/";
  if (p === "/" || p === "") return { name: "start", path: "/", params: {} };
  if (p === "/parse") return { name: "parse", path: "/parse", params: {} };
  if (p === "/design-lab")
    return { name: "designlab", path: "/design-lab", params: {} };
  if (p === "/characters") return { name: "select", path: "/characters", params: {} };
  const m = p.match(/^\/characters\/([^/]+)\/?$/);
  if (m) {
    return {
      name: "bio",
      path: p,
      params: { characterId: decodeURIComponent(m[1]) },
    };
  }
  // 真实存档浏览（URL 携带 saveId，可刷新恢复）
  const rm = p.match(/^\/saves\/([^/]+)\/characters\/?$/);
  if (rm) {
    return {
      name: "select",
      path: p,
      params: { saveId: decodeURIComponent(rm[1]) },
    };
  }
  const rmb = p.match(/^\/saves\/([^/]+)\/characters\/([^/]+)\/?$/);
  if (rmb) {
    return {
      name: "bio",
      path: p,
      params: {
        saveId: decodeURIComponent(rmb[1]),
        characterId: decodeURIComponent(rmb[2]),
      },
    };
  }
  return { name: "notfound", path: p, params: {} };
}

// 初始快照（客户端首屏读取真实 pathname，支持刷新恢复）。
let current: Route = parsePath(
  typeof window !== "undefined" ? window.location.pathname : "/",
);

function emitChange() {
  current = parsePath(window.location.pathname);
  window.dispatchEvent(new Event(NAV_EVENT));
}

export function navigate(to: string, replace = false): void {
  if (replace) {
    window.history.replaceState({}, "", to);
  } else {
    window.history.pushState({}, "", to);
  }
  emitChange();
}

function subscribe(cb: () => void): () => void {
  // popstate（浏览器前进/后退）必须重新读取 location 再通知 React，
  // 否则 current 仍是旧快照，路由不会更新。
  const onPop = () => emitChange();
  window.addEventListener("popstate", onPop);
  window.addEventListener(NAV_EVENT, cb);
  return () => {
    window.removeEventListener("popstate", onPop);
    window.removeEventListener(NAV_EVENT, cb);
  };
}

function getSnapshot(): Route {
  // 防御性对齐：若 window.location 与缓存快照不一致（例如测试直接改写 URL、
  // 或在订阅建立前发生过导航），以权威的 window.location 重新对齐，避免读到陈旧路由。
  const fromUrl = parsePath(
    typeof window !== "undefined" ? window.location.pathname : "/",
  );
  if (fromUrl.path !== current.path) current = fromUrl;
  return current;
}

/** 订阅当前路由（前进/后退/程序跳转都会触发更新）。 */
export function useRoute(): Route {
  return useSyncExternalStore(subscribe, getSnapshot);
}

/** 当前路由是否匹配给定 path（用于 Header 高亮 / 面包屑）。 */
export function routeKey(route: Route): string {
  return route.name === "bio" ? "bio" : route.name;
}
