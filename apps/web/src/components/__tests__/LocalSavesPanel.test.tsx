import { describe, it, expect, afterEach, vi, beforeEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import LocalSavesPanel from "../LocalSavesPanel";
import { resetBackendAvailableCache } from "../../lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const SAMPLE = [
  {
    saveId: "abc123",
    fileName: "autosave.ck3",
    displayName: "autosave.ck3",
    sizeBytes: 65000000,
    modifiedAt: "2026-08-02T12:00:00Z",
    isAutosave: true,
    status: "available",
    gameVersion: null,
    date: null,
    modCount: null,
    lastParseStatus: "untouched",
  },
];

function jsonResponse(body: unknown): any {
  return { ok: true, status: 200, json: async () => body };
}

function mockAvailableFetch() {
  globalThis.fetch = vi.fn(async (input: unknown) => {
    const u = String(input);
    if (u.includes("/api/health")) return jsonResponse({});
    if (u.includes("/api/local-saves") && u.includes("rescan"))
      return jsonResponse({ available: true, saves: SAMPLE });
    if (u.endsWith("/api/local-saves")) return jsonResponse({ available: true, saves: SAMPLE });
    if (u.includes("/api/settings/paths"))
      return jsonResponse({ saves_dir: "C:/savegames", staging_dir: "/x" });
    if (u.includes("/api/local-saves/watch")) return jsonResponse({ running: true });
    if (u.includes("/api/local-saves/import")) return jsonResponse({ saveId: "x" });
    return jsonResponse({});
  }) as any;
}

describe("LocalSavesPanel（Phase 2A 本地存档浏览器）", () => {
  beforeEach(() => resetBackendAvailableCache());

  it("后端可用时列出本机存档", async () => {
    mockAvailableFetch();
    render(<LocalSavesPanel />);
    await waitFor(() => expect(screen.getByText("本机存档")).toBeInTheDocument());
    expect(screen.getByText("autosave.ck3")).toBeInTheDocument();
    // 展示存档目录
    expect(screen.getByText(/C:\/savegames/)).toBeInTheDocument();
  });

  it("后端不可用时整块不渲染（继续 Mock 演示，不崩溃）", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("backend down");
    }) as any;
    const { container } = render(<LocalSavesPanel />);
    await waitFor(() =>
      expect(screen.queryByText("本机存档")).not.toBeInTheDocument(),
    );
    expect(container.textContent).toBe("");
  });

  it("增量监听：首轮对齐游标后轮询带 sinceEventId，且历史事件不重复处理", async () => {
    const requested: string[] = [];
    globalThis.fetch = vi.fn(async (input: unknown) => {
      const u = String(input);
      requested.push(u);
      if (u.includes("/api/health")) return jsonResponse({});
      if (u.endsWith("/api/local-saves"))
        return jsonResponse({ available: true, saves: SAMPLE });
      if (u.includes("/api/settings/paths"))
        return jsonResponse({ saves_dir: "C:/savegames", staging_dir: "/x" });
      // 带游标的轮询：无新事件 → 不应触发刷新。
      if (
        u.includes("/api/local-saves/watch/status") &&
        u.includes("sinceEventId")
      )
        return jsonResponse({
          running: true,
          lastEventId: "evt-1",
          recent_events: [],
        });
      // 首轮对齐状态：给一个游标，但 no recent_events（不刷新）。
      if (u.includes("/api/local-saves/watch/status"))
        return jsonResponse({ running: true, lastEventId: "evt-1" });
      if (u.includes("/api/local-saves/watch")) return jsonResponse({ running: true });
      return jsonResponse({});
    }) as any;

    render(<LocalSavesPanel />);
    await waitFor(() => expect(screen.getByText("本机存档")).toBeInTheDocument());
    // 等待首轮轮询（3s 间隔）发出带游标的请求。
    await waitFor(
      () =>
        expect(
          requested.some((u) => u.includes("sinceEventId=evt-1")),
        ).toBe(true),
      { timeout: 6000 },
    );
    expect(requested.some((u) => u.includes("/api/local-saves/watch/start"))).toBe(
      true,
    );
    // 对齐 + 无新事件轮询均不应触发刷新（仅挂载时的初始 refresh 一次）。
    const refetchCount = requested.filter(
      (u) => u.endsWith("/api/local-saves") && u.includes("rescan") === false,
    ).length;
    expect(refetchCount).toBe(1);
  });

  it("增量监听：轮询返回新事件时触发一次刷新", async () => {
    const requested: string[] = [];
    globalThis.fetch = vi.fn(async (input: unknown) => {
      const u = String(input);
      requested.push(u);
      if (u.includes("/api/health")) return jsonResponse({});
      if (u.endsWith("/api/local-saves"))
        return jsonResponse({ available: true, saves: SAMPLE });
      if (u.includes("/api/settings/paths"))
        return jsonResponse({ saves_dir: "C:/savegames", staging_dir: "/x" });
      // 首轮对齐状态。
      if (
        u.includes("/api/local-saves/watch/status") &&
        !u.includes("sinceEventId")
      )
        return jsonResponse({ running: true, lastEventId: "evt-1" });
      // 带游标的轮询：返回新事件 → 应触发刷新。
      if (u.includes("/api/local-saves/watch/status"))
        return jsonResponse({
          running: true,
          lastEventId: "evt-2",
          recent_events: [{ eventId: "evt-2" }],
        });
      if (u.includes("/api/local-saves/watch")) return jsonResponse({ running: true });
      return jsonResponse({});
    }) as any;

    render(<LocalSavesPanel />);
    await waitFor(() => expect(screen.getByText("本机存档")).toBeInTheDocument());
    // 等待首轮轮询返回新事件并触发刷新。
    await waitFor(
      () => {
        const refetchCount = requested.filter(
          (u) => u.endsWith("/api/local-saves") && u.includes("rescan") === false,
        ).length;
        expect(refetchCount).toBe(2); // 初始 refresh + 增量事件触发一次
      },
      { timeout: 6000 },
    );
    expect(requested.some((u) => u.includes("sinceEventId=evt-1"))).toBe(true);
  });

  it("页面卸载不再关闭全局监听（不调用 watch/stop）", async () => {
    const requested: string[] = [];
    globalThis.fetch = vi.fn(async (input: unknown) => {
      const u = String(input);
      requested.push(u);
      if (u.includes("/api/health")) return jsonResponse({});
      if (u.endsWith("/api/local-saves"))
        return jsonResponse({ available: true, saves: SAMPLE });
      if (u.includes("/api/settings/paths"))
        return jsonResponse({ saves_dir: "C:/savegames", staging_dir: "/x" });
      if (u.includes("/api/local-saves/watch/status"))
        return jsonResponse({ running: true, lastEventId: "evt-1" });
      if (u.includes("/api/local-saves/watch")) return jsonResponse({ running: true });
      return jsonResponse({});
    }) as any;

    const { unmount } = render(<LocalSavesPanel />);
    await waitFor(() => expect(screen.getByText("本机存档")).toBeInTheDocument());
    unmount();
    // 卸载后绝不发送 watch/stop（全局监听由应用退出统一回收）。
    expect(requested.some((u) => u.includes("/api/local-saves/watch/stop"))).toBe(
      false,
    );
  });
});
