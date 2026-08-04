/**
 * 后端 API 客户端（Phase 2A）。
 *
 * 设计：
 *  - 所有请求走 fetch，base URL 取 import.meta.env.VITE_API_BASE，缺省 http://localhost:8000。
 *  - checkBackendAvailable() 做一次带超时的 /api/health 探测，结果缓存；
 *    探测失败（后端未启动）时上层回退到 Mock 演示流程，绝不阻塞 UI。
 *  - 解析失败显式抛出，由调用方转成可读错误。
 */
import type {
  CharacterProfile,
  CharacterSummary,
  ParsedSaveMeta,
} from "@shiguan/save-schema";

const envBase = (import.meta.env as Record<string, unknown>).VITE_API_BASE;
const BASE: string =
  typeof envBase === "string" && envBase.length > 0
    ? envBase
    : "http://localhost:8000";

export interface LocalSaveSummary {
  saveId: string;
  fileName: string;
  displayName: string;
  sizeBytes: number;
  modifiedAt: string;
  isAutosave: boolean;
  status: string;
  gameVersion: string | null;
  date: string | null;
  modCount: number | null;
  lastParseStatus: string;
}

export interface ModReport {
  required_count: number;
  found_count: number;
  missing_count: number;
  version_mismatch_count: number;
  corrupted_count: number;
  localization_available: boolean;
  required: Array<Record<string, unknown>>;
  missing: string[];
  version_mismatch: string[];
  corrupted: string[];
  playset_diff: unknown | null;
}

export interface ParseResult {
  saveId: string;
  meta: ParsedSaveMeta;
  player_name: string | null;
  mod_count: number;
  mods: ModReport;
  character_count: number;
  dead_character_count: number;
  encoding: string;
  unknown_token_count: number;
  header_parse_ok: boolean;
  parse_ms: number;
  sample: CharacterSummary[];
  game_data: Record<string, unknown>;
  localization: { loaded_languages: string[]; entry_count: number };
}

export interface CharacterPage {
  saveId: string;
  total: number;
  offset: number;
  limit: number;
  items: CharacterSummary[];
}

let _available: boolean | null = null;

async function _getJson(path: string, signal?: AbortSignal): Promise<unknown> {
  return _request("GET", path, undefined, signal);
}

/**
 * 通用请求：显式指定 HTTP 方法，避免把 POST/DELETE 端点误用 GET（405）。
 * 后端路由方法：rescan/import/parse/watch 为 POST，delete 为 DELETE，其余为 GET。
 */
async function _request(
  method: "GET" | "POST" | "DELETE",
  path: string,
  init?: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<unknown> {
  const res = await fetch(`${BASE}${path}`, { method, signal, ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`后端请求失败（${res.status}）：${text.slice(0, 200)}`);
  }
  return res.json();
}

export async function checkBackendAvailable(
  timeoutMs = 800,
): Promise<boolean> {
  if (_available !== null) return _available;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    await fetch(`${BASE}/api/health`, { signal: ctrl.signal });
    _available = true;
  } catch {
    _available = false;
  } finally {
    clearTimeout(t);
  }
  return _available;
}

export function resetBackendAvailableCache(): void {
  _available = null;
}

export const api = {
  listLocalSaves: (signal?: AbortSignal) =>
    _getJson("/api/local-saves", signal) as Promise<{
      available: boolean;
      saves: LocalSaveSummary[];
    }>,
  rescanLocalSaves: (signal?: AbortSignal) =>
    _request("POST", "/api/local-saves/rescan", undefined, signal) as Promise<{
      available: boolean;
      saves: LocalSaveSummary[];
    }>,
  inspectSave: (saveId: string, signal?: AbortSignal) =>
    _getJson(`/api/local-saves/${saveId}/inspect`, signal) as Promise<Record<string, unknown>>,
  modsForSave: (saveId: string, signal?: AbortSignal) =>
    _getJson(`/api/local-saves/${saveId}/mods`, signal) as Promise<{
      saveId: string;
      report: ModReport;
    }>,
  parseSave: (saveId: string, signal?: AbortSignal) =>
    _request("POST", `/api/local-saves/${saveId}/parse`, undefined, signal) as Promise<ParseResult>,
  listCharacters: (
    saveId: string,
    opts: { limit?: number; offset?: number; q?: string } = {},
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams();
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.offset != null) params.set("offset", String(opts.offset));
    if (opts.q) params.set("q", opts.q);
    return _getJson(
      `/api/saves/${saveId}/characters?${params.toString()}`,
      signal,
    ) as Promise<CharacterPage>;
  },
  getProfile: (saveId: string, characterId: string, signal?: AbortSignal) =>
    _getJson(
      `/api/saves/${saveId}/characters/${encodeURIComponent(characterId)}`,
      signal,
    ) as Promise<CharacterProfile>,
  deleteSave: (saveId: string, signal?: AbortSignal) =>
    _request("DELETE", `/api/saves/${saveId}`, undefined, signal) as Promise<{
      saveId: string;
      removed: boolean;
    }>,
};

export const API_BASE = BASE;
