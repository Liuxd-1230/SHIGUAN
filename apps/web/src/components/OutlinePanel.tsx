import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LlmHealth, type OutlineGenerationResultData } from "../lib/api";
import MuseumSurface from "./MuseumSurface";
import SealButton from "./SealButton";
import InkDivider from "./InkDivider";

/**
 * AI 传记提纲面板（Phase 3A 5.11）。
 *
 * 约束：
 *  - 打开人物页面**不自动调用模型生成**；只有用户点击「生成提纲」才发起生成。
 *  - 模型健康探测只发一个最小 ping（不携带任何存档内容）。
 *  - 所有事实只来自后端压缩档案；展示层只呈现后端返回的提纲与告警。
 */
const STYLE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "vernacular_annals", label: "白话编年体" },
  { value: "serious_biography", label: "严肃传记体" },
  { value: "medieval_chronicle", label: "中古编年史风" },
  { value: "family_memoir", label: "家族回忆录风" },
  { value: "concise_profile", label: "简明档案式" },
  { value: "cold_historian", label: "冷峻史家笔法" },
];

const MAX_EVENT_OPTIONS = [16, 24, 32, 48];

type GenStatus = "idle" | "loading";

export default function OutlinePanel({
  saveId,
  characterId,
}: {
  saveId: string;
  characterId: string;
}) {
  const [health, setHealth] = useState<LlmHealth | null>(null);
  const [healthState, setHealthState] = useState<"idle" | "checking">("idle");
  const [style, setStyle] = useState("serious_biography");
  const [includeInferred, setIncludeInferred] = useState(true);
  const [includeUncertain, setIncludeUncertain] = useState(true);
  const [maxEvents, setMaxEvents] = useState(24);
  const [genStatus, setGenStatus] = useState<GenStatus>("idle");
  const [result, setResult] = useState<OutlineGenerationResultData | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 健康探测：只 ping 模型服务（无存档数据），绝不自动生成。
  const checkHealth = useCallback(async () => {
    setHealthState("checking");
    try {
      const h = await api.getLlmHealth();
      setHealth(h);
    } catch {
      setHealth(null);
    } finally {
      setHealthState("idle");
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    return () => abortRef.current?.abort();
  }, [checkHealth]);

  async function generate() {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setGenStatus("loading");
    setRequestError(null);
    try {
      const res = await api.generateOutline(
        saveId,
        characterId,
        { style, includeInferred, includeUncertain, maxEvents },
        ctrl.signal,
      );
      setResult(res);
      if (res.valid && res.error) {
        // 兼容旧契约：成功时 error 为空。
        setRequestError(null);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setRequestError(err instanceof Error ? err.message : String(err));
      setResult(null);
    } finally {
      setGenStatus("idle");
    }
  }

  const modelStatus = renderModelStatus(health, healthState);

  return (
    <MuseumSurface variant="raised" className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-serif text-lg font-bold text-ink-900">
            AI 传记提纲
          </h2>
          <p className="mt-1 text-xs text-ink-500">
            仅依据存档证据压缩档案生成；提纲中的事件 id 均来自时间线。
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-600">
          {modelStatus}
          <SealButton
            variant="ghost"
            className="min-h-[2rem] px-2 py-1 text-xs"
            onClick={() => void checkHealth()}
            disabled={healthState === "checking"}
          >
            {healthState === "checking" ? "检测中…" : "检测模型"}
          </SealButton>
        </div>
      </div>

      <InkDivider className="my-3" />

      {/* 生成设置 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block">
          <span className="text-xs font-semibold text-ink-700">文风</span>
          <select
            value={style}
            onChange={(e) => setStyle(e.target.value)}
            className="mt-1 w-full rounded-lg border border-ink-400/50 bg-paper-50 px-2 py-2 text-sm text-ink-900"
          >
            {STYLE_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-ink-700">事件上限</span>
          <select
            value={maxEvents}
            onChange={(e) => setMaxEvents(Number(e.target.value))}
            className="mt-1 w-full rounded-lg border border-ink-400/50 bg-paper-50 px-2 py-2 text-sm text-ink-900"
          >
            {MAX_EVENT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} 条
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-end gap-2 pb-2">
          <input
            type="checkbox"
            checked={includeInferred}
            onChange={(e) => setIncludeInferred(e.target.checked)}
            className="h-4 w-4"
          />
          <span className="text-xs text-ink-700">包含推断事件</span>
        </label>
        <label className="flex items-end gap-2 pb-2">
          <input
            type="checkbox"
            checked={includeUncertain}
            onChange={(e) => setIncludeUncertain(e.target.checked)}
            className="h-4 w-4"
          />
          <span className="text-xs text-ink-700">包含存疑事件</span>
        </label>
      </div>

      <div className="mt-4">
        <SealButton
          variant="primary"
          seal
          onClick={() => void generate()}
          disabled={genStatus === "loading"}
          aria-busy={genStatus === "loading"}
        >
          {genStatus === "loading" ? "生成中…" : "生成提纲"}
        </SealButton>
      </div>

      {/* 请求层错误（后端不可达等） */}
      {requestError && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger-700"
        >
          {requestError}
        </div>
      )}

      {/* 生成结果 */}
      {result && !result.valid && result.error && (
        <GenerationError error={result.error} />
      )}
      {result?.valid && result.outline && (
        <OutlineResult result={result} />
      )}
    </MuseumSurface>
  );
}

function renderModelStatus(
  health: LlmHealth | null,
  state: "idle" | "checking",
) {
  if (state === "checking") {
    return <span className="text-ink-500">模型检测中…</span>;
  }
  if (!health) {
    return <span className="text-ink-500">无法探测模型状态</span>;
  }
  if (!health.configured) {
    return (
      <span className="text-danger-700">
        ⚠ 未配置模型提供者（{health.message ?? health.provider}）
      </span>
    );
  }
  if (health.reachable) {
    return (
      <span className="text-emerald-700">
        ● {health.provider}
        {health.model ? ` / ${health.model}` : ""}
      </span>
    );
  }
  return (
    <span className="text-amber-700">
      ⚠ 模型不可达（{health.message ?? "请启动本地模型服务"}）
    </span>
  );
}

function GenerationError({ error }: { error: { code: string; message: string } }) {
  const hints: Record<string, string> = {
    provider_not_configured:
      "请在 .env 中设置 LLM_PROVIDER（如 openai_compatible）并确认 LLM_BASE_URL / LLM_MODEL。",
    provider_unreachable: "请确认本地模型服务已启动（默认 http://127.0.0.1:8080）。",
    provider_timeout: "模型响应超时，请减小事件上限或检查模型负载后重试。",
    remote_provider_disabled:
      "远程模型被禁用：如需调用远程服务，请在 .env 设置 LLM_ALLOW_REMOTE=true。",
    insufficient_timeline: "该人物时间线为空或可用事件过少，无法生成提纲。",
    invalid_event_reference: "模型引用了非本人物的事件，已按规则拒绝（不展示错误内容）。",
    invalid_model_output: "模型输出未通过 JSON 契约校验，请重试。",
  };
  return (
    <div
      role="alert"
      className="mt-4 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger-700"
    >
      <p className="font-semibold">提纲生成失败</p>
      <p className="mt-1">{error.message}</p>
      {hints[error.code] && <p className="mt-1 text-xs text-ink-600">{hints[error.code]}</p>}
    </div>
  );
}

function OutlineResult({ result }: { result: OutlineGenerationResultData }) {
  const outline = result.outline;
  if (!outline) return null;
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
        <span>已生成（重试 {result.retryCount} 次）</span>
        {result.warnings.length > 0 && (
          <span className="text-amber-700">{result.warnings.join("；")}</span>
        )}
        {result.stale && (
          <span className="text-amber-700">⚠ 该提纲基于旧存档，请重新生成</span>
        )}
      </div>
      <div className="mt-3 space-y-3">
        {outline.chapters.map((ch, i) => (
          <div
            key={ch.id}
            className="rounded-lg border border-ink-400/40 bg-paper-100/60 px-3 py-2"
          >
            <p className="text-sm font-semibold text-ink-900">
              {i + 1}. {ch.title}
              <span className="ml-2 text-[11px] font-normal text-ink-500">
                {ch.eventIds.length} 条事件
              </span>
            </p>
            <p className="mt-1 text-sm leading-relaxed text-ink-700">{ch.summary}</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {ch.eventIds.map((eid) => (
                <span
                  key={eid}
                  className="rounded bg-gold-500/20 px-1.5 py-0.5 text-[11px] text-ink-700"
                >
                  {eid}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
