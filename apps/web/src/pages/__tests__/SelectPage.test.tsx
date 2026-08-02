import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import SelectPage from "../SelectPage";
import { resetStore, seedIndex } from "../../test/helpers";
import type { CharacterSummary, ParsedSaveMeta } from "@shiguan/save-schema";

function summary(
  p: Partial<CharacterSummary> & { id: string; name: string },
): CharacterSummary {
  return {
    sex: "male",
    birthDate: "1000.01.01",
    deathDate: undefined,
    dynasty: undefined,
    house: undefined,
    culture: undefined,
    faith: undefined,
    primaryTitle: undefined,
    highestTitleTier: undefined,
    isRuler: false,
    isAlive: true,
    isPlayerDynasty: false,
    evidenceWarningCount: 0,
    ...p,
  };
}

const meta: ParsedSaveMeta = { gameVersion: "1.12.mock" };
const arnulf = summary({
  id: "arnulf",
  name: "阿努尔夫",
  isRuler: true,
  primaryTitle: { id: "t1", name: "巴伐利亚公爵" },
  dynasty: { id: "d1", name: "阿努尔夫家族" },
});
const lowborn = summary({
  id: "lowborn",
  name: "贫民甲",
  primaryTitle: { id: "t2", name: "农夫" },
  dynasty: { id: "d2", name: "平民家族" },
});
const other = summary({
  id: "other",
  name: "某人",
  isRuler: false,
  primaryTitle: { id: "t3", name: "伯爵" },
  dynasty: { id: "d3", name: "阿努尔夫家族" },
});

describe("SelectPage（搜索 / 筛选 / 导航）", () => {
  beforeEach(() => {
    resetStore();
    seedIndex(meta, [arnulf, lowborn, other]);
  });

  it("默认展示全部人物", () => {
    render(<SelectPage />);
    expect(screen.getByText("阿努尔夫")).toBeInTheDocument();
    expect(screen.getByText("贫民甲")).toBeInTheDocument();
    expect(screen.getByText("某人")).toBeInTheDocument();
  });

  it("按姓名搜索过滤", () => {
    render(<SelectPage />);
    // 用仅出现在 name 中的串，避免与王朝/头衔子串误匹配
    fireEvent.change(screen.getByPlaceholderText(/搜索姓名/), {
      target: { value: "贫民甲" },
    });
    expect(screen.getByText("贫民甲")).toBeInTheDocument();
    expect(screen.queryByText("阿努尔夫")).not.toBeInTheDocument();
    expect(screen.queryByText("某人")).not.toBeInTheDocument();
  });

  it("按头衔搜索过滤", () => {
    render(<SelectPage />);
    fireEvent.change(screen.getByPlaceholderText(/搜索姓名/), {
      target: { value: "伯爵" },
    });
    expect(screen.getByText("某人")).toBeInTheDocument();
    expect(screen.queryByText("阿努尔夫")).not.toBeInTheDocument();
  });

  it("按王朝搜索过滤", () => {
    render(<SelectPage />);
    fireEvent.change(screen.getByPlaceholderText(/搜索姓名/), {
      target: { value: "阿努尔夫家族" },
    });
    expect(screen.getByText("阿努尔夫")).toBeInTheDocument();
    expect(screen.getByText("某人")).toBeInTheDocument();
    expect(screen.queryByText("贫民甲")).not.toBeInTheDocument();
  });

  it("仅显示统治者筛选", () => {
    render(<SelectPage />);
    fireEvent.click(screen.getByLabelText(/仅显示统治者/));
    expect(screen.getByText("阿努尔夫")).toBeInTheDocument();
    expect(screen.queryByText("贫民甲")).not.toBeInTheDocument();
    expect(screen.queryByText("某人")).not.toBeInTheDocument();
  });

  it("点击人物卡片跳转到其传记路由", () => {
    render(<SelectPage />);
    fireEvent.click(screen.getByText("阿努尔夫"));
    expect(window.location.pathname).toBe("/characters/arnulf");
  });

  it("无匹配人物时给出空状态提示", () => {
    render(<SelectPage />);
    fireEvent.change(screen.getByPlaceholderText(/搜索姓名/), {
      target: { value: "不存在的人" },
    });
    expect(screen.getByText(/没有匹配的人物/)).toBeInTheDocument();
    const grid = screen.getByText(/没有匹配的人物/).closest("div");
    expect(within(grid as HTMLElement).queryByText("阿努尔夫")).not.toBeInTheDocument();
  });
});
