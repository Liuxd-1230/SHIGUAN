import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { TitlesPanel } from "../BiographyPage";
import type { TitlePeriod } from "@shiguan/save-schema";

afterEach(cleanup);

const current: TitlePeriod = {
  titleId: "k_li",
  name: "李王国",
  tier: "kingdom",
  start: "780.5.10",
  end: undefined,
  isCurrent: true,
  sourcePath: "landed_titles/k_li",
};

const historical: TitlePeriod = {
  titleId: "d_li",
  name: "李公爵领",
  tier: "duchy",
  start: "760.1.1",
  end: "780.5.9",
  isCurrent: false,
  sourcePath: "landed_titles/d_li",
};

describe("TitlesPanel（M3 当前与历史头衔）", () => {
  it("无头衔时展示诚实降级文案", () => {
    render(<TitlesPanel titles={[]} />);
    expect(screen.getByText("头衔与统治")).toBeTruthy();
    expect(screen.getByText(/未找到该人物的头衔/)).toBeTruthy();
  });

  it("分开展示现任与历史任期，含等级与起止", () => {
    render(<TitlesPanel titles={[current, historical]} />);
    expect(screen.getByText("现任")).toBeTruthy();
    expect(screen.getByText("历史任期")).toBeTruthy();
    expect(screen.getByText("李王国")).toBeTruthy();
    expect(screen.getByText("王国")).toBeTruthy();
    expect(screen.getByText("780.5.10 起")).toBeTruthy();
    expect(screen.getByText("李公爵领")).toBeTruthy();
    expect(screen.getByText("公爵领")).toBeTruthy();
    expect(screen.getByText("760.1.1 – 780.5.9")).toBeTruthy();
  });

  it("未解析头衔（name==titleId）标注（未解析）", () => {
    render(
      <TitlesPanel
        titles={[
          { ...current, titleId: "zz_custom", name: "zz_custom", tier: undefined },
        ]}
      />,
    );
    expect(screen.getByText("（未解析）")).toBeTruthy();
    expect(screen.getByText("等级不详")).toBeTruthy();
  });
});
