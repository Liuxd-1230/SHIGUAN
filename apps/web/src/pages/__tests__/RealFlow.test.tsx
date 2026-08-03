import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SelectPage from "../SelectPage";
import BiographyPage from "../BiographyPage";
import { resetStore, setPath } from "../../test/helpers";
import { resetProfileInflight } from "../../store";
import { api } from "../../lib/api";
import { setActiveSaveId } from "../../lib/realRepository";
import type { CharacterProfile, CharacterSummary } from "@shiguan/save-schema";

const SAVE_ID = "save_001";

function fakeSummary(id: string, name: string): CharacterSummary {
  return {
    id,
    name,
    sex: "male",
    birthDate: "1000.1.1",
    deathDate: undefined,
    isAlive: true,
    isRuler: false,
    isPlayerDynasty: false,
    culture: undefined,
    faith: undefined,
    dynasty: undefined,
    primaryTitle: undefined,
    highestTitleRank: undefined,
    evidenceWarningCount: 0,
  } as unknown as CharacterSummary;
}

function fakeProfile(id: string): CharacterProfile {
  return {
    id,
    name: id,
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
    timeline: [
      {
        id: "e1",
        date: "1000.1.1",
        kind: "birth",
        title: "出生",
        description: "诞生",
        confidence: "confirmed",
        evidence: [],
      },
    ],
    evidenceWarnings: [],
  } as unknown as CharacterProfile;
}

class TestIO {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}

beforeEach(() => {
  resetStore();
  resetProfileInflight();
  setActiveSaveId(null, null);
  vi.restoreAllMocks();
  globalThis.IntersectionObserver = TestIO as unknown as typeof IntersectionObserver;
  window.matchMedia = ((q: string) => ({
    matches: false,
    media: q,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("真实存档选择页（按需分页，不存全量）", () => {
  it("首屏仅加载一页，并显示总数与翻页", async () => {
    const listMock = vi.fn(async (_sid: string, opts: { offset?: number; q?: string }) => {
      const off = opts?.offset ?? 0;
      const items =
        off === 0
          ? [fakeSummary("6432", "张三"), fakeSummary("6433", "李四")]
          : [fakeSummary("7000", "王五")];
      return {
        saveId: SAVE_ID,
        total: 100,
        offset: off,
        limit: 48,
        hasMore: off + 48 < 100,
        items,
      };
    });
    vi.spyOn(api, "listCharacters").mockImplementation(listMock);

    setPath(`/saves/${SAVE_ID}/characters`);
    render(<SelectPage />);

    // 首屏一页
    expect(await screen.findByText("张三")).toBeTruthy();
    expect(screen.getByText(/本存档共 100 位人物/)).toBeTruthy();
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(listMock.mock.calls[0][1]).toMatchObject({ offset: 0, limit: 48 });

    // 翻到下一页
    fireEvent.click(screen.getByText("下一页"));
    expect(await screen.findByText("王五")).toBeTruthy();
    expect(listMock).toHaveBeenCalledTimes(2);
    expect(listMock.mock.calls[1][1]).toMatchObject({ offset: 48 });
  });

  it("搜索经防抖后触发带 q 的请求，并重置到第一页", async () => {
    const listMock = vi.fn(async (_sid: string, opts: { offset?: number; q?: string }) => {
      const q = opts?.q;
      const items = q ? [fakeSummary("6432", "张三")] : [fakeSummary("6432", "张三"), fakeSummary("6433", "李四")];
      return {
        saveId: SAVE_ID,
        total: q ? 1 : 100,
        offset: 0,
        limit: 48,
        hasMore: false,
        items,
      };
    });
    vi.spyOn(api, "listCharacters").mockImplementation(listMock);

    setPath(`/saves/${SAVE_ID}/characters`);
    render(<SelectPage />);
    await screen.findByText("张三");

    const input = screen.getByLabelText("搜索人物") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "张" } });

    await waitFor(() => {
      const calls = listMock.mock.calls;
      expect(calls.some((c) => c[1]?.q === "张")).toBe(true);
    });
    const last = listMock.mock.calls[listMock.mock.calls.length - 1];
    expect(last[1]).toMatchObject({ q: "张", offset: 0 });
  });
});

describe("真实存档传记页（URL 恢复，不依赖全量索引）", () => {
  it("进入即经后端按需取档并渲染，返回回到真实选择页", async () => {
    const getMock = vi.fn(async (_sid: string, id: string) => fakeProfile(id));
    vi.spyOn(api, "getProfile").mockImplementation(getMock);

    setPath(`/saves/${SAVE_ID}/characters/6432`);
    render(<BiographyPage />);

    // 真实模式：无全量索引也应触发后端取档
    await waitFor(() => {
      expect(getMock).toHaveBeenCalledWith(SAVE_ID, "6432");
    });
    expect(await screen.findByRole("heading", { name: "6432" })).toBeTruthy();

    // 返回按钮回到真实选择页路由
    fireEvent.click(screen.getByRole("button", { name: /返回选择页/ }));
    expect(window.location.pathname).toBe(`/saves/${SAVE_ID}/characters`);
  });

  it("后端取档失败时显示错误态（不白屏）", async () => {
    const getMock = vi.fn(async () => {
      throw new Error("reader_error");
    });
    vi.spyOn(api, "getProfile").mockImplementation(getMock);

    setPath(`/saves/${SAVE_ID}/characters/6432`);
    render(<BiographyPage />);

    expect(await screen.findByText(/档案载入失败/)).toBeTruthy();
    expect(screen.getByText(/reader_error/)).toBeTruthy();
  });
});
