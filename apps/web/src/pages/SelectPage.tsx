import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useStore } from "../store";
import { useRoute, navigate, ROUTES } from "../lib/router";
import { api } from "../lib/api";
import type { CharacterSummary } from "@shiguan/save-schema";
import { setActiveSaveId } from "../lib/realRepository";
import CharacterCard from "../components/CharacterCard";
import SealButton from "../components/SealButton";

/** 每页人物数（真实存档数万，首屏仅取一页，绝不一次性载入全部）。 */
const PAGE_SIZE = 48;
/** 搜索防抖毫秒。 */
const SEARCH_DEBOUNCE_MS = 300;
/** 真实模式：从后端按需分页加载，首屏仅一页 + 防抖 + 取消过期请求。 */
function RealCharacterBrowser({ saveId }: { saveId: string }) {
  const [items, setItems] = useState<CharacterSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [inputValue, setInputValue] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<number | undefined>(undefined);

  // 进入真实模式：置 backendMode、激活存档（供传记页 loadProfile 使用），并复位分页。
  useEffect(() => {
    useStore.getState().setBackendMode(true);
    setActiveSaveId(saveId, null);
    setItems([]);
    setTotal(0);
    setOffset(0);
    setInputValue("");
    setQuery("");
    loadPage(0, "");
    return () => {
      abortRef.current?.abort();
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveId]);

  function loadPage(off: number, q: string) {
    // 取消上一笔未完成的请求，避免过期响应污染当前页。
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    setError(null);
    api
      .listCharacters(
        saveId,
        { limit: PAGE_SIZE, offset: off, q: q || undefined },
        ctrl.signal,
      )
      .then((page) => {
        if (ctrl.signal.aborted) return;
        setItems(page.items);
        setTotal(page.total);
        setOffset(page.offset);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
  }

  function onSearchChange(v: string) {
    setInputValue(v);
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setQuery(v);
      loadPage(0, v); // 搜索重置到第一页
    }, SEARCH_DEBOUNCE_MS);
  }

  function gotoPage(off: number) {
    if (off < 0 || off >= total) return;
    loadPage(off, query);
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <motion.h1
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="font-serif text-2xl font-bold text-ink-950"
      >
        选择人物
      </motion.h1>
      <p className="mt-1 text-sm text-ink-500">
        本存档共 {total} 位人物。仅载入当前页（{PAGE_SIZE} 条），按需翻页或搜索。
      </p>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <input
          value={inputValue}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="搜索姓名 / 头衔 / 国家 / 王朝"
          aria-label="搜索人物"
          className="w-full rounded-lg border border-ink-400/50 bg-paper-50 px-3 py-2 text-ink-900 placeholder:text-ink-400 focus:border-cinnabar-700 focus:outline-none sm:max-w-sm"
        />
        <SealButton
          variant="ghost"
          onClick={() => navigate(ROUTES.start)}
          className="shrink-0"
        >
          返回存档列表
        </SealButton>
      </div>

      {error && (
        <div className="mt-4" role="alert">
          <p className="rounded-md bg-cinnabar-700/10 px-3 py-2 text-sm text-cinnabar-700">
            {error}
          </p>
          <SealButton
            variant="primary"
            className="mt-2"
            onClick={() => loadPage(offset, query)}
          >
            重试
          </SealButton>
        </div>
      )}

      {loading && (
        <p className="mt-6 text-ink-600" role="status" aria-live="polite">
          正在载入人物…
        </p>
      )}

      {!loading && !error && items.length === 0 && (
        <p className="mt-6 text-sm text-ink-500">
          {query ? "没有匹配的人物。" : "本存档暂无人物。"}
        </p>
      )}

      {!loading && !error && items.length > 0 && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((c) => (
              <CharacterCard
                key={c.id}
                summary={c}
                onClick={() => navigate(ROUTES.saveCharacter(saveId, c.id))}
              />
            ))}
          </div>

          <div className="mt-6 flex items-center justify-center gap-3 text-sm text-ink-600">
            <SealButton
              variant="ghost"
              disabled={!hasPrev}
              onClick={() => gotoPage(offset - PAGE_SIZE)}
            >
              上一页
            </SealButton>
            <span>
              第 {currentPage} / {totalPages} 页
            </span>
            <SealButton
              variant="ghost"
              disabled={!hasNext}
              onClick={() => gotoPage(offset + PAGE_SIZE)}
            >
              下一页
            </SealButton>
          </div>
        </>
      )}
    </div>
  );
}

/** Mock 演示模式：读取 store 中的全量摘要（仅数十条），客户端筛选。 */
function MockSelectPage() {
  const indexLoaded = useStore((s) => s.indexLoaded);
  const characterIndex = useStore((s) => s.characterIndex);
  const query = useStore((s) => s.query);
  const rulerOnly = useStore((s) => s.rulerOnly);
  const setQuery = useStore((s) => s.setQuery);
  const setRulerOnly = useStore((s) => s.setRulerOnly);

  const filtered = (() => {
    const q = query.trim().toLowerCase();
    return characterIndex.filter((c) => {
      if (rulerOnly && !c.isRuler) return false;
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) ||
        (c.primaryTitle?.name ?? "").toLowerCase().includes(q) ||
        (c.dynasty?.name ?? "").toLowerCase().includes(q)
      );
    });
  })();

  if (!indexLoaded) {
    return (
      <div
        className="mx-auto max-w-2xl px-5 py-12 text-ink-600"
        role="status"
        aria-live="polite"
      >
        正在载入人物索引…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <motion.h1
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="font-serif text-2xl font-bold text-ink-950"
      >
        选择人物
      </motion.h1>
      <p className="mt-1 text-sm text-ink-500">
        本存档共 {characterIndex.length} 位人物。以下为摘要索引（完整档案按需载入），点击进入其传记。
      </p>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索姓名 / 头衔 / 国家 / 王朝"
          aria-label="搜索人物"
          className="w-full rounded-lg border border-ink-400/50 bg-paper-50 px-3 py-2 text-ink-900 placeholder:text-ink-400 focus:border-cinnabar-700 focus:outline-none sm:max-w-sm"
        />
        <label className="flex items-center gap-2 text-sm text-ink-700">
          <input
            type="checkbox"
            checked={rulerOnly}
            onChange={(e) => setRulerOnly(e.target.checked)}
            className="h-4 w-4 accent-cinnabar-700"
          />
          仅显示统治者
        </label>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((c) => (
          <CharacterCard
            key={c.id}
            summary={c}
            onClick={() => navigate(ROUTES.character(c.id))}
          />
        ))}
        {filtered.length === 0 && (
          <p className="col-span-full text-sm text-ink-500">没有匹配的人物。</p>
        )}
      </div>
    </div>
  );
}

export default function SelectPage() {
  const route = useRoute();
  // 真实存档路由：URL 携带 saveId，按页从后端加载（首屏仅一页）。
  if (route.params.saveId) {
    return <RealCharacterBrowser saveId={route.params.saveId} />;
  }
  return <MockSelectPage />;
}
