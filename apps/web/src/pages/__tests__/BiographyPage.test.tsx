import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  waitFor,
  within,
} from "@testing-library/react";
import BiographyPage from "../BiographyPage";
import { resetStore, seedIndex, setPath } from "../../test/helpers";
import { useStore, resetProfileInflight, profileCacheKey, MOCK_SAVE_ID } from "../../store";
import { mockCharacterRepository } from "../../lib/characterRepository";
import indexJson from "@mock/index.json";
import type {
  CharacterProfile,
  CharacterSummary,
  ParsedSaveMeta,
} from "@shiguan/save-schema";

// 复用真实索引摘要（含 arnulf_001 / lowborn_002 / incomplete_003），
// 便于以真实 fixture 驱动"按需取档"测试。
const envelope = indexJson as unknown as {
  data: { meta: ParsedSaveMeta; characterIndex: CharacterSummary[] };
};
const mockMeta = envelope.data.meta;
const mockSummaries = envelope.data.characterIndex;

const originalIO = globalThis.IntersectionObserver;
const originalMatchMedia = window.matchMedia;

/**
 * 可控 IntersectionObserver：记录实例、被观察元素与断开情况，并暴露回调供测试
 * 手动触发"进入视口"。framer-motion 的 whileInView 也会创建自己的 observer，
 * 因此用"是否观察了 chapter-* 元素"来唯一定位传记页自身的 observer。
 */
class TestIO {
  static instances: TestIO[] = [];
  cb: IntersectionObserverCallback;
  observed: Element[] = [];
  disconnected = false;
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb;
    TestIO.instances.push(this);
  }
  observe(el: Element) {
    this.observed.push(el);
  }
  unobserve(el: Element) {
    this.observed = this.observed.filter((e) => e !== el);
  }
  disconnect() {
    this.disconnected = true;
    this.observed = [];
  }
  takeRecords() {
    return [];
  }
}

function getBioObserver(): TestIO {
  const el = document.querySelector('[id^="chapter-"]');
  const inst = TestIO.instances.find(
    (i) => !!el && i.observed.includes(el as Element),
  );
  if (!inst) throw new Error("未找到传记页的 IntersectionObserver 实例");
  return inst;
}

