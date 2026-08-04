import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import EvidenceBadge from "../EvidenceBadge";
import SealButton from "../SealButton";
import TimelineNode from "../TimelineNode";
import InkDivider from "../InkDivider";
import PageHeading from "../PageHeading";
import MuseumSurface from "../MuseumSurface";
import ScrollPanel from "../ScrollPanel";
import EmptyState from "../EmptyState";
import type { TimelineEvent } from "@shiguan/save-schema";

afterEach(cleanup);

const ev: TimelineEvent = {
  id: "e1",
  type: "birth",
  title: "诞生",
  description: "样例",
  date: "1001.01.01",
  confidence: "confirmed",
  evidence: [],
};

describe("EvidenceBadge（图标 + 形状 + 文字，不靠颜色）", () => {
  it("三种置信度都同时渲染文字标签与图标", () => {
    const { container } = render(
      <div>
        <EvidenceBadge value="confirmed" />
        <EvidenceBadge value="inferred" />
        <EvidenceBadge value="uncertain" />
      </div>,
    );
    expect(screen.getByText("确认")).toBeInTheDocument();
    expect(screen.getByText("推断")).toBeInTheDocument();
    expect(screen.getByText("存疑")).toBeInTheDocument();
    expect(container.querySelectorAll("svg").length).toBeGreaterThanOrEqual(3);
  });

  it("提供 tooltip 说明置信度", () => {
    render(<EvidenceBadge value="uncertain" />);
    expect(screen.getByTitle("证据置信度：存疑")).toBeInTheDocument();
  });

  it("showLabel=false 时仅保留图标形状", () => {
    const { container } = render(<EvidenceBadge value="confirmed" showLabel={false} />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(screen.queryByText("确认")).not.toBeInTheDocument();
  });
});

describe("SealButton（四态 / 触控高度 / 语义）", () => {
  it("默认是原生 button 且最小触控高度达标", () => {
    render(<SealButton>载入</SealButton>);
    const btn = screen.getByRole("button", { name: "载入" });
    expect(btn).toHaveAttribute("type", "button");
    expect(btn.className).toContain("min-h-[2.75rem]");
  });

  it("seal 时在左侧渲染图标", () => {
    const { container } = render(<SealButton seal>印</SealButton>);
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("点击触发 onClick", () => {
    let clicked = false;
    render(<SealButton onClick={() => (clicked = true)}>去</SealButton>);
    fireEvent.click(screen.getByRole("button", { name: "去" }));
    expect(clicked).toBe(true);
  });
});

describe("TimelineNode（键盘可达 / aria-current）", () => {
  it("激活项标记 aria-current 且点击回调", () => {
    let picked = "";
    render(
      <TimelineNode event={ev} active onSelect={(id) => (picked = id)} inChapter={false} />,
    );
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-current", "true");
    fireEvent.click(btn);
    expect(picked).toBe("e1");
  });

  it("渲染日期与标题", () => {
    render(<TimelineNode event={ev} active={false} onSelect={() => {}} inChapter={false} />);
    expect(screen.getByText("1001.01.01")).toBeInTheDocument();
    expect(screen.getByText("诞生")).toBeInTheDocument();
  });

  it("非激活项不标记 aria-current", () => {
    render(<TimelineNode event={ev} active={false} onSelect={() => {}} inChapter />);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-current");
  });

  it("mergedCount>1 时显示「已合并 N 条记录」徽标", () => {
    render(
      <TimelineNode
        event={{ ...ev, mergedCount: 2 }}
        active={false}
        onSelect={() => {}}
        inChapter={false}
      />,
    );
    expect(screen.getByText("已合并 2 条记录")).toBeInTheDocument();
  });

  it("mergedCount 缺省/为 1 时不显示合并徽标", () => {
    const { container } = render(
      <TimelineNode
        event={ev}
        active={false}
        onSelect={() => {}}
        inChapter={false}
      />,
    );
    expect(screen.queryByText(/已合并/)).not.toBeInTheDocument();
    expect(container.querySelectorAll("span").length).toBeGreaterThan(0);
  });

  it("relatedTitles>1 时显示「聚合 N 个头衔」徽标（含头衔名 tooltip）", () => {
    render(
      <TimelineNode
        event={{
          ...ev,
          relatedTitles: [
            { id: "c_a", name: "甲伯爵领", type: "title", resolved: true },
            { id: "c_b", name: "乙伯爵领", type: "title", resolved: true },
          ],
        }}
        active={false}
        onSelect={() => {}}
        inChapter={false}
      />,
    );
    expect(screen.getByText("聚合 2 个头衔")).toBeInTheDocument();
  });

  it("relatedTitles 缺省/单个时不显示聚合徽标", () => {
    render(<TimelineNode event={ev} active={false} onSelect={() => {}} inChapter={false} />);
    expect(screen.queryByText(/聚合/)).not.toBeInTheDocument();
  });
});

describe("InkDivider（装饰分隔线）", () => {
  it("默认作为装饰（aria-hidden，不进入无障碍树）", () => {
    const { container } = render(<InkDivider />);
    const hr = container.querySelector("hr");
    expect(hr).not.toBeNull();
    expect(hr).toHaveAttribute("aria-hidden", "true");
  });

  it("提供 label 时以 aria-label 暴露于无障碍树", () => {
    render(<InkDivider label="章节分隔" />);
    const sep = screen.getByRole("separator");
    expect(sep).toHaveAttribute("aria-label", "章节分隔");
    expect(sep).not.toHaveAttribute("aria-hidden");
    expect(screen.getByText("章节分隔")).toBeInTheDocument();
  });
});

describe("PageHeading（语义层级）", () => {
  it("按 level 渲染对应标题标签", () => {
    const { container } = render(<PageHeading title="标题" level={2} eyebrow="眉题" />);
    expect(container.querySelector("h2")?.textContent).toBe("标题");
    expect(screen.getByText("眉题")).toBeInTheDocument();
  });
});

describe("MuseumSurface / ScrollPanel / EmptyState", () => {
  it("MuseumSurface 透传 variant 与 as", () => {
    const { container } = render(
      <MuseumSurface variant="raised" as="section">
        内容
      </MuseumSurface>,
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.tagName).toBe("SECTION");
    expect(el.className).toContain("rounded-2xl");
  });

  it("ScrollPanel 透传 id（供滚动同步定位）", () => {
    render(<ScrollPanel id="chapter-x">正文</ScrollPanel>);
    expect(document.getElementById("chapter-x")?.textContent).toContain("正文");
  });

  it("EmptyState 以 role=status 呈现标题/描述/动作", () => {
    render(
      <EmptyState title="空" description="暂无" action={<button type="button">重试</button>} />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("空")).toBeInTheDocument();
    expect(screen.getByText("暂无")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});
