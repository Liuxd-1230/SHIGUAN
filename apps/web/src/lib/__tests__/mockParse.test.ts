import { describe, it, expect } from "vitest";
import { mockParseService, initialParseStages } from "../mockParse";
import type { ParseStageStatus } from "../../store";

/**
 * MockParseService 必须是确定性的任务状态机：
 *  - 阶段严格按 pending → running → success 推进（无 Math.random 假进度）
 *  - failAt 注入失败时该阶段 error、后续 skipped、整体 reject
 *  - AbortSignal 触发后以 AbortError 终止（组件卸载可可靠取消）
 *  - 失败后移除 failAt 重试可成功（对应 UI 重试按钮）
 */
describe("MockParseService（确定性任务状态机，无随机数）", () => {
  it("按 pending → running → success 顺序推进每个阶段", async () => {
    const seen: Record<string, ParseStageStatus[]> = {};
    await mockParseService.run(
      { stageDelayMs: 1 },
      {
        onStage: (id, status) => {
          (seen[id] ??= []).push(status);
        },
      },
    );
    for (const s of initialParseStages()) {
      expect(seen[s.id][0]).toBe("running");
      expect(seen[s.id][seen[s.id].length - 1]).toBe("success");
      expect(seen[s.id]).not.toContain("error");
      expect(seen[s.id]).not.toContain("skipped");
    }
  });

  it("failAt 注入失败时该阶段 error、后续阶段 skipped、整体 reject", async () => {
    const last: Record<string, ParseStageStatus> = {};
    let rejected = false;
    await mockParseService
      .run(
        { stageDelayMs: 1, failAt: "read" },
        { onStage: (id, status) => (last[id] = status) },
      )
      .then(
        () => {},
        () => {
          rejected = true;
        },
      );
    expect(rejected).toBe(true);
    expect(last["detect"]).toBe("success");
    expect(last["unzip"]).toBe("success");
    expect(last["convert"]).toBe("success");
    expect(last["read"]).toBe("error");
    expect(last["index"]).toBe("skipped");
    expect(last["localize"]).toBe("skipped");
  });

  it("AbortSignal 触发后任务以 AbortError 终止", async () => {
    const ac = new AbortController();
    let rejected: unknown = null;
    await mockParseService
      .run(
        { stageDelayMs: 30, signal: ac.signal },
        {
          onStage: (id, status) => {
            if (id === "convert" && status === "running") ac.abort();
          },
        },
      )
      .then(
        () => {},
        (e) => {
          rejected = e;
        },
      );
    expect(rejected).toBeInstanceOf(DOMException);
    expect((rejected as DOMException).name).toBe("AbortError");
  });

  it("失败后移除 failAt 重试可成功完成（对应 UI 重试按钮）", async () => {
    await mockParseService
      .run(
        { stageDelayMs: 1, failAt: "read" },
        { onStage: () => {} },
      )
      .then(
        () => {},
        () => {},
      );
    let ok = false;
    await mockParseService
      .run({ stageDelayMs: 1 }, { onStage: () => {} })
      .then(() => {
        ok = true;
      });
    expect(ok).toBe(true);
  });
});
