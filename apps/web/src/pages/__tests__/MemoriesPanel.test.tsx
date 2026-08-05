import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import MemoriesPanel from "../../components/MemoriesPanel";
import type { CharacterProfile } from "@shiguan/save-schema";

afterEach(cleanup);

/** 最小完整档案：只填充 M4 相关字段，其余按契约给空。 */
function profile(overrides: Partial<CharacterProfile>): CharacterProfile {
  return {
    id: "arnulf_001",
    name: "阿努尔夫",
    traits: [],
    titles: [],
    residences: [],
    courtPositions: [],
    parents: [],
    spouses: [],
    children: [],
    siblings: [],
    friends: [],
    rivals: [],
    lovers: [],
    wars: [],
    imprisonments: [],
    travels: [],
    memories: [],
    timeline: [],
    evidenceWarnings: [],
    ...overrides,
  } as CharacterProfile;
}

describe("MemoriesPanel（M4 关系与记忆）", () => {
  it("空态：无关系无记忆时展示诚实降级文案", () => {
    render(<MemoriesPanel profile={profile({})} />);
    expect(screen.getByText("关系与记忆")).toBeTruthy();
    expect(screen.getByText(/未找到该人物的可解析条目/)).toBeTruthy();
  });

  it("展示配偶/婚约/妾室与前任的语义标签", () => {
    render(
      <MemoriesPanel
        profile={profile({
          spouses: [
            {
              characterId: "beatrix",
              name: "贝亚特丽克丝",
              type: "spouse",
              confidence: "confirmed",
              sourcePath: "character/arnulf/spouse/beatrix",
            },
            {
              characterId: "gertrude",
              name: "格特鲁德",
              type: "spouse",
              confidence: "confirmed",
              isFormer: true,
              sourcePath: "character/arnulf/former_spouses/gertrude",
            },
            {
              characterId: "bertha",
              name: "贝尔莎",
              type: "betrothed",
              confidence: "confirmed",
              sourcePath: "character/arnulf/betrothed/bertha",
            },
            {
              characterId: "li",
              name: "李姬",
              type: "concubine",
              confidence: "confirmed",
              isFormer: true,
              sourcePath: "character/arnulf/former_concubines/li",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("配偶与婚约")).toBeTruthy();
    expect(screen.getByText("贝亚特丽克丝")).toBeTruthy();
    expect(screen.getByText("配偶")).toBeTruthy();
    expect(screen.getByText("格特鲁德")).toBeTruthy();
    expect(screen.getByText("前配偶")).toBeTruthy();
    expect(screen.getByText("贝尔莎")).toBeTruthy();
    expect(screen.getByText("婚约")).toBeTruthy();
    expect(screen.getByText("李姬")).toBeTruthy();
    expect(screen.getByText("前妾室")).toBeTruthy();
  });

  it("好友/宿敌/恋人分组展示计数与推断徽标；兄弟姐妹无推断徽标", () => {
    render(
      <MemoriesPanel
        profile={profile({
          siblings: [{ id: "konrad", name: "康拉德" }],
          friends: [{ id: "sieg", name: "西格主教" }],
          rivals: [{ id: "otto", name: "奥托公爵" }],
          lovers: [{ id: "ada", name: "阿达" }],
        })}
      />,
    );
    expect(screen.getByText("兄弟姐妹")).toBeTruthy();
    expect(screen.getByText("康拉德")).toBeTruthy();
    expect(screen.getByText("好友")).toBeTruthy();
    expect(screen.getByText("西格主教")).toBeTruthy();
    expect(screen.getByText("宿敌")).toBeTruthy();
    expect(screen.getByText("奥托公爵")).toBeTruthy();
    expect(screen.getByText("恋人")).toBeTruthy();
    expect(screen.getByText("阿达")).toBeTruthy();
    // 好友/宿敌/恋人三组均标"推断"，兄弟姐妹不标
    expect(screen.getAllByText("推断")).toHaveLength(3);
  });

  it("记忆列表按日期升序展示，未知日期排最后", () => {
    render(
      <MemoriesPanel
        profile={profile({
          memories: [
            {
              id: "mem_1",
              type: "marriage",
              date: "1055.6.20",
              description: "与贝亚特丽克丝成婚。",
              relatedCharacters: [],
              confidence: "confirmed",
              sourcePath: "memory/arnulf/1",
            },
            {
              id: "mem_2",
              type: "child_birth",
              date: "1057.5.30",
              description: "长子海因里希出生。",
              relatedCharacters: [],
              confidence: "confirmed",
              sourcePath: "memory/arnulf/2",
            },
            {
              id: "mem_3",
              type: "death",
              description: "无日期记忆：只入列表，不伪造事件时间。",
              relatedCharacters: [],
              confidence: "uncertain",
              sourcePath: "memory/arnulf/3",
            },
          ],
        })}
      />,
    );
    const list = screen.getAllByRole("list");
    // 记忆列表是第二个 <ul>（关系分组为空时仅此一个，直接用第一个列表断言顺序）
    const ul = list[0];
    const texts = Array.from(ul.querySelectorAll("p")).map((p) => p.textContent);
    expect(texts.indexOf("与贝亚特丽克丝成婚。")).toBeLessThan(
      texts.indexOf("长子海因里希出生。"),
    );
    expect(texts.indexOf("长子海因里希出生。")).toBeLessThan(
      texts.indexOf("无日期记忆：只入列表，不伪造事件时间。"),
    );
    // 无日期记忆显示"日期不详"
    expect(screen.getByText("日期不详")).toBeTruthy();
  });

  it("父母/子女分组展示（2C.2：引用名已含姓，如梁活）", () => {
    render(
      <MemoriesPanel
        profile={profile({
          parents: [{ id: "p1", name: "梁父" }],
          children: [
            { id: "c1", name: "梁活" },
            { id: "c2", name: "梁吉定" },
          ],
        })}
      />,
    );
    expect(screen.getByText("父母")).toBeTruthy();
    expect(screen.getByText("梁父")).toBeTruthy();
    expect(screen.getByText("子女")).toBeTruthy();
    expect(screen.getByText("梁活")).toBeTruthy();
    expect(screen.getByText("梁吉定")).toBeTruthy();
  });

  it("未解析人名（name==id）标注（未解析）", () => {
    render(
      <MemoriesPanel
        profile={profile({
          friends: [{ id: "unknown_5", name: "unknown_5" }],
        })}
      />,
    );
    expect(screen.getByText("（未解析）")).toBeTruthy();
  });
});
