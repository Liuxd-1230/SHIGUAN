import { describe, it, expect, afterEach, beforeEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import App from "../App";
import { resetStore, seedIndex, setPath } from "../test/helpers";
import type { ParsedSaveMeta, CharacterSummary } from "@shiguan/save-schema";

afterEach(cleanup);

describe("App（无障碍骨架）", () => {
  it("提供跳转主内容链接与主内容区", () => {
    render(<App />);
    expect(screen.getByText("跳到主内容")).toBeInTheDocument();
    const main = document.getElementById("main-content");
    expect(main).not.toBeNull();
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("默认渲染起始页标题", () => {
    render(<App />);
    expect(
      screen.getByRole("heading", { name: /读取存档，重写一生/ }),
    ).toBeInTheDocument();
  });
});

// 路由切换（含同一页面不同人物 A→B）后，焦点应移入 <main id="main-content">。
// 该测试同时验证 Phase 1C.1 修复的 mainRef 已正确绑定到 <main>。
const meta: ParsedSaveMeta = {
  saveVersion: "1.0",
  gameVersion: "1.19.0.6",
  date: "1066.9.15",
  playerId: "arnulf_001",
};

const index: CharacterSummary[] = [
  {
    id: "arnulf_001",
    name: "阿努尔夫",
    sex: "male",
    isRuler: true,
    isAlive: true,
    isPlayerDynasty: true,
    evidenceWarningCount: 0,
  },
  {
    id: "lowborn_002",
    name: "无名氏",
    sex: "male",
    isRuler: false,
    isAlive: true,
    isPlayerDynasty: false,
    evidenceWarningCount: 0,
  },
];

describe("App 路由焦点管理", () => {
  beforeEach(() => {
    resetStore();
    seedIndex(meta, index);
    window.history.replaceState({}, "", "/");
  });

  it("切换不同人物后 main 获得焦点", () => {
    render(<App />);
    const main = document.getElementById("main-content");
    expect(main).not.toBeNull();

    act(() => {
      setPath("/characters/arnulf_001");
    });
    expect(document.activeElement).toBe(main);

    // 切换到另一人物（同 route.name=bio，不同 route.path）后焦点仍在 main。
    act(() => {
      setPath("/characters/lowborn_002");
    });
    expect(document.activeElement).toBe(main);
    expect(main).toHaveFocus();
  });
});
