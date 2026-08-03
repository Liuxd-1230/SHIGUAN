/**
 * 全局状态（Zustand）。Phase 1B 重构：
 *  - 把"人物摘要索引"与"完整档案缓存"分离：索引在解析后一次性载入，
 *    完整档案按需懒加载进 profileCache（不进初始化 bundle）。
 *  - 解析状态独立（parseStages / parseError），支持失败 / 重试 / 取消。
 *  - 筛选（query / rulerOnly）独立于路由，返回选择页时保留。
 *
 * Phase 1C（竞态修复）：
 *  - 人物档案载入状态改为"按人物区分"的 profileRequestStateById，
 *    不再使用单一全局 profileLoadStatus。这样在 A/B 两个人物之间快速切换时，
 *    后到/更早的响应不会互相污染（以请求序号 requestId 判定新鲜度）。
 *
 * Phase 2A.1（多存档隔离）：
 *  - 人物缓存 / 请求状态 / in-flight 的键统一为 `dataSource::saveId::characterId`。
 *    这样两个真实存档即便含有相同 characterId，也各自独立、绝不串档；
 *    且真实存档不会误用 Mock 档案（数据源维度隔离）。
 */
import { create } from "zustand";
import type {
  CharacterProfile,
  CharacterSummary,
  ParsedSaveMeta,
} from "@shiguan/save-schema";
import { mockCharacterRepository } from "./lib/characterRepository";
import { realCharacterRepository } from "./lib/realRepository";
import { initialParseStages } from "./lib/mockParse";

export type ParseStageStatus =
  | "pending"
  | "running"
  | "success"
  | "error"
  | "skipped";

export interface ParseStageState {
  id: string;
  label: string;
  status: ParseStageStatus;
  message?: string;
  error?: string;
}

export type ProfileLoadStatus = "idle" | "loading" | "success" | "error";

/** 档案数据源：mock（演示数据）或 real（后端真实存档）。 */
export type DataSource = "mock" | "real";

/** Mock 模式没有真实 saveId，用此哨兵占位（保证复合键唯一且可读）。 */
export const MOCK_SAVE_ID = "__mock__";

/** 复合缓存键：dataSource::saveId::characterId，多存档隔离的核心。 */
export function profileCacheKey(
  dataSource: DataSource,
  saveId: string,
  characterId: string,
): string {
  return `${dataSource}::${saveId}::${characterId}`;
}

/** 单个人物的档案请求状态（按复合键区分，避免切换/跨存档互相污染）。 */
export interface ProfileRequestState {
  status: ProfileLoadStatus;
  error?: string;
  /** 本次请求序号；仅当仍为最新序号时，响应才会被采纳。 */
  requestId?: number;
}

export const IDLE_REQUEST: ProfileRequestState = { status: "idle", requestId: 0 };

/**
 * 模块级（在 store 状态之外）：按复合键的 in-flight Promise 与每键请求序号。
 * 放在状态之外，原因有二：
 *  1) 便于跨调用判定"某次响应是否还是该人物的最新请求"（真正的按复合键竞态判定）；
 *  2) 支持同人物并发请求合并为同一个 Promise，避免重复访问仓库。
 */
interface InflightEntry {
  promise: Promise<void>;
  requestId: number;
}
const profileInflightById = new Map<string, InflightEntry>();
let profileReqSeqById: Record<string, number> = {};

/** 测试用：清空 in-flight 与每人物序号，避免测试间串扰。 */
export function resetProfileInflight(): void {
  profileInflightById.clear();
  profileReqSeqById = {};
}

interface AppState {
  // —— 索引 / 档案分离 ——
  saveMeta: ParsedSaveMeta | null;
  characterIndex: CharacterSummary[];
  /** 已成功载入的完整档案，按 id 缓存（真正的按需加载）。 */
  profileCache: Record<string, CharacterProfile>;
  indexLoaded: boolean;

  // —— 当前人物 ——
  selectedCharacterId: string | null;
  /** 按人物 id 区分的档案请求状态（替代旧的全局 profileLoadStatus）。 */
  profileRequestStateById: Record<string, ProfileRequestState>;

  // —— 真实后端模式（Phase 2A）——
  // backendMode=true 时，loadProfile / ensureIndex 走 RealCharacterRepository；
  // 后端不可用时保持 false，沿用 Mock 演示流程（行为与之前完全一致）。
  backendMode: boolean;

  // —— 选择页筛选（独立于路由，返回时保留）——
  query: string;
  rulerOnly: boolean;

  // —— 解析阶段状态 ——
  parseStages: ParseStageState[];
  parseError: string | null;

  // —— actions ——
  setIndex: (meta: ParsedSaveMeta, index: CharacterSummary[]) => void;
  /** 按复合键载入档案：dataSource(数据源) + saveId(存档) + id(人物)，多存档隔离。 */
  loadProfile: (dataSource: DataSource, saveId: string, id: string) => Promise<void>;
  /** 按当前模式载入索引：真实模式走后端，否则 Mock。供路由刷新恢复使用。 */
  ensureIndex: () => Promise<void>;
  setBackendMode: (b: boolean) => void;
  setSelectedId: (id: string | null) => void;
  setQuery: (q: string) => void;
  setRulerOnly: (b: boolean) => void;
  clearProfileRequest: (dataSource: DataSource, saveId: string, id: string) => void;

