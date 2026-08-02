import { describe, it, expect } from "vitest";
import { mockCharacterRepository } from "../characterRepository";
import { useStore } from "../../store";
import { resetStore } from "../../test/helpers";

describe("CharacterRepository（真正的按需加载）", () => {
  it("索引加载成功，且不内联任何完整档案", async () => {
    resetStore();
    const res = await mockCharacterRepository.loadIndex();
    expect(res.characterIndex.length).toBe(3);
    expect(res.meta.gameVersion).toBeTruthy();
    // 载入索引不应把完整档案塞进缓存
    expect(Object.keys(useStore.getState().profileCache).length).toBe(0);
  });

  it("完整档案只在点击后加载（store.loadProfile 才进缓存）", async () => {
    resetStore();
    await mockCharacterRepository.loadIndex();
    expect(Object.keys(useStore.getState().profileCache).length).toBe(0);

    await useStore.getState().loadProfile("arnulf_001");
    expect(useStore.getState().profileCache["arnulf_001"]).toBeDefined();
    expect(useStore.getState().profileCache["arnulf_001"]?.id).toBe("arnulf_001");
  });

  it("已加载档案进入缓存并保持成功状态", async () => {
    resetStore();
    await useStore.getState().loadProfile("arnulf_001");
    expect(useStore.getState().profileRequestStateById["arnulf_001"].status).toBe("success");
    expect(useStore.getState().profileCache["arnulf_001"]?.name).toBe("阿努尔夫");

    await useStore.getState().loadProfile("arnulf_001");
    expect(useStore.getState().profileRequestStateById["arnulf_001"].status).toBe("success");
  });

  it("未知人物 ID 进入可读错误状态", async () => {
    resetStore();
    await useStore.getState().loadProfile("ghost_999");
    expect(useStore.getState().profileRequestStateById["ghost_999"].status).toBe("error");
    expect(useStore.getState().profileRequestStateById["ghost_999"].error).toContain("ghost_999");
  });

  it("损坏的档案进入可读错误状态（不白屏）", async () => {
    resetStore();
    await useStore.getState().loadProfile("incomplete_003");
    expect(useStore.getState().profileRequestStateById["incomplete_003"].status).toBe("error");
    expect(useStore.getState().profileRequestStateById["incomplete_003"].error).toBeTruthy();
  });
});
