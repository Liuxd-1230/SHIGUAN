/**
 * CharacterRepository —— 人物档案仓库接口与 Mock 实现。
 *
 * 设计要点（Phase 1B）：
 *  - 索引（轻量摘要）与完整档案（CharacterProfile）分离。
 *  - 完整档案通过 import.meta.glob(eager:false) 懒加载：每个 profiles/<id>.json
 *    是一个独立代码块，只有在用户点开某个人物时才被动态 import，
 *    绝不会在初始化时把所有完整档案打进主 bundle。
 *  - 所有载入都经过运行时校验（contractValidate），未知 id / 档案缺失 /
 *    JSON 损坏都会进入可读错误，而非白屏。
 */
import type {
  CharacterProfile,
  CharacterSummary,
  ParsedSaveMeta,
} from "@shiguan/save-schema";
import { validateIndexEnvelope, validateProfileEnvelope } from "./contractValidate";

export interface CharacterIndexResult {
  meta: ParsedSaveMeta;
  characterIndex: CharacterSummary[];
}

export interface CharacterRepository {
  /** 载入人物摘要索引（供选择页），按需也可包含存档元信息。 */
  loadIndex(): Promise<CharacterIndexResult>;
  /** 按 id 载入完整档案（真正的按需取档）。 */
  loadProfile(id: string): Promise<CharacterProfile>;
}

// 懒加载：每个完整档案是独立 chunk，仅在调用 loadProfile 时动态 import。
// 注意：import.meta.glob 不支持别名，这里用相对路径（从 apps/web/src/lib 上溯 4 级到仓库根）。
const profileModules = import.meta.glob(
  "../../../../fixtures/mock/profiles/*.json",
  { eager: false },
) as Record<string, () => Promise<{ default: unknown }>>;

function idFromPath(path: string): string {
  const base = path.split("/").pop() ?? path;
  return base.replace(/\.json$/i, "");
}

const profileLoaders = new Map<string, () => Promise<{ default: unknown }>>();
for (const [path, loader] of Object.entries(profileModules)) {
  profileLoaders.set(idFromPath(path), loader);
}

// 索引包较小，直接静态引入（仅含摘要 + 定位符，不含完整档案）。
import indexJson from "@mock/index.json";

export class MockCharacterRepository implements CharacterRepository {
  async loadIndex(): Promise<CharacterIndexResult> {
    const env = validateIndexEnvelope(indexJson);
    return {
      meta: env.data.meta,
      characterIndex: env.data.characterIndex,
    };
  }

  async loadProfile(id: string): Promise<CharacterProfile> {
    const loader = profileLoaders.get(id);
    if (!loader) {
      throw new Error(
        `未找到人物「${id}」的档案文件。该人物可能不存在，或档案尚未生成。`,
      );
    }
    const mod = await loader();
    // 运行时校验：id 一致性 + timeline 结构 + confidence 合法性 + evidence 存在。
    return validateProfileEnvelope(mod.default, id);
  }
}

/** 默认 Mock 仓库单例。 */
export const mockCharacterRepository: CharacterRepository = new MockCharacterRepository();
