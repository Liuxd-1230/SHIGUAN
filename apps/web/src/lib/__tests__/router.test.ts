import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { parsePath, navigate, useRoute, ROUTES } from "../router";

/**
 * 轻量路由验证：
 *  - parsePath 正确识别各路由及人物 id（含编解码），直接访问人物页可恢复
 *  - navigate 通过自定义事件驱动 useRoute 更新（程序内跳转）
 *  - popstate（浏览器前进/后退）驱动 useRoute 重新读取 location
 */
describe("轻量路由（History API）", () => {
  it("parsePath 正确识别各路由与人物 id（含编解码）", () => {
    expect(parsePath("/").name).toBe("start");
    expect(parsePath("/parse").name).toBe("parse");
    expect(parsePath("/characters").name).toBe("select");
    const bio = parsePath("/characters/arnulf_001");
    expect(bio.name).toBe("bio");
    expect(bio.params.characterId).toBe("arnulf_001");
    // 刷新恢复：含空格的 id 编解码正确
    expect(parsePath("/characters/with%20space").params.characterId).toBe("with space");
    expect(parsePath("/unknown/path").name).toBe("notfound");
  });

  it("parsePath 正确识别真实存档路由（携带 saveId，可刷新恢复）", () => {
    const sel = parsePath("/saves/my%20save/characters");
    expect(sel.name).toBe("select");
    expect(sel.params.saveId).toBe("my save");
    const bio = parsePath("/saves/save_001/characters/6432");
    expect(bio.name).toBe("bio");
    expect(bio.params.saveId).toBe("save_001");
    expect(bio.params.characterId).toBe("6432");
    // 与 Mock 路由不冲突
    expect(parsePath("/characters").params.saveId).toBeUndefined();
    expect(parsePath("/characters/arnulf_001").params.saveId).toBeUndefined();
  });

  it("navigate 通过自定义事件驱动 useRoute 更新", () => {
    window.history.replaceState({}, "", "/");
    const { result } = renderHook(() => useRoute());
    expect(result.current.name).toBe("start");

    act(() => navigate("/characters"));
    expect(result.current.name).toBe("select");

    act(() => navigate(ROUTES.character("arnulf_001")));
    expect(result.current.name).toBe("bio");
    expect(result.current.params.characterId).toBe("arnulf_001");
  });

  it("浏览器前进/后退（popstate）驱动 useRoute 重新读取 location", () => {
    const { result, rerender } = renderHook(() => useRoute());

    // 用通用 Event("popstate") 触发监听（jsdom 下 PopStateEvent 构造不一定派发监听）。
    // 监听同步调用 emitChange 更新 current，rerender 强制读到最新快照。
    window.history.replaceState({}, "", "/parse");
    window.dispatchEvent(new Event("popstate"));
    rerender();
    expect(result.current.name).toBe("parse");

    // 前进到 /characters
    window.history.pushState({}, "", "/characters");
    window.dispatchEvent(new Event("popstate"));
    rerender();
    expect(result.current.name).toBe("select");

    // 再前进到 /parse（模拟来回切换，两端都应生效）
    window.history.pushState({}, "", "/parse");
    window.dispatchEvent(new Event("popstate"));
    rerender();
    expect(result.current.name).toBe("parse");
  });
});
