import { describe, it, expect, vi, afterEach } from "vitest";
import { mockCharacterRepository } from "../characterRepository";
import { useStore, resetProfileInflight } from "../../store";
import { resetStore } from "../../test/helpers";
import type { CharacterProfile } from "@shiguan/save-schema";

afterEach(() => {
  vi.restoreAllMocks();
  resetProfileInflight();
  resetStore();
});

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

/**
 * 安装一个可控仓库：每次 loadProfile 调用都返回一个独立的、可单独 resolve/reject 的
 * Promise（按调用顺序记录），便于精确编排"谁先返回 / 谁晚返回"。
 */
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
    lastCall: () => calls[calls.length - 1],
  };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("store.loadProfile 竞态修复（按人物 id 管理请求）", () => {
  it("1) A → B → A，A 首次请求晚返回：两者都成功，A 不永久停留在 loading", async () => {
    const repo = installControllableRepo();
    const s = useStore.getState();
    s.loadProfile("A"); // 调用 0（inflight A）
    s.loadProfile("B"); // 调用 1（inflight B）
    s.loadProfile("A"); // 调用 2：命中 in-flight，复用同一 Promise（不会访问仓库）

    // B 先成功，A 晚返回
    repo.resolveNth(1, fakeProfile("B"));
    repo.resolveNth(0, fakeProfile("A"));
    await flush();

    const st = useStore.getState();
    expect(st.profileRequestStateById["A"].status).toBe("success");
    expect(st.profileCache["A"]?.id).toBe("A");
    expect(st.profileRequestStateById["B"].status).toBe("success");
    expect(st.profileCache["B"]?.id).toBe("B");
    // 第二次 A 调用不应再访问仓库
    expect(repo.spy).toHaveBeenCalledTimes(2);
  });

  it("2) A 与 B 同时成功，两者都进入缓存（互不干扰）", async () => {
    const repo = installControllableRepo();
    const s = useStore.getState();
    s.loadProfile("A");
    s.loadProfile("B");

    repo.resolveNth(0, fakeProfile("A"));
    repo.resolveNth(1, fakeProfile("B"));
    await flush();

    const st = useStore.getState();
    expect(st.profileRequestStateById["A"].status).toBe("success");
    expect(st.profileRequestStateById["B"].status).toBe("success");
    expect(st.profileCache["A"]).toBeDefined();
    expect(st.profileCache["B"]).toBeDefined();
  });

  it("3) 同一人物两个并发调用只访问一次仓库（请求合并）", async () => {
    const repo = installControllableRepo();
    const s = useStore.getState();
    const p1 = s.loadProfile("A");
    const p2 = s.loadProfile("A"); // 并发：命中 in-flight，合并

    expect(repo.spy).toHaveBeenCalledTimes(1);

    repo.resolveNth(0, fakeProfile("A"));
    await Promise.all([p1, p2]);
    await flush();

    const st = useStore.getState();
    expect(st.profileRequestStateById["A"].status).toBe("success");
    expect(repo.spy).toHaveBeenCalledTimes(1);
  });

  it("4) 同一人物旧请求晚于重试返回，不覆盖新结果", async () => {
    const repo = installControllableRepo();
    const s = useStore.getState();
    s.loadProfile("A"); // 调用 0：旧请求（requestId=1）
    useStore.getState().clearProfileRequest("A"); // 作废旧请求，允许重试
    s.loadProfile("A"); // 调用 1：重试（requestId=2）

    // 重试（新）先成功 → 采纳
    repo.resolveNth(1, fakeProfile("A"));
    await flush();
    expect(useStore.getState().profileRequestStateById["A"].status).toBe("success");

    // 旧请求晚返回 → 被丢弃，不覆盖
    repo.resolveNth(0, fakeProfile("A-OLD"));
    await flush();
    const st = useStore.getState();
    expect(st.profileRequestStateById["A"].status).toBe("success");
    expect(st.profileCache["A"]?.id).toBe("A"); // 仍是新结果，非 A-OLD
  });

  it("5) 一个人物失败不影响另一个人物", async () => {
    const repo = installControllableRepo();
    const s = useStore.getState();
    s.loadProfile("A");
    s.loadProfile("B");

    repo.rejectNth(0, new Error("no A"));
    repo.resolveNth(1, fakeProfile("B"));
    await flush();

    const st = useStore.getState();
    expect(st.profileRequestStateById["A"].status).toBe("error");
    expect(st.profileRequestStateById["A"].error).toContain("no A");
    expect(st.profileRequestStateById["B"].status).toBe("success");
  });

  it("6) 任意时刻都不存在永久 loading 状态", async () => {
    const repo = installControllableRepo();
    const s = useStore.getState();
    s.loadProfile("A");
    s.loadProfile("B");
    s.loadProfile("A"); // 合并

    repo.resolveNth(1, fakeProfile("B"));
    repo.resolveNth(0, fakeProfile("A"));
    await flush();

    const st = useStore.getState();
    const anyLoading = Object.values(st.profileRequestStateById).some(
      (r) => r.status === "loading",
    );
    expect(anyLoading).toBe(false);
  });

  it("缓存命中不得重新访问仓库", async () => {
    const repo = installControllableRepo();
    useStore.getState().loadProfile("A"); // 调用 0
    repo.resolveNth(0, fakeProfile("A"));
    await flush();
    expect(repo.spy).toHaveBeenCalledTimes(1);
    expect(useStore.getState().profileRequestStateById["A"].status).toBe("success");

    // 再次请求同一人物：已是 success + 缓存命中，不应再访问仓库
    await useStore.getState().loadProfile("A");
    expect(repo.spy).toHaveBeenCalledTimes(1);
  });

  it("clearProfileRequest 重置指定人物的请求状态为空闲", async () => {
    const repo = installControllableRepo();
    useStore.getState().loadProfile("Z"); // 调用 0
    repo.rejectNth(0, new Error("boom"));
    await flush();
    expect(useStore.getState().profileRequestStateById["Z"].status).toBe("error");

    useStore.getState().clearProfileRequest("Z");
    expect(useStore.getState().profileRequestStateById["Z"].status).toBe("idle");
    expect(useStore.getState().profileRequestStateById["Z"].requestId).toBe(0);
  });
});
