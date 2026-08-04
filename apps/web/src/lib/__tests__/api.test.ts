import { describe, it, expect, afterEach, vi } from "vitest";
import { api } from "../api";

/**
 * 回归：HTTP 方法与后端路由一致（后端：rescan/import/parse/watch=POST、
 * delete=DELETE、其余读取=GET）。此前 parse/rescan/delete 误用 GET 导致
 * 405 Method Not Allowed，而测试只 mock 了 URL 未断言方法，未被发现。
 */
function jsonResponse(body: unknown): any {
  return { ok: true, status: 200, json: async () => body };
}

function installFetchRecorder() {
  const calls: { url: string; method: string }[] = [];
  globalThis.fetch = vi.fn(async (input: unknown, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method ?? "GET" });
    return jsonResponse({});
  }) as any;
  return calls;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("api HTTP 方法（回归 405）", () => {
  it("parseSave 使用 POST", async () => {
    const calls = installFetchRecorder();
    await api.parseSave("save_1");
    expect(calls[0].url).toContain("/api/local-saves/save_1/parse");
    expect(calls[0].method).toBe("POST");
  });

  it("rescanLocalSaves 使用 POST", async () => {
    const calls = installFetchRecorder();
    await api.rescanLocalSaves();
    expect(calls[0].url).toContain("/api/local-saves/rescan");
    expect(calls[0].method).toBe("POST");
  });

  it("deleteSave 使用 DELETE", async () => {
    const calls = installFetchRecorder();
    await api.deleteSave("save_1");
    expect(calls[0].url).toContain("/api/saves/save_1");
    expect(calls[0].method).toBe("DELETE");
  });

  it("读取类端点保持 GET（inspect/mods/characters/profile/timeline）", async () => {
    const calls = installFetchRecorder();
    await api.inspectSave("save_1");
    await api.modsForSave("save_1");
    await api.listCharacters("save_1", { limit: 5, offset: 0 });
    await api.getProfile("save_1", "c_1");
    await api.getTimeline("save_1", "c_1");
    expect(calls.map((c) => c.method)).toEqual(["GET", "GET", "GET", "GET", "GET"]);
    expect(calls[4].url).toContain(
      "/api/local-saves/save_1/characters/c_1/timeline",
    );
  });

  it("非 2xx 响应抛出可读错误（不吞 405）", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 405,
      text: async () => '{"detail":"Method Not Allowed"}',
    })) as any;
    await expect(api.parseSave("save_1")).rejects.toThrow(/405/);
  });
});
