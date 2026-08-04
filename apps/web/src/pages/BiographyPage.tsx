import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useStore, IDLE_REQUEST, profileCacheKey, MOCK_SAVE_ID, type DataSource } from "../store";
import { useRoute, navigate, ROUTES } from "../lib/router";
import { setActiveSaveId } from "../lib/realRepository";
import { buildDraft, eventChapterMap } from "../lib/buildOutline";
import { titleTierLabel } from "../lib/labels";
import type { TitlePeriod } from "@shiguan/save-schema";
import Timeline, { TimelineDensity } from "../components/Timeline";
import EvidencePanel from "../components/EvidencePanel";
import MemoriesPanel from "../components/MemoriesPanel";
import OutlinePanel from "../components/OutlinePanel";
import PortraitFrame from "../components/PortraitFrame";
import MuseumSurface from "../components/MuseumSurface";
import ScrollPanel from "../components/ScrollPanel";
import SealButton from "../components/SealButton";
import InkDivider from "../components/InkDivider";
import { ChevronLeft } from "../components/icons";
import { cn } from "../lib/cn";

function lifeSpan(birth?: string, death?: string, alive?: boolean): string {
  const b = birth ? birth.split(".")[0] : "生年不详";
  const d = death ? death.split(".")[0] : alive ? "在世" : "卒年不详";
  return `${b} – ${d}`;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

function isDesktop(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(min-width: 1024px)").matches
  );
}

// 滚动锁定：点击时间线触发自动滚动期间，忽略 IntersectionObserver 的更新，
// 避免高亮在平滑滚动过程中反复跳动。
const SCROLL_LOCK_MS = 700;