/** 按查询字符串切换 matchMedia 行为（桌面 / 减弱动效）。 */
function stubMatchMedia(matchesFor: (q: string) => boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: matchesFor(query),
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
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
    timeline: [],
    evidenceWarnings: [],
  } as unknown as CharacterProfile;
}

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: unknown) => void;
}
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** 安装可控仓库：每次 loadProfile 返回一个可单独 resolve/reject 的 Promise。 */
function installControllableRepo() {
  const calls: { id: string; d: Deferred<CharacterProfile> }[] = [];
  const spy = vi.spyOn(mockCharacterRepository, "loadProfile");
  spy.mockImplementation((id: string) => {
    const d = deferred<CharacterProfile>();
    calls.push({ id, d });
    return d.promise;
  });
  return {
    spy,
    calls,
    resolveNth(n: number, p: CharacterProfile) {
      calls[n].d.resolve(p);
    },
    rejectNth(n: number, e: unknown) {
      calls[n].d.reject(e);
    },
  };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

/**
 * 先挂载组件（让路由器订阅生效），再以编程方式切到目标路由。
 * 这样 setPath 派发的 popstate 能被路由器的监听器捕获，characterId 才会正确更新。
 */
async function renderAt(path: string) {
  const utils = render(<BiographyPage />);
  await act(async () => {
    setPath(path);
  });
  return utils;
}

beforeEach(() => {
  resetStore();
  seedIndex(mockMeta, mockSummaries);
  TestIO.instances = [];
  globalThis.IntersectionObserver = TestIO as unknown as typeof IntersectionObserver;
  stubMatchMedia(() => false); // 默认：非桌面、不减弱动效
  // 路由器 current 是模块级单例，会跨测试残留（上一测试改动过的 window.location）。
  // 把 URL 复位到起始页；getSnapshot 会在组件挂载时据此对齐 current，避免误读旧路由。
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.restoreAllMocks();
  resetProfileInflight();
  resetStore();
  globalThis.IntersectionObserver = originalIO;
  window.matchMedia = originalMatchMedia;
});

describe("BiographyPage（按需取档 / 双向联动 / 无障碍 / 动效边界）", () => {
  it("1) 初次访问按需载入完整档案，且展示姓名与传记章节", async () => {
    await renderAt("/characters/arnulf_001");
    // 先出现按需加载态（仅当该人物未在缓存时取档）
    expect(screen.getByText(/正在载入「arnulf_001」/)).toBeInTheDocument();
    // 档案就绪后展示姓名与"史料摘要"小节（3A.1：确定性史料摘要，非 AI 正文）
    expect(await screen.findByText("阿努尔夫")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "史料摘要" })).toBeInTheDocument();
  });

  it("2) 索引中不存在的人物：给出未找到提示，且不发起取档", async () => {
    const spy = vi.spyOn(mockCharacterRepository, "loadProfile");
    await renderAt("/characters/ghost_999");
    expect(await screen.findByText("未找到该人物")).toBeInTheDocument();
    // 索引中无此人，loadProfile 不应被调用（避免无谓取档与错误态）
    expect(spy).not.toHaveBeenCalled();
  });

  it("3) 点击时间线节点更新当前事件并联动史料依据面板", async () => {
    // 减弱动效：让 EvidencePanel 的 mode="wait" 切换在 jsdom 中即时完成（退出动画不会卡住）。
    stubMatchMedia((q) => q.includes("prefers-reduced-motion"));
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const warButton = within(timelineSection)
      .getByText("发动继承战争")
      .closest("button") as HTMLButtonElement;
    fireEvent.click(warButton);

    // 史料依据面板切换到 ev_war1：其证据描述（独立文本节点）应出现，
    // 且当前事件标题也随之更新（事件标题 span 在证据区内唯一）。
    expect(
      await screen.findByText("战争参与块记录为 attacker"),
    ).toBeInTheDocument();
    const evidenceSection = screen
      .getByRole("heading", { name: "史料依据" })
      .closest("section") as HTMLElement;
    expect(
      within(evidenceSection).getByText("发动继承战争"),
    ).toBeInTheDocument();
  });

  it("4) IntersectionObserver 进入视口时更新当前章节与事件", async () => {
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const observer = await waitFor(() => getBioObserver());
    // 初始：首章（出身与家世）激活
    expect(
      document.getElementById("chapter-ch_origin")!.className,
    ).toContain("ring-cinnabar-700/40");

    act(() => {
      observer.cb(
        [
          {
            target: document.getElementById("chapter-ch_war") as Element,
            isIntersecting: true,
            intersectionRatio: 1,
          } as IntersectionObserverEntry,
        ],
        observer as unknown as IntersectionObserver,
      );
    });

    await waitFor(() =>
      expect(
        document.getElementById("chapter-ch_war")!.className,
      ).toContain("ring-cinnabar-700/40"),
    );
    expect(
      document.getElementById("chapter-ch_origin")!.className,
    ).not.toContain("ring-cinnabar-700/40");

    // 当前事件也更新为战争章首事件（ev_war1）
    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const warEventNode = within(timelineSection)
      .getByText("发动继承战争")
      .closest("button") as HTMLButtonElement;
    expect(warEventNode).toHaveAttribute("aria-current", "true");
  });

  it("5) 点击触发滚动锁期间，IntersectionObserver 的更新被忽略", async () => {
    // 桌面 + 不减弱动效：点击会设置滚动锁
    stubMatchMedia((q) => q.includes("min-width: 1024px"));
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const observer = await waitFor(() => getBioObserver());
    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const warButton = within(timelineSection)
      .getByText("发动继承战争")
      .closest("button") as HTMLButtonElement;
    fireEvent.click(warButton);

    // 点击后战争章激活（点击本身生效）
    await waitFor(() =>
      expect(
        document.getElementById("chapter-ch_war")!.className,
      ).toContain("ring-cinnabar-700/40"),
    );
    expect(
      document.getElementById("chapter-ch_origin")!.className,
    ).not.toContain("ring-cinnabar-700/40");

    // 锁定期内触发 Observer 指向出身章 → 应被忽略，出身章不激活
    act(() => {
      observer.cb(
        [
          {
            target: document.getElementById("chapter-ch_origin") as Element,
            isIntersecting: true,
            intersectionRatio: 1,
          } as IntersectionObserverEntry,
        ],
        observer as unknown as IntersectionObserver,
      );
    });
    expect(
      document.getElementById("chapter-ch_origin")!.className,
    ).not.toContain("ring-cinnabar-700/40");
    expect(
      document.getElementById("chapter-ch_war")!.className,
    ).toContain("ring-cinnabar-700/40");
  });

  it("6) 减弱动效时不调用 smooth scroll", async () => {
    stubMatchMedia((q) => q.includes("prefers-reduced-motion"));
    const spy = vi.spyOn(Element.prototype, "scrollIntoView");
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const warButton = within(timelineSection)
      .getByText("发动继承战争")
      .closest("button") as HTMLButtonElement;
    fireEvent.click(warButton);
    expect(spy).not.toHaveBeenCalled();
  });

  it("6b) 桌面且未减弱动效时点击会调用 smooth scroll", async () => {
    stubMatchMedia((q) => q.includes("min-width: 1024px"));
    const spy = vi.spyOn(Element.prototype, "scrollIntoView");
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const warButton = within(timelineSection)
      .getByText("发动继承战争")
      .closest("button") as HTMLButtonElement;
    fireEvent.click(warButton);
    expect(spy).toHaveBeenCalled();
  });

  it("7) 移动端（非桌面）点击不自动滚动", async () => {
    stubMatchMedia(() => false); // 非桌面（默认）
    const spy = vi.spyOn(Element.prototype, "scrollIntoView");
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const warButton = within(timelineSection)
      .getByText("发动继承战争")
      .closest("button") as HTMLButtonElement;
    fireEvent.click(warButton);
    expect(spy).not.toHaveBeenCalled();
  });

  it("8) A→B→A 快速切换：A 不永久 loading，且仅取档两次（第二次 A 复用 in-flight）", async () => {
    const repo = installControllableRepo();
    await renderAt("/characters/arnulf_001"); // 发起 A 取档（调用 0）

    await act(async () => {
      setPath("/characters/lowborn_002"); // B 取档（调用 1）
    });
    await act(async () => {
      setPath("/characters/arnulf_001"); // 回到 A：复用 in-flight，不再取档
    });
    // 第二次 A 命中进行中的请求，未产生新的仓库访问
    expect(repo.spy).toHaveBeenCalledTimes(2);

    // B 先成功，A 晚返回
    await act(async () => {
      repo.resolveNth(1, fakeProfile("lowborn_002"));
    });
    await act(async () => {
      repo.resolveNth(0, fakeProfile("arnulf_001"));
    });
    await flush();

    // 最终路由为 A，展示 A 档案，且无永久 loading
    expect(await screen.findByText("arnulf_001")).toBeInTheDocument();
    expect(screen.queryByText(/正在载入/)).not.toBeInTheDocument();

    const st = useStore.getState();
    expect(st.profileRequestStateById[profileCacheKey("mock", MOCK_SAVE_ID, "arnulf_001")].status).toBe("success");
    expect(st.profileRequestStateById[profileCacheKey("mock", MOCK_SAVE_ID, "lowborn_002")].status).toBe("success");
  });

  it("9) 密度切换按钮正确反映 aria-pressed", async () => {
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const allBtn = screen.getByRole("button", { name: "全部事件" });
    const keyBtn = screen.getByRole("button", { name: "关键事件" });
    expect(allBtn).toHaveAttribute("aria-pressed", "true");
    expect(keyBtn).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(keyBtn);
    expect(keyBtn).toHaveAttribute("aria-pressed", "true");
    expect(allBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("10) 默认当前时间线节点带 aria-current", async () => {
    await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫");

    const timelineSection = screen
      .getByRole("heading", { name: "时间线" })
      .closest("section") as HTMLElement;
    const birthButton = within(timelineSection)
      .getByText("诞生于韦尔特")
      .closest("button") as HTMLButtonElement;
    expect(birthButton).toHaveAttribute("aria-current", "true");
  });

  it("11) 卸载时断开 IntersectionObserver", async () => {
    const { unmount } = await renderAt("/characters/arnulf_001");
    await screen.findByText("阿努尔夫"); // 档案就绪后 observer 创建

    const observer = await waitFor(() => getBioObserver());
    expect(observer.disconnected).toBe(false);

    unmount();
    expect(observer.disconnected).toBe(true);
  });
});
