import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import EvidencePanel from "../EvidencePanel";
import type {
  EvidenceWarning,
  TimelineEvent,
} from "@shiguan/save-schema";

const ev1: TimelineEvent = {
  id: "e1",
  type: "birth",
  title: "出生",
  description: "诞生于宫廷",
  confidence: "confirmed",
  evidence: [
    {
      id: "v1",
      sourceType: "save_block",
      description: "存档人物块",
      confidence: "confirmed",
    },
  ],
};

const evNoPath: TimelineEvent = {
  id: "e2",
  type: "trait_gain",
  title: "获得特质",
  description: "勇武",
  confidence: "inferred",
  evidence: [
    { id: "v2", sourceType: "memory", description: "记忆片段", confidence: "inferred" },
  ],
};

const warnings: EvidenceWarning[] = [
  { code: "w1", message: "与事件 e1 相关", severity: "warning", relatedEventId: "e1" },
  { code: "w2", message: "全局告警", severity: "info" },
  {
    code: "w3",
    message: "与事件 e2 相关（非当前）",
    severity: "error",
    relatedEventId: "e2",
  },
];

describe("EvidencePanel（当前事件告警 / 全局告警分离）", () => {
  it("仅把 relatedEventId 一致的告警归入当前事件告警", () => {
    render(<EvidencePanel event={ev1} warnings={warnings} />);

    const currentSection = screen.getByText("当前事件告警").closest("div") as HTMLElement;
    expect(within(currentSection).getByText("与事件 e1 相关")).toBeInTheDocument();
    expect(
      within(currentSection).queryByText(/与事件 e2 相关/),
    ).not.toBeInTheDocument();

    const globalSection = screen
      .getByText(/人物全局告警/)
      .closest("div") as HTMLElement;
    expect(
      within(globalSection).getByText(/与事件 e2 相关/),
    ).toBeInTheDocument();
    expect(within(globalSection).getByText("全局告警")).toBeInTheDocument();
  });

  it("证据缺失 sourcePath 时给出无法定位提示", () => {
    render(<EvidencePanel event={evNoPath} warnings={[]} />);
    expect(screen.getByText(/来源路径缺失/)).toBeInTheDocument();
  });

  it("证据来源类别显示中文名（如 save_block → 存档数据块）", () => {
    render(<EvidencePanel event={ev1} warnings={[]} />);
    expect(screen.getByText("存档数据块")).toBeInTheDocument();
  });

  it("未选择事件时提示选择时间线事件", () => {
    render(<EvidencePanel warnings={warnings} />);
    expect(screen.getByText(/在时间线中选择一个事件/)).toBeInTheDocument();
  });

  it("3A.1：同 code 全局告警聚合为一条并标计数", () => {
    const dup = [
      { code: "title_holder_conflict", message: "头衔冲突甲", severity: "warning" },
      { code: "title_holder_conflict", message: "头衔冲突乙", severity: "warning" },
      { code: "unresolved_birth", message: "出生日期缺失", severity: "warning" },
    ] as EvidenceWarning[];
    render(<EvidencePanel event={ev1} warnings={dup} />);
    const globalSection = screen
      .getByText(/人物全局告警/)
      .closest("div") as HTMLElement;
    // 两条同 code → 一条带计数；另一条独立。
    expect(within(globalSection).getByText("头衔冲突甲")).toBeInTheDocument();
    expect(within(globalSection).getByText("同类告警 × 2")).toBeInTheDocument();
    expect(within(globalSection).getByText("出生日期缺失")).toBeInTheDocument();
  });
});
