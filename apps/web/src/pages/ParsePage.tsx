import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useStore } from "../store";
import { mockParseService } from "../lib/mockParse";
import { mockCharacterRepository } from "../lib/characterRepository";
import { navigate, ROUTES } from "../lib/router";
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

export default function ParsePage({
  stageDelayMs = 600,
  successSealMs = 700,
}: {
  /** 每阶段耗时（毫秒）。生产默认 600；测试可注入更小值以加速。 */
  stageDelayMs?: number;
  /** 解析成功后展示朱砂落印的时长（毫秒），随后进入选择页。 */
  successSealMs?: number;
}) {
  const parseStages = useStore((s) => s.parseStages);
  const parseError = useStore((s) => s.parseError);
  const resetParse = useStore((s) => s.resetParse);
  const setParseStage = useStore((s) => s.setParseStage);
  const setParseError = useStore((s) => s.setParseError);
  const setIndex = useStore((s) => s.setIndex);

  const abortRef = useRef<AbortController | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [showSeal, setShowSeal] = useState(false);

  // 初始失败注入：?fail=<stage> 用于演示/测试"解析失败与重试"。
  const initialFailAt =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("fail") ?? undefined
      : undefined;

  const startParse = useCallback(
    async (failAt?: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      resetParse();
      setParseError(null);
      setShowDetail(false);

      try {
        await mockParseService.run(
          { failAt, stageDelayMs, signal: controller.signal },
          {
            onStage: (id, status, extra) => setParseStage(id, status, extra),
          },
        );
        if (controller.signal.aborted) return;
        // 阶段全部成功 → 载入索引 → 展示朱砂落印（仪式性反馈）→ 进入选择页
        const { meta, characterIndex } =
          await mockCharacterRepository.loadIndex();
        if (controller.signal.aborted) return;
        setIndex(meta, characterIndex);
        setShowSeal(true);
        setTimeout(() => navigate(ROUTES.characters), successSealMs);
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        const message = e instanceof Error ? e.message : String(e);
        setParseError(message);
      }
    },
    [
      resetParse,
      setParseError,
      setParseStage,
      setIndex,
      setShowDetail,
      stageDelayMs,
      successSealMs,
    ],
  );

  useEffect(() => {
    startParse(initialFailAt);
    return () => abortRef.current?.abort();
  }, [startParse, initialFailAt]);

  const failedStage = parseStages.find((s) => s.status === "error");

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
        当前为 <span className="font-medium text-gold-700">Mock 演示流程</span>
        ，尚未解析真实 CK3 存档。以下阶段由 Mock 顺序驱动，状态真实反映任务进度（非随机定时进度条）。
      </div>

      <ol className="mt-8 space-y-0">
        {parseStages.map((stage, idx) => {
          const isLast = idx === parseStages.length - 1;
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
                    <p className="mt-1 text-sm text-cinnabar-700">{stage.error}</p>
                  )}
                </div>
              </div>
              {/* 阶段连接墨线：当前阶段成功后自上方延伸向下一阶段（逐段延伸） */}
              {!isLast && (
                <motion.span
                  aria-hidden
                  initial={{ scaleY: 0 }}
                  animate={{ scaleY: stage.status === "success" ? 1 : 0 }}
                  transition={{ duration: 0.3, ease: "easeOut" }}
                  style={{ transformOrigin: "top" }}
                  className="block h-3 w-px bg-ink-400/50 mx-auto"
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
              <SealButton
                variant="primary"
                seal
                onClick={() => {
                  // 重试：清除 URL 中的 fail 注入，从头再跑
                  if (initialFailAt) navigate(ROUTES.parse, true);
                  startParse(undefined);
                }}
              >
                重试
              </SealButton>
              <SealButton
                variant="ghost"
                onClick={() => navigate(ROUTES.start)}
              >
                返回起始页
              </SealButton>
            </div>
          </MuseumSurface>
        </div>
      )}

      {/* 解析成功的仪式性反馈：朱砂落印（装饰，缺失素材则整节点消失） */}
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
