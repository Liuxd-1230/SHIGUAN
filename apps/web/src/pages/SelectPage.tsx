import { useMemo } from "react";
import { motion } from "framer-motion";
import { useStore } from "../store";
import { navigate, ROUTES } from "../lib/router";
import CharacterCard from "../components/CharacterCard";

export default function SelectPage() {
  const indexLoaded = useStore((s) => s.indexLoaded);
  const characterIndex = useStore((s) => s.characterIndex);
  const query = useStore((s) => s.query);
  const rulerOnly = useStore((s) => s.rulerOnly);
  const setQuery = useStore((s) => s.setQuery);
  const setRulerOnly = useStore((s) => s.setRulerOnly);

  const filtered = useMemo(() => {
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
  }, [characterIndex, query, rulerOnly]);

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
          placeholder="搜索姓名 / 头衔 / 王朝"
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
