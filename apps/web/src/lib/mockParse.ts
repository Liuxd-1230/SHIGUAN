/**
 * MockParseService —— 模拟存档解析的任务状态机（Phase 1B）。
 *
 * 重要说明（修复 Phase 1A 的虚假表述）：
 *  - 这里**不是**用 setTimeout + Math.random 伪造的"假进度条"。
 *  - 它是一个明确的任务状态模型：每个阶段在真正"开始 → 完成"之间发出事件，
 *    由 Mock 顺序驱动；阶段耗时固定（默认 600ms），不随机。
 *  - UI 必须明确标注"当前为 Mock 演示流程，尚未解析真实 CK3 存档"。
 *  - 支持 AbortSignal：组件卸载时可靠取消；支持 failAt 注入失败（演示/测试重试）。
 */
import type { ParseStageState, ParseStageStatus } from "../store";

export interface ParseStageDef {
  id: string;
  label: string;
}

export const PARSE_STAGES: ParseStageDef[] = [
  { id: "detect", label: "检测文件类型与编码" },
  { id: "unzip", label: "解压存档容器" },
  { id: "convert", label: "转换为标准明文" },
  { id: "read", label: "读取人物数据" },
  { id: "index", label: "建立人物索引" },
  { id: "localize", label: "加载本地化名称" },
];

export function initialParseStages(): ParseStageState[] {
  return PARSE_STAGES.map((s) => ({ id: s.id, label: s.label, status: "pending" }));
}

export interface MockParseOptions {
  /** 演示/测试：在此阶段完成后注入失败。 */
  failAt?: string;
  /** 每阶段固定耗时（毫秒）。不使用随机数。 */
  stageDelayMs?: number;
  /** 取消信号；触发后任务抛 AbortError 并停止。 */
  signal?: AbortSignal;
}

export interface MockParseHandlers {
  onStage: (
    id: string,
    status: ParseStageStatus,
    extra?: Partial<ParseStageState>,
  ) => void;
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const t = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      window.clearTimeout(t);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export class MockParseService {
  /**
   * 顺序执行各解析阶段。成功时 resolve；被取消时 reject(AbortError)；
   * 在 failAt 阶段注入失败时 reject(Error)。阶段状态通过 onStage 回调上抛。
   */
  async run(
    opts: MockParseOptions,
    handlers: MockParseHandlers,
  ): Promise<void> {
    const { failAt, stageDelayMs = 600, signal } = opts;

    for (const stage of PARSE_STAGES) {
      if (signal?.aborted) {
        throw new DOMException("aborted", "AbortError");
      }
      handlers.onStage(stage.id, "running");

      await delay(stageDelayMs, signal);
      if (signal?.aborted) {
        throw new DOMException("aborted", "AbortError");
      }

      if (failAt === stage.id) {
        handlers.onStage(stage.id, "error", {
          error: `阶段「${stage.label}」模拟失败：缺少所需组件或数据，无法继续。`,
        });
        // 后续阶段标记为 skipped
        const idx = PARSE_STAGES.findIndex((s) => s.id === stage.id);
        for (let j = idx + 1; j < PARSE_STAGES.length; j++) {
          handlers.onStage(PARSE_STAGES[j].id, "skipped");
        }
        throw new Error(`解析在阶段「${stage.label}」失败`);
      }

      handlers.onStage(stage.id, "success");
    }
  }
}

/** 默认 Mock 解析服务单例。 */
export const mockParseService = new MockParseService();
