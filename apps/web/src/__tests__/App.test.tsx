import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import App from "../App";

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
