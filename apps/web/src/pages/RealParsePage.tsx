import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { api } from "../lib/api";
import { navigate, ROUTES } from "../lib/router";
import { setActiveSaveId } from "../lib/realRepository";
import { useStore } from "../store";
import MuseumSurface from "../components/MuseumSurface";
import SealButton from "../components/SealButton";
import AssetImage from "../components/AssetImage";
import { cn } from "../lib/cn";
import {
  CheckSeal,
  CircleHollow,
  CrossMark,
  SkipMark,
  Spinner,
} from "../components/icons";

/**
 * 真实存档解析过程页（M5，对齐 Mock ParsePage 的体验）。
 *
 * 与 Mock 的差异：阶段由真实后端 API 驱动，非模拟延时——
 *   ① 初检（inspect：文件类型/编码/token 指标）
 *   ② Mod 报告（mods：Mod 兼容性 + 本地化加载）
 *   ③ 解析（parse：一次 melt + 索引建立）
 *   ④ 完成 → 切换真实模式并进入人物选择页。
 * 阶段状态机与 Mock 视觉一致（pending/running/success/error/skipped），
 * 失败可在该阶段重试，成功有朱砂落印仪式反馈（与 Mock 一致）。
 */
const REAL_STAGES = [
  { id: "detect", label: "检测文件类型与编码" },
  { id: "mods", label: "核对 Mod 与本地化" },
  { id: "melt", label: "解析存档并建立索引" },
] as const;

type StageStatus = "pending" | "running" | "success" | "error" | "skipped";
interface LocalStage {
  id: string;
  label: string;
  status: StageStatus;
  error?: string;
}

function initialStages(): LocalStage[] {
  return REAL_STAGES.map((s) => ({ id: s.id, label: s.label, status: "pending" }));
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "success":
      return <CheckSeal size={18} className="text-jade-700" />;
    case "running":
      return <Spinner size={18} className="text-gold-700" />;
    case "error":
      return <CrossMark size={18} className="text-cinnabar-700" />;
    case "skipped":
      return <SkipMark size={18} className="text-ink-400" />;
    default:
      return <CircleHollow size={18} className="text-ink-400" />;
  }
}

