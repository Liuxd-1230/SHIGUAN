import { describe, it, expect } from "vitest";
import {
  isCacheableStaticPath,
  isNeverCachePath,
  isAppNavigationPath,
} from "../swCachePolicy";

describe("swCachePolicy（PWA 缓存路径判定，纯函数）", () => {
  it("同源静态资源（/assets/ 与 shell）可缓存", () => {
    expect(isCacheableStaticPath("/assets/app.abc.js")).toBe(true);
    expect(isCacheableStaticPath("/assets/oriental/paper-texture.png")).toBe(true);
    expect(isCacheableStaticPath("/")).toBe(true);
    expect(isCacheableStaticPath("/index.html")).toBe(true);
    expect(isCacheableStaticPath("/manifest.webmanifest")).toBe(true);
    expect(isCacheableStaticPath("/icon.svg")).toBe(true);
  });

  it("私有数据路径永不缓存", () => {
    expect(isCacheableStaticPath("/api/foo")).toBe(false);
    expect(isCacheableStaticPath("/uploads/x")).toBe(false);
    expect(isCacheableStaticPath("/saves/x")).toBe(false);
    expect(isNeverCachePath("/api/")).toBe(true);
  });

  it("非 GET 请求不缓存", () => {
    expect(isCacheableStaticPath("/assets/app.js", "POST")).toBe(false);
  });

  it("SPA 应用路由离线回退到 index.html", () => {
    expect(isAppNavigationPath("/")).toBe(true);
    expect(isAppNavigationPath("/parse")).toBe(true);
    expect(isAppNavigationPath("/characters")).toBe(true);
    expect(isAppNavigationPath("/design-lab")).toBe(true);
    expect(isAppNavigationPath("/characters/arnulf_001")).toBe(true);
    expect(isAppNavigationPath("/unknown")).toBe(false);
  });
});