export default function BiographyPage() {
  const route = useRoute();
  const characterId = route.params.characterId ?? null;
  const saveId = route.params.saveId ?? null;
  const isReal = !!saveId;
  const backToSelect = isReal
    ? ROUTES.savesCharacters(saveId)
    : ROUTES.characters;

  // 复合键维度：dataSource(real/mock) + saveId + characterId，确保多存档不串档。
  const dataSource: DataSource = isReal ? "real" : "mock";
  const effectiveSaveId = isReal ? (saveId as string) : MOCK_SAVE_ID;
  const pkey = characterId ? profileCacheKey(dataSource, effectiveSaveId, characterId) : "";

  const characterIndex = useStore((s) => s.characterIndex);
  const indexLoaded = useStore((s) => s.indexLoaded);
  const reqState = useStore((s) =>
    pkey ? s.profileRequestStateById[pkey] ?? IDLE_REQUEST : IDLE_REQUEST,
  );
  const loadProfile = useStore((s) => s.loadProfile);
  const clearProfileRequest = useStore((s) => s.clearProfileRequest);

  const profile = useStore((s) => (pkey ? s.profileCache[pkey] : undefined));
  const summary = useMemo(
    () => characterIndex.find((c) => c.id === characterId),
    [characterIndex, characterId],
  );

  // 真实模式：进入即置 backendMode 并激活存档，供 loadProfile 经后端取档；
  // 不依赖全量索引，刷新/深链到 /saves/:saveId/characters/:id 亦可恢复。
  useEffect(() => {
    if (!isReal || !saveId) return;
    useStore.getState().setBackendMode(true);
    setActiveSaveId(saveId, null);
  }, [isReal, saveId]);

  // 载入完整档案（真正的按需取档）。仅当该人物处于 idle（且未缓存）时触发，
  // 成功态命中缓存不再访问仓库；错误态由"重试"按钮显式触发，避免自动重试死循环。
  useEffect(() => {
    if (!characterId) return;
    // Mock：索引中不存在该人物则无需取档（由 NotFound 处理）。
    // 真实模式无全量索引，跳过该判断，直接按需取档。
    if (!isReal && !summary) return;
    if (reqState.status !== "idle") return;
    if (profile) return;
    loadProfile(dataSource, effectiveSaveId, characterId);
  }, [characterId, summary, reqState.status, profile, loadProfile, isReal, dataSource, effectiveSaveId]);

  const draft = useMemo(
    () => (profile ? buildDraft(profile) : null),
    [profile],
  );
  const map = useMemo(
    () => (draft ? eventChapterMap(draft.chapters) : {}),
    [draft],
  );

  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null);
  const [density, setDensity] = useState<TimelineDensity>("all");

  const lockUntilRef = useRef(0);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // 档案就绪后，默认选中首条事件
  useEffect(() => {
    if (profile && profile.timeline.length > 0) {
      const first = profile.timeline[0].id;
      setActiveEventId(first);
      setActiveChapterId(map[first] ?? null);
    }
  }, [profile, map]);

  // 双向联动：IntersectionObserver 监测章节进入视口，更新当前章节
  useEffect(() => {
    if (!draft) return;
    const root = containerRef.current;
    if (!root || typeof IntersectionObserver === "undefined") return;

    const elements = draft.chapters
      .map((ch) => root.querySelector<HTMLElement>(`#chapter-${ch.id}`))
      .filter((el): el is HTMLElement => el !== null);

    const observer = new IntersectionObserver(
      (entries) => {
        if (performance.now() < lockUntilRef.current) return; // 滚动锁定期间忽略
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible.length === 0) return;
        const id = visible[0].target.id.replace(/^chapter-/, "");
        setActiveChapterId(id);
        const firstEvent = draft.chapters.find((c) => c.id === id)?.eventIds[0];
        if (firstEvent) setActiveEventId(firstEvent);
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: [0, 0.25, 0.5, 1] },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [draft]);

  function selectEvent(id: string) {
    setActiveEventId(id);
    const ch = map[id];
    if (ch) setActiveChapterId(ch);
    // 仅在桌面且未要求减弱动效时，自动滚动到对应章节
    if (!prefersReducedMotion() && isDesktop()) {
      lockUntilRef.current = performance.now() + SCROLL_LOCK_MS;
      document
        .getElementById(`chapter-${map[id]}`)
        ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  // —— 边界状态 ——
  if (!isReal && !indexLoaded) {
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
  if (characterId && !isReal && !summary) {
    return <NotFound characterId={characterId} backPath={backToSelect} />;
  }
  if (reqState.status === "loading") {
    return (
      <div
        className="mx-auto max-w-2xl px-5 py-12 text-ink-600"
        role="status"
        aria-live="polite"
      >
        正在载入「{characterId}」的完整档案…
      </div>
    );
  }
  if (reqState.status === "error") {
    return (
      <div className="mx-auto max-w-2xl px-5 py-12" role="alert">
        <MuseumSurface variant="raised" className="p-5">
          <p className="font-medium text-cinnabar-700">档案载入失败</p>
          <p className="mt-2 break-words text-sm text-ink-700">
            {reqState.error}
          </p>
          <div className="mt-4 flex gap-2">
            <SealButton
              variant="primary"
              seal
              onClick={() => {
                if (characterId) {
                  clearProfileRequest(dataSource, effectiveSaveId, characterId);
                  loadProfile(dataSource, effectiveSaveId, characterId);
                }
              }}
            >
              重试载入
            </SealButton>
            <SealButton
              variant="ghost"
              onClick={() => navigate(backToSelect)}
            >
              返回选择页
            </SealButton>
          </div>
        </MuseumSurface>
      </div>
    );
  }
  if (!profile || !draft) {
    return (
      <div className="mx-auto max-w-2xl px-5 py-12 text-ink-600">
        未找到该人物档案。请返回选择页。
      </div>
    );
  }

  const activeChapterEventIds = new Set(
    draft.chapters.find((c) => c.id === activeChapterId)?.eventIds ?? [],
  );
  const activeEvent = profile.timeline.find((e) => e.id === activeEventId);

  return (
    <div className="mx-auto max-w-6xl px-5 py-8" ref={containerRef}>
      <SealButton
        variant="ghost"
        className="mb-3 -ml-2"
        onClick={() => navigate(backToSelect)}
        aria-label="返回选择页"
      >
        <ChevronLeft size={16} />
        返回选择页
      </SealButton>

      <MuseumSurface variant="raised" className="p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <PortraitFrame
            name={profile.name}
            cultureLabel={profile.culture?.name}
            size={84}
          />
          <div className="min-w-0">
            <h1 className="font-serif text-3xl font-bold text-ink-950">
              {profile.name}
            </h1>
            <p className="mt-1 text-ink-600">
              {summary?.primaryTitle?.name ?? "无头衔"}
              {summary?.dynasty && <span> · {summary.dynasty.name}</span>}
              {summary && (
                <span>
                  {" "}
                  · {lifeSpan(summary.birthDate, summary.deathDate, summary.isAlive)}
                </span>
              )}
            </p>
          </div>
        </div>
      </MuseumSurface>

      <div className="mt-6">
        <TitlesPanel titles={profile.titles} />
      </div>

      <div className="mt-6">
        <MemoriesPanel profile={profile} />
      </div>

      {/* Phase 3A：AI 传记提纲（仅真实模式；打开页面不自动生成，点按钮才调用模型） */}
      {isReal && characterId && (
        <div className="mt-6">
          <OutlinePanel saveId={effectiveSaveId} characterId={characterId} />
        </div>
      )}

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 时间线 + 密度控制（移动端排正文之后） */}
        <section className="order-2 lg:order-1">
          <div className="mb-2 flex items-center gap-2 text-xs">
            <span className="text-ink-500">密度</span>
            {(["all", "key"] as TimelineDensity[]).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDensity(d)}
                aria-pressed={density === d}
                className={cn(
                  "min-h-[2.25rem] rounded border px-2 py-0.5 transition-colors",
                  density === d
                    ? "border-cinnabar-700/60 text-cinnabar-700"
                    : "border-ink-400/50 text-ink-500 hover:text-ink-900",
                )}
              >
                {d === "all" ? "全部事件" : "关键事件"}
              </button>
            ))}
          </div>
          <Timeline
            events={profile.timeline}
            activeId={activeEventId}
            activeChapterEventIds={activeChapterEventIds}
            onSelect={selectEvent}
            density={density}
          />
        </section>

        {/* 传记正文（移动端置顶） */}
        <section className="order-1 lg:order-2">
          <div className="mb-3">
            <h2 className="font-serif text-lg font-bold text-ink-900">传记</h2>
            <p className="mt-1 text-xs text-ink-500">
              传记草稿（由存档数据自动整理，非 AI 生成）
            </p>
          </div>
          <div className="space-y-5">
            {draft.chapters.map((ch) => {
              const active = ch.id === activeChapterId;
              return (
                <motion.div
                  key={ch.id}
                  initial={{ opacity: 0, y: 10 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: "-8% 0px -8% 0px" }}
                  transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                >
                  <ScrollPanel
                    as="article"
                    id={`chapter-${ch.id}`}
                    className={cn(
                      "transition-colors",
                      active && "ring-1 ring-cinnabar-700/40",
                    )}
                  >
                    <h3 className="font-serif text-lg font-bold text-ink-900">
                      {ch.title}
                    </h3>
                    <InkDivider className="my-3" animateInk />
                    <p className="text-sm leading-relaxed text-ink-700">
                      {ch.content}
                    </p>
                  </ScrollPanel>
                </motion.div>
              );
            })}
          </div>
        </section>

        {/* 史料依据面板 */}
        <section className="order-3 lg:order-3">
          <MuseumSurface variant="inset" className="p-4">
            <EvidencePanel
              event={activeEvent}
              warnings={profile.evidenceWarnings}
            />
          </MuseumSurface>
        </section>
      </div>
    </div>
  );
}

