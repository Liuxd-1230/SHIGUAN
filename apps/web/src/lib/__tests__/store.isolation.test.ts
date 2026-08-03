import { describe, it, expect, vi, afterEach } from "vitest";
import { useStore, resetProfileInflight, profileCacheKey } from "../../store";
import { mockCharacterRepository } from "../characterRepository";
import { realCharacterRepository } from "../realRepository";
import { resetStore } from "../../test/helpers";
import type { CharacterProfile } from "@shiguan/save-schema";

afterEach(() => {
  vi.restoreAllMocks();
  resetProfileInflight();
  resetStore();
});

function fakeProfile(id: string, markers: string[]): CharacterProfile {
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
    // 注入标记以便断言"真实档用真实档、互不串档"。
    ...(markers.length ? { notes: markers } : {}),
  } as unknown as CharacterProfile;
}

/**
 * 两个真实存档（saveId 不同）含有相同 characterId=6432：
 *  - 各自独立载入，缓存键为 real::<saveId>::6432，绝不串档；
 *  - 真实档只走 realCharacterRepository，绝不误用 mockCharacterRepository 的档案。
 */
describe("store 多真实存档隔离（同 characterId 不串档、不误用 Mock）", () => {
  it("两个真实存档同 characterId 各自独立，且不调用 Mock 仓库", async () => {
    const mockSpy = vi.spyOn(mockCharacterRepository, "loadProfile");
    const realSpy = vi
      .spyOn(realCharacterRepository, "loadProfile")
      .mockImplementation(async (id: string, saveId?: string) => {
        // 不同 saveId 返回不同档案，用于验证隔离。
        if (saveId === "SAVE_A")
          return fakeProfile(id, ["from-A"]);
        if (saveId === "SAVE_B")
          return fakeProfile(id, ["from-B"]);
        return fakeProfile(id, []);
      });

    const s = useStore.getState();
    await s.loadProfile("real", "SAVE_A", "6432");
    await s.loadProfile("real", "SAVE_B", "6432");

    const st = useStore.getState();
    const keyA = profileCacheKey("real", "SAVE_A", "6432");
    const keyB = profileCacheKey("real", "SAVE_B", "6432");

    // 两条独立缓存键都存在且互不相同。
    expect(st.profileCache[keyA]).toBeDefined();
    expect(st.profileCache[keyB]).toBeDefined();
    expect(Object.keys(st.profileCache).length).toBe(2);

    // 不串档：A 的档案来自 A，B 的档案来自 B。
    expect((st.profileCache[keyA] as any).notes).toEqual(["from-A"]);
    expect((st.profileCache[keyB] as any).notes).toEqual(["from-B"]);
    expect(st.profileCache[keyA]).not.toBe(st.profileCache[keyB]);

    // 请求状态各自成功。
    expect(st.profileRequestStateById[keyA].status).toBe("success");
    expect(st.profileRequestStateById[keyB].status).toBe("success");

    // 真实档绝不调用 Mock 仓库。
    expect(mockSpy).not.toHaveBeenCalled();
    expect(realSpy).toHaveBeenCalledTimes(2);
    expect(realSpy).toHaveBeenCalledWith("6432", "SAVE_A");
    expect(realSpy).toHaveBeenCalledWith("6432", "SAVE_B");
  });

  it("真实档与 Mock 档即便 characterId 相同也隔离在各自缓存键下", async () => {
    // Mock 与真实各自用不同数据源维度；同 id 不互相覆盖。
    vi.spyOn(mockCharacterRepository, "loadProfile").mockResolvedValue(
      fakeProfile("arnulf_001", ["from-mock"]),
    );
    vi.spyOn(realCharacterRepository, "loadProfile").mockResolvedValue(
      fakeProfile("arnulf_001", ["from-real"]),
    );

    const s = useStore.getState();
    await s.loadProfile("mock", "__mock__", "arnulf_001");
    await s.loadProfile("real", "SAVE_A", "arnulf_001");

    const st = useStore.getState();
    const mockKey = profileCacheKey("mock", "__mock__", "arnulf_001");
    const realKey = profileCacheKey("real", "SAVE_A", "arnulf_001");

    expect((st.profileCache[mockKey] as any).notes).toEqual(["from-mock"]);
    expect((st.profileCache[realKey] as any).notes).toEqual(["from-real"]);
    // Mock 加载不污染真实键，反之亦然。
    expect(st.profileCache[realKey]).not.toBe(st.profileCache[mockKey]);
  });
});
