import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import CharacterCard from "../CharacterCard";
import type { CharacterSummary } from "@shiguan/save-schema";

afterEach(cleanup);

function makeSummary(over: Partial<CharacterSummary> = {}): CharacterSummary {
  return {
    id: "1",
    name: "李瑀",
    isAlive: true,
    isRuler: true,
    isPlayerDynasty: false,
    evidenceWarningCount: 0,
    ...over,
  };
}

describe("CharacterCard（M3 主头衔展示）", () => {
  it("有主头衔时显示主头衔名", () => {
    render(
      <CharacterCard
        summary={makeSummary({
          primaryTitle: { id: "k_li", name: "李王国", type: "title", resolved: true },
        })}
        onClick={() => {}}
      />,
    );
    expect(screen.getByText("李王国")).toBeTruthy();
  });

  it("无主头衔时降级为「无头衔」（不伪造）", () => {
    render(<CharacterCard summary={makeSummary({ primaryTitle: undefined })} onClick={() => {}} />);
    expect(screen.getByText("无头衔")).toBeTruthy();
  });

  it("未解析头衔（resolved=false）标注（未解析）", () => {
    render(
      <CharacterCard
        summary={makeSummary({
          primaryTitle: { id: "zz_custom", name: "zz_custom", type: "title", resolved: false },
        })}
        onClick={() => {}}
      />,
    );
    expect(screen.getByText("zz_custom（未解析）")).toBeTruthy();
  });

  it("点击回调携带该人物", () => {
    const onClick = vi.fn();
    render(<CharacterCard summary={makeSummary()} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("统治者徽标与已故状态照常渲染", () => {
    render(<CharacterCard summary={makeSummary({ isAlive: false })} onClick={() => {}} />);
    expect(screen.getByText("统治者")).toBeTruthy();
    expect(screen.getByText("已故")).toBeTruthy();
  });
});