function periodText(p: TitlePeriod): string {
  if (p.start && p.end) return `${p.start} – ${p.end}`;
  if (p.start) return `${p.start} 起`;
  if (p.end) return `至 ${p.end}`;
  return "任期时间不详";
}

/** 头衔与统治面板（M3）：现任 + 历史任期，带等级/起止/证据出处，不伪造。 */
export function TitlesPanel({ titles }: { titles: TitlePeriod[] }) {
  if (!titles || titles.length === 0) {
    return (
      <MuseumSurface variant="raised" className="p-4">
        <h2 className="font-serif text-lg font-bold text-ink-900">头衔与统治</h2>
        <p className="mt-2 text-sm text-ink-500">
          存档的 landed_titles 记录中未找到该人物的头衔（可能为无领地的宫廷角色）。
        </p>
      </MuseumSurface>
    );
  }
  const current = titles.filter((t) => t.isCurrent);
  const historical = titles.filter((t) => !t.isCurrent);
  return (
    <MuseumSurface variant="raised" className="p-4">
      <h2 className="font-serif text-lg font-bold text-ink-900">头衔与统治</h2>
      <p className="mt-1 text-xs text-ink-500">
        由存档 landed_titles 的 holder/history 反解；未解析头衔以 key 原样展示。
      </p>
      {current.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold tracking-wide text-ink-500">现任</h3>
          <ul className="mt-1 space-y-1.5">
            {current.map((t) => (
              <li
                key={`cur-${t.titleId}`}
                className="rounded-lg border border-gold-500/50 bg-gold-500/5 px-3 py-2"
              >
                <span className="text-sm font-semibold text-ink-900">{t.name}</span>
                {t.name === t.titleId && (
                  <span className="ml-1.5 text-[11px] text-ink-400">（未解析）</span>
                )}
                <span className="ml-2 text-[11px] text-ink-500">
                  {titleTierLabel(t.tier) ?? "等级不详"}
                </span>
                <span className="ml-2 text-[11px] text-ink-500">{periodText(t)}</span>
                <span className="ml-1.5 text-[10px] text-ink-400">{t.sourcePath}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {historical.length > 0 && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold tracking-wide text-ink-500">历史任期</h3>
          <ul className="mt-1 space-y-1.5">
            {historical.map((t) => (
              <li
                key={`his-${t.titleId}-${t.start ?? "?"}-${t.end ?? "?"}`}
                className="rounded-lg border border-ink-400/40 bg-paper-100 px-3 py-2"
              >
                <span className="text-sm text-ink-900">{t.name}</span>
                {t.name === t.titleId && (
                  <span className="ml-1.5 text-[11px] text-ink-400">（未解析）</span>
                )}
                <span className="ml-2 text-[11px] text-ink-500">
                  {titleTierLabel(t.tier) ?? "等级不详"}
                </span>
                <span className="ml-2 text-[11px] text-ink-500">{periodText(t)}</span>
                <span className="ml-1.5 text-[10px] text-ink-400">{t.sourcePath}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </MuseumSurface>
  );
}

function NotFound({ characterId, backPath }: { characterId: string; backPath: string }) {
  return (
    <div className="mx-auto max-w-2xl px-5 py-12">
      <MuseumSurface variant="raised" className="p-5">
        <p className="font-medium text-ink-900">未找到该人物</p>
        <p className="mt-2 text-sm text-ink-700">
          存档索引中没有 ID 为「{characterId}」的人物。该人物可能不存在，或档案尚未生成。
        </p>
        <SealButton
          variant="ghost"
          className="mt-4"
          onClick={() => navigate(backPath)}
        >
          返回选择页
        </SealButton>
      </MuseumSurface>
    </div>
  );
}