export default function RealParsePage({
  saveId,
  successSealMs = 700,
}: {
  saveId: string;
  /** 解析成功后展示朱砂落印的时长（毫秒），随后进入选择页。 */
  successSealMs?: number;
}) {
  const setBackendMode = useStore((s) => s.setBackendMode);
  const abortRef = useRef<AbortController | null>(null);
  const [stages, setStages] = useState<LocalStage[]>(initialStages);
  const [parseError, setParseError] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [showSeal, setShowSeal] = useState(false);

  const mark = useCallback(
    (id: string, status: StageStatus, error?: string) => {
      setStages((prev) =>
        prev.map((st) =>
          st.id === id ? { ...st, status, ...(error ? { error } : {}) } : st,
        ),
      );
    },
    [],
  );

  const runStages = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStages(initialStages());
    setParseError(null);
    setShowDetail(false);

    try {
      // ① 初检（真实后端）。
      mark("detect", "running");
      await api.inspectSave(saveId, controller.signal);
      if (controller.signal.aborted) return;
      mark("detect", "success");

      // ② Mod 报告（真实后端，含本地化加载）。
      mark("mods", "running");
      await api.modsForSave(saveId, controller.signal);
      if (controller.signal.aborted) return;
      mark("mods", "success");

      // ③ 解析（真实后端一次 melt + 索引）。
      mark("melt", "running");
      const result = await api.parseSave(saveId, controller.signal);
      if (controller.signal.aborted) return;
      mark("melt", "success");

      // 完成：切换真实模式 + 激活存档 + 携带 meta 进入选择页。
      setBackendMode(true);
      setActiveSaveId(saveId, result.meta);
      setShowSeal(true);
      window.setTimeout(() => {
        navigate(ROUTES.savesCharacters(saveId));
      }, successSealMs);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      const message = e instanceof Error ? e.message : String(e);
      setStages((prev) =>
        prev.map((st) =>
          st.status === "running"
            ? { ...st, status: "error", error: message }
            : st.status === "pending"
              ? { ...st, status: "skipped" }
              : st,
        ),
      );
      setParseError(message);
    }
  }, [saveId, mark, setBackendMode, successSealMs]);

  useEffect(() => {
    runStages();
    return () => abortRef.current?.abort();
  }, [runStages]);

  const failedStage = stages.find((s) => s.status === "error");

  return (
    <div className="mx-auto max-w-2xl px-5 py-12">
      <motion.h1
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="font-serif text-2xl font-bold text-ink-950"
      >
        解析存档
      </motion.h1>

      <div className="mt-3 rounded-lg border border-gold-500/40 bg-paper-100/70 px-4 py-3 text-xs text-ink-600">
        正在解析真实 CK3 存档。以下阶段由
        <span className="font-medium text-gold-700">后端真实结果</span>
        驱动（初检 → Mod → 一次 melt + 索引），非模拟进度。
      </div>

      <ol className="mt-8 space-y-0">
        {stages.map((stage, idx) => {
          const isLast = idx === stages.length - 1;
          return (
            <li key={stage.id}>
              <div
                className={cn(
                  "flex items-start gap-3 rounded-lg border px-4 py-3",
                  stage.status === "error"
                    ? "border-cinnabar-700/50 bg-cinnabar-700/5"
                    : "border-ink-400/40 bg-paper-50/70",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 w-6 text-center",
                    stage.status === "success" && "animate-seal-stamp",
                  )}
                >
                  <StatusIcon status={stage.status} />
                </span>
                <div className="min-w-0">
                  <span
                    className={cn(
                      stage.status === "pending" ? "text-ink-500" : "text-ink-900",
                    )}
                  >
                    {stage.label}
                  </span>
                  {stage.status === "error" && stage.error && (
                    <p className="mt-1 break-words text-sm text-cinnabar-700">
                      {stage.error}
                    </p>
                  )}
                </div>
              </div>
              {!isLast && (
                <motion.span
                  aria-hidden
                  initial={{ scaleY: 0 }}
                  animate={{ scaleY: stage.status === "success" ? 1 : 0 }}
                  transition={{ duration: 0.3, ease: "easeOut" }}
                  style={{ transformOrigin: "top" }}
                  className="mx-auto block h-3 w-px bg-ink-400/50"
                />
              )}
            </li>
          );
        })}
      </ol>

      {parseError && (
        <div className="mt-6" role="alert">
          <MuseumSurface
            variant="raised"
            className="border-cinnabar-700/40 p-4"
          >
            <p className="text-sm font-medium text-cinnabar-700">解析失败</p>
            <p className="mt-1 break-words text-sm text-ink-700">{parseError}</p>
            <button
              type="button"
              onClick={() => setShowDetail((v) => !v)}
              className="mt-2 text-xs text-ink-500 underline"
            >
              {showDetail ? "收起错误详情" : "展开错误详情"}
            </button>
            {showDetail && failedStage?.error && (
              <pre className="mt-2 overflow-auto rounded bg-ink-950/90 p-2 text-[11px] text-paper-100">
                {failedStage.error}
              </pre>
            )}
            <div className="mt-3 flex gap-2">
              <SealButton variant="primary" seal onClick={() => runStages()}>
                重试
              </SealButton>
              <SealButton variant="ghost" onClick={() => navigate(ROUTES.start)}>
                返回起始页
              </SealButton>
            </div>
          </MuseumSurface>
        </div>
      )}

      {/* 解析成功的仪式性反馈：朱砂落印（装饰，缺失素材则整个节点消失） */}
      {showSeal && (
        <div
          className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center"
          aria-hidden
        >
          <AssetImage
            src="/assets/oriental/red-seal.webp"
            className="h-28 w-28 animate-seal-stamp opacity-95"
            eager
          />
        </div>
      )}
    </div>
  );
}
