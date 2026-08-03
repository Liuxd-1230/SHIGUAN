/**
 * RealCharacterRepository —— 通过后端 API 读取真实 CK3 存档（Phase 2A）。
 *
 * 仅当后端可用且用户选择了本地存档时启用（store.backendMode=true）。
 * 其余情况前端继续使用 MockCharacterRepository，行为与之前完全一致。
 *
 * 索引：调用 /api/saves/{saveId}/characters 一次取全量摘要（真实存档人物数万，
 * 但后端已 melt 并缓存，单次请求可接受；选择页按需再分页）。
 * 档案：按 id 调 /api/saves/{saveId}/characters/{id} 按需取。
 */
import type {
  CharacterProfile,
  ParsedSaveMeta,
} from "@shiguan/save-schema";
import type { CharacterRepository, CharacterIndexResult } from "./characterRepository";
import { api } from "./api";

let _activeSaveId: string | null = null;
let _cachedMeta: ParsedSaveMeta | null = null;

export function setActiveSaveId(saveId: string | null, meta: ParsedSaveMeta | null): void {
  _activeSaveId = saveId;
  _cachedMeta = meta;
}

export function getActiveSaveId(): string | null {
  return _activeSaveId;
}

export class RealCharacterRepository implements CharacterRepository {
  async loadIndex(): Promise<CharacterIndexResult> {
    if (!_activeSaveId) throw new Error("未选择本地存档（saveId 为空）。");
    const page = await api.listCharacters(_activeSaveId, { limit: 100000, offset: 0 });
    return {
      meta: _cachedMeta as ParsedSaveMeta,
      characterIndex: page.items,
    };
  }

  async loadProfile(id: string, saveId?: string): Promise<CharacterProfile> {
    const sid = saveId ?? _activeSaveId;
    if (!sid) throw new Error("未选择本地存档（saveId 为空）。");
    return api.getProfile(sid, id);
  }
}

export const realCharacterRepository: CharacterRepository = new RealCharacterRepository();
