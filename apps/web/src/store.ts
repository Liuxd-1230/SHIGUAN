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
 */
import { create } from "zustand";
import type {
  CharacterProfile,
  CharacterSummary,
  ParsedSaveMeta,
} from "@shiguan/save-schema";
import { mockCharacterRepository } from "./lib/characterRepository";
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

/** 单个人物的档案请求状态（按 id 区分，避免切换互相污染）。 */
export interface ProfileRequestState {
  status: ProfileLoadStatus;
  error?: string;
  /** 本次请求序号；仅当仍为最新序号时，响应才会被采纳。 */
  requestId?: number;
}

export const IDLE_REQUEST: ProfileRequestState = { status: "idle", requestId: 0 };

/**
 * 模块级（在 store 状态之外）：按人物 id 的 in-flight Promise 与每人物请求序号。
 * 放在状态之外，原因有二：
 *  1) 便于跨调用判定"某次响应是否还是该人物的最新请求"（真正的按 id 竞态判定）；
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

  // —— 选择页筛选（独立于路由，返回时保留）——
  query: string;
  rulerOnly: boolean;

  // —— 解析阶段状态 ——
  parseStages: ParseStageState[];
  parseError: string | null;

  // —— actions ——
  setIndex: (meta: ParsedSaveMeta, index: CharacterSummary[]) => void;
  loadProfile: (id: string) => Promise<void>;
  setSelectedId: (id: string | null) => void;
  setQuery: (q: string) => void;
  setRulerOnly: (b: boolean) => void;
  clearProfileRequest: (id: string) => void;

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

  query: "",
  rulerOnly: false,

  parseStages: initialParseStages(),
  parseError: null,

  setIndex: (meta, index) =>
    set({ saveMeta: meta, characterIndex: index, indexLoaded: true }),

  loadProfile: async (id: string) => {
    const current = get().profileRequestStateById[id];
    // 缓存命中：已成功且档案已在缓存，不再访问仓库（避免重复取档）。
    if (current?.status === "success" && get().profileCache[id]) return;

    // 并发合并：同人物已有进行中的请求，直接复用其 Promise（只访问一次仓库）。
    const inflight = profileInflightById.get(id);
    if (inflight) return inflight.promise;

    // 每人物独立序号：A/B 互不干扰，A 的晚返回不会因 B 而作废。
    const requestId = (profileReqSeqById[id] ?? 0) + 1;
    profileReqSeqById[id] = requestId;
    set((s) => ({
      selectedCharacterId: id,
      profileRequestStateById: {
        ...s.profileRequestStateById,
        [id]: { status: "loading", requestId },
      },
    }));

    const promise = (async () => {
      try {
        const profile = await mockCharacterRepository.loadProfile(id);
        // 仅当本次请求仍为该人物最新时才写入；旧请求不得覆盖新结果。
        if (profileReqSeqById[id] !== requestId) return;
        set((s) => ({
          profileCache: { ...s.profileCache, [id]: profile },
          profileRequestStateById: {
            ...s.profileRequestStateById,
            [id]: { status: "success", requestId },
          },
        }));
      } catch (e) {
        if (profileReqSeqById[id] !== requestId) return;
        const message = e instanceof Error ? e.message : String(e);
        set((s) => ({
          profileRequestStateById: {
            ...s.profileRequestStateById,
            [id]: { status: "error", error: message, requestId },
          },
        }));
      } finally {
        // 仅当该条目仍属于本次请求时才清除，避免误删重试产生的新请求。
        const entry = profileInflightById.get(id);
        if (entry && entry.requestId === requestId) {
          profileInflightById.delete(id);
        }
      }
    })();

    profileInflightById.set(id, { promise, requestId });
    return promise;
  },

  setSelectedId: (id) => set({ selectedCharacterId: id }),
  setQuery: (q) => set({ query: q }),
  setRulerOnly: (b) => set({ rulerOnly: b }),
  clearProfileRequest: (id) =>
    set((s) => {
      // 使任何进行中的旧请求作废（其响应回来时会被丢弃），
      // 并清掉 in-flight 条目，使紧随其后的重试能以全新请求覆盖。
      profileReqSeqById[id] = (profileReqSeqById[id] ?? 0) + 1;
      profileInflightById.delete(id);
      return {
        profileRequestStateById: {
          ...s.profileRequestStateById,
          [id]: { status: "idle", requestId: 0 },
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
