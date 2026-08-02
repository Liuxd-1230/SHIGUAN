import { useStore, resetProfileInflight } from "../store";
import { initialParseStages } from "../lib/mockParse";
import type { CharacterSummary, ParsedSaveMeta } from "@shiguan/save-schema";

/** 把 store 重置到初始状态，避免测试间串扰。 */
export function resetStore(): void {
  resetProfileInflight();
  useStore.setState({
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
  });
}

/** 直接把索引写入 store（绕过异步加载，便于测试选择/传记页）。 */
export function seedIndex(
  meta: ParsedSaveMeta,
  index: CharacterSummary[],
): void {
  useStore.getState().setIndex(meta, index);
}

/** 设置当前路由（通过 History API，使 useRoute 生效）。 */
export function setPath(path: string): void {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
