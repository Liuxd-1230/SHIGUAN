import { describe, it, expect } from "vitest";
import { parsePath } from "../router";

describe("router（含临时 /design-lab 路由）", () => {
  it("解析 /design-lab 为 designlab 路由", () => {
    expect(parsePath("/design-lab").name).toBe("designlab");
  });

  it("仍正确解析起始 / 选择 / 传记路由", () => {
    expect(parsePath("/").name).toBe("start");
    expect(parsePath("/characters").name).toBe("select");
    expect(parsePath("/characters/arnulf_001").name).toBe("bio");
    expect(parsePath("/characters/arnulf_001").params.characterId).toBe(
      "arnulf_001",
    );
  });

  it("未知路径回退到 notfound", () => {
    expect(parsePath("/totally/unknown").name).toBe("notfound");
  });
});
