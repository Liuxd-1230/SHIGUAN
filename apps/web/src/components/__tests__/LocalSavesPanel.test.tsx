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
});
