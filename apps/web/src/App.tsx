import { useEffect, useRef, useState } from "react";
import { AnimatePresence, MotionConfig } from "framer-motion";
import { useStore, profileCacheKey, MOCK_SAVE_ID, type DataSource } from "./store";
import { useRoute, navigate, ROUTES } from "./lib/router";
import Header from "./components/Header";
import StartPage from "./pages/StartPage";
import ParsePage from "./pages/ParsePage";
import RealParsePage from "./pages/RealParsePage";
import SelectPage from "./pages/SelectPage";
import BiographyPage from "./pages/BiographyPage";
import DesignLabPage from "./pages/DesignLabPage";
import MuseumSurface from "./components/MuseumSurface";
import PageTransition from "./components/PageTransition";

function NotFoundPage() {
  return (
    <div className="mx-auto max-w-2xl px-5 py-12">
      <MuseumSurface variant="raised" className="p-5">
        <p className="font-medium text-ink-900">页面不存在</p>
        <p className="mt-2 text-sm text-ink-600">
          找不到路径「{typeof window !== "undefined" ? window.location.pathname : ""}」。
        </p>
        <button
          type="button"
          onClick={() => navigate(ROUTES.start)}
          className="mt-4 rounded-lg border border-ink-400/60 px-4 py-2 text-sm text-ink-700 hover:border-ink-600 hover:bg-paper-100"
        >
          返回起始页
        </button>
      </MuseumSurface>
    </div>
  );
}

export default function App() {
  const route = useRoute();
  const indexLoaded = useStore((s) => s.indexLoaded);
  // 传记页标题需要人物名（索引摘要或已载入档案）。
  const bioName = useStore((s) => {
    if (route.name !== "bio") return undefined;
    const id = route.params.characterId;
    if (!id) return undefined;
    // 复合键：真实/ Mock 数据源 + saveId + characterId，与 store 缓存键一致。
    const ds: DataSource = route.params.saveId ? "real" : "mock";
    const sid = route.params.saveId ?? MOCK_SAVE_ID;
    return (
      s.characterIndex.find((c) => c.id === id)?.name ??
      s.profileCache[profileCacheKey(ds, sid, id)]?.name
    );
  });
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);

  // 刷新恢复：直接访问 /characters 或 /characters/:id 时，先确保索引已载入。
  // 真实存档路由（携带 saveId）由对应页面自行按需分页加载，不在此触发全量索引载入。
  useEffect(() => {
    if (route.name !== "select" && route.name !== "bio") return;
    if (route.params.saveId) return;
    if (indexLoaded) return;
    let cancelled = false;
    useStore
      .getState()
      .ensureIndex()
      .then(() => {
        /* 状态已由 ensureIndex 写入 store */
      })
      .catch((e) => {
        if (!cancelled) {
          setBootstrapError(e instanceof Error ? e.message : String(e));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [route.name, route.params.saveId, indexLoaded]);

  // 页面标题随路由更新（含传记页人物名）。减少无谓刷新：仅依赖路径与人物名。
  useEffect(() => {
    let title = "史官 SHIGUAN";
    if (route.name === "parse") title = "解析存档 · 史官";
    else if (route.name === "select") title = "选择人物 · 史官";
    else if (route.name === "bio")
      title = bioName ? `${bioName} · 人物传记 · 史官` : "人物传记 · 史官";
    else if (route.name === "notfound") title = "页面不存在 · 史官";
    document.title = title;
  }, [route.name, route.path, bioName]);

  // 路由切换（含同一页面不同人物 A→B）后将焦点移入主内容区；
  // 依赖 route.path 而非仅 route.name，确保切换人物时也重新聚焦，
  // 且 preventScroll 避免焦点跳跃。
  useEffect(() => {
    if (mainRef.current) {
      mainRef.current.focus({ preventScroll: true });
    }
  }, [route.path]);

  let page;
  if (bootstrapError) {
    page = (
      <div className="mx-auto max-w-2xl px-5 py-12" role="alert">
        <MuseumSurface variant="raised" className="border-cinnabar-700/40 p-5">
          <p className="font-medium text-cinnabar-700">索引载入失败</p>
          <p className="mt-2 break-words text-sm text-ink-700">
            {bootstrapError}
          </p>
          <button
            type="button"
            onClick={() => navigate(ROUTES.start)}
            className="mt-4 rounded-lg border border-ink-400/60 px-4 py-2 text-sm text-ink-700 hover:border-ink-600 hover:bg-paper-100"
          >
            返回起始页
          </button>
        </MuseumSurface>
      </div>
    );
  } else if (route.name === "start") {
    page = <StartPage />;
  } else if (route.name === "parse") {
    // 带 saveId 的真实解析过程页；无 saveId 走 Mock 演示流程。
    page = route.params.saveId ? (
      <RealParsePage saveId={route.params.saveId} />
    ) : (
      <ParsePage />
    );
  } else if (route.name === "select") {
    page = <SelectPage />;
  } else if (route.name === "bio") {
    page = <BiographyPage />;
  } else if (route.name === "designlab") {
    page = <DesignLabPage />;
  } else {
    page = <NotFoundPage />;
  }

  return (
    <MotionConfig reducedMotion="user">
      <a href="#main-content" className="skip-link">
        跳到主内容
      </a>
      <div className="flex min-h-full flex-col">
        <Header />
        <main
          id="main-content"
          ref={mainRef}
          tabIndex={-1}
          className="flex-1 outline-none"
        >
          <AnimatePresence mode="wait">
            <PageTransition key={route.path}>{page}</PageTransition>
          </AnimatePresence>
        </main>
      </div>
    </MotionConfig>
  );
}
