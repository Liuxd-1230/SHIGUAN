import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  EntityListSection,
  HistoricalEventsSection,
  IdentitySection,
  TerritorySection,
} from "../SemanticSections";
import type {
  CharacterIdentity,
  EntityRef,
  HistoricalSemanticEvent,
} from "@shiguan/save-schema";

const ref = (id: string, name: string, resolved = true): EntityRef => ({
  id,
  name,
  type: "title",
  resolved,
});

describe("IdentitySection（3C.2 主要身份）", () => {
  it("渲染 headline / realmStatus / 主领地，不按 tier 硬编码爵位", () => {
    const identity: CharacterIdentity = {
      headlineIdentity: "「梁克贞」的最高统治者",
      realmStatus: "independent_ruler",
      primaryRealmTitle: ref("k_liang", "梁朝"),
      confidence: "confirmed",
      evidence: [],
    };
    render(<IdentitySection identity={identity} />);
    expect(screen.getByRole("heading", { name: "主要身份" })).toBeInTheDocument();
    expect(screen.getByText("「梁克贞」的最高统治者")).toBeInTheDocument();
    expect(screen.getByText("独立最高统治者")).toBeInTheDocument();
    expect(screen.getByText(/主领地：梁朝/)).toBeInTheDocument();
  });

  it("无 identity 时返回 null（不渲染空块）", () => {
    const { container } = render(<IdentitySection />);
    expect(container.firstChild).toBeNull();
  });

  it("unknown 状态如实标注，且渲染 warnings", () => {
    const identity: CharacterIdentity = {
      headlineIdentity: "「某君」的领主",
      realmStatus: "unknown",
      confidence: "uncertain",
      evidence: [],
      warnings: ["当前头衔结构无法判定身份"],
    };
    render(<IdentitySection identity={identity} />);
    expect(screen.getByText("无法判定")).toBeInTheDocument();
    expect(screen.getByText("当前头衔结构无法判定身份")).toBeInTheDocument();
  });
});

describe("EntityListSection（3C.2 官职/机构/荣誉）", () => {
  it("渲染条目与未解析标注；空列表不渲染", () => {
    const { rerender, container } = render(
      <EntityListSection title="个人官职" items={[ref("e_shizheng", "政事堂")]} />,
    );
    expect(screen.getByRole("heading", { name: "个人官职" })).toBeInTheDocument();
    expect(screen.getByText("政事堂")).toBeInTheDocument();

    rerender(<EntityListSection title="个人官职" items={undefined} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("TerritorySection（3C.2 领土）", () => {
  it("主要领土与下属领地分组展示", () => {
    render(
      <TerritorySection
        major={[ref("k_liang", "梁朝")]}
        subordinate={[ref("c_youji", "幽蓟", false)]}
      />,
    );
    expect(screen.getByRole("heading", { name: "领土" })).toBeInTheDocument();
    expect(screen.getByText("主要领土")).toBeInTheDocument();
    expect(screen.getByText("下属领地")).toBeInTheDocument();
    expect(screen.getByText("幽蓟")).toBeInTheDocument();
    expect(screen.getByText("（未解析）")).toBeInTheDocument();
  });

  it("无领土时不渲染", () => {
    const { container } = render(<TerritorySection />);
    expect(container.firstChild).toBeNull();
  });
});

describe("HistoricalEventsSection（3C.3 统治历程）", () => {
  it("按日期数值排序（944.4.20 在 944.10.22 之前，非字符串序）", () => {
    const events: HistoricalSemanticEvent[] = [
      {
        eventId: "p-identity_transition-944.10.22",
        semanticType: "identity_transition",
        date: "944.10.22",
        summary: "后一条",
        confidence: "confirmed",
        evidence: [],
        acquisitionCause: "unknown",
        narrativeConstraints: ["不得推断原因"],
      },
      {
        eventId: "p-identity_transition-944.4.20",
        semanticType: "identity_transition",
        date: "944.4.20",
        summary: "前一条",
        confidence: "confirmed",
        evidence: [],
      },
    ];
    render(<HistoricalEventsSection events={events} />);
    const summaries = screen
      .getAllByText(/前一条|后一条/)
      .map((el) => el.textContent);
    expect(summaries).toEqual(["前一条", "后一条"]);
  });

  it("无事件时不渲染", () => {
    const { container } = render(<HistoricalEventsSection />);
    expect(container.firstChild).toBeNull();
  });
});