  resetParse: () => void;
  setParseStage: (
    id: string,
    status: ParseStageStatus,
    extra?: Partial<ParseStageState>,
  ) => void;
  setParseError: (msg: string | null) => void;
}

export const useStore = create<AppState>((set, get) => ({
  saveMeta: null,
  characterIndex: [],
  profileCache: {},
  indexLoaded: false,

  selectedCharacterId: null,
  profileRequestStateById: {},

  backendMode: false,

  query: "",
  rulerOnly: false,

  parseStages: initialParseStages(),
  parseError: null,

  setIndex: (meta, index) =>
    set({ saveMeta: meta, characterIndex: index, indexLoaded: true }),

  loadProfile: async (dataSource: DataSource, saveId: string, id: string) => {
    const key = profileCacheKey(dataSource, saveId, id);
    const current = get().profileRequestStateById[key];
    // 缓存命中：已成功且档案已在缓存，不再访问仓库（避免重复取档）。
    if (current?.status === "success" && get().profileCache[key]) return;

    // 并发合并：同复合键已有进行中的请求，直接复用其 Promise（只访问一次仓库）。
    const inflight = profileInflightById.get(key);
    if (inflight) return inflight.promise;

    // 每复合键独立序号：A/B、不同存档互不干扰，晚返回不会作废新结果。
    const requestId = (profileReqSeqById[key] ?? 0) + 1;
    profileReqSeqById[key] = requestId;
    set((s) => ({
      selectedCharacterId: id,
      profileRequestStateById: {
        ...s.profileRequestStateById,
        [key]: { status: "loading", requestId },
      },
    }));

    const promise = (async () => {
      try {
        // 真实存档明确绑定 saveId；Mock 演示数据不区分 saveId。
        const profile =
          dataSource === "real"
            ? await realCharacterRepository.loadProfile(id, saveId)
            : await mockCharacterRepository.loadProfile(id);
        // 仅当本次请求仍为该复合键最新时才写入；旧请求不得覆盖新结果。
        if (profileReqSeqById[key] !== requestId) return;
        set((s) => ({
          profileCache: { ...s.profileCache, [key]: profile },
          profileRequestStateById: {
            ...s.profileRequestStateById,
            [key]: { status: "success", requestId },
          },
        }));
      } catch (e) {
        if (profileReqSeqById[key] !== requestId) return;
        const message = e instanceof Error ? e.message : String(e);
        set((s) => ({
          profileRequestStateById: {
            ...s.profileRequestStateById,
            [key]: { status: "error", error: message, requestId },
          },
        }));
      } finally {
        // 仅当该条目仍属于本次请求时才清除，避免误删重试产生的新请求。
        const entry = profileInflightById.get(key);
        if (entry && entry.requestId === requestId) {
          profileInflightById.delete(key);
        }
      }
    })();

    profileInflightById.set(key, { promise, requestId });
    return promise;
  },

  setSelectedId: (id) => set({ selectedCharacterId: id }),

  setBackendMode: (b) => set({ backendMode: b }),

  // 仅 Mock 模式需要把全量摘要载入 store（Mock 数据仅数十条，可接受）。
  // 真实模式不走此路径：人物选择页按需分页从后端拉取，绝不一次性载入数万条，
  // 避免 Zustand 持有 35078 条人物（规范：Zustand 不存全量）。
  ensureIndex: async () => {
    if (get().indexLoaded) return;
    const { meta, characterIndex } = await mockCharacterRepository.loadIndex();
    set({ saveMeta: meta, characterIndex, indexLoaded: true });
  },
  setQuery: (q) => set({ query: q }),
  setRulerOnly: (b) => set({ rulerOnly: b }),
  clearProfileRequest: (dataSource, saveId, id) =>
    set((s) => {
      const key = profileCacheKey(dataSource, saveId, id);
      // 使任何进行中的旧请求作废（其响应回来时会被丢弃），
      // 并清掉 in-flight 条目，使紧随其后的重试能以全新请求覆盖。
      profileReqSeqById[key] = (profileReqSeqById[key] ?? 0) + 1;
      profileInflightById.delete(key);
      return {
        profileRequestStateById: {
          ...s.profileRequestStateById,
          [key]: { status: "idle", requestId: 0 },
        },
      };
    }),

  resetParse: () =>
    set({ parseStages: initialParseStages(), parseError: null }),

  setParseStage: (id, status, extra) =>
    set((s) => ({
      parseStages: s.parseStages.map((st) =>
        st.id === id ? { ...st, status, ...(extra ?? {}) } : st,
      ),
    })),

  setParseError: (msg) => set({ parseError: msg }),
}));
